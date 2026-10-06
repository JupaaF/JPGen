#!/usr/bin/env python3
"""Run six friction coefficients on ten shared initial packings."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

from jpgen.dem.configuration import build_dem_plan
from jpgen.packing.configuration import build_packing_plan
from jpgen.run_reader import RunReader


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "examples/characterization/friction"
EXPERIMENT = "friction_characterization"
FRICTIONS = (0.0, 0.1, 0.2, 0.4, 0.6, 0.8)


def repetition_seed(seed, repetition):
    payload = f"JPGen.friction:{seed}:{repetition}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:16], "big")


def write_yaml(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run_one(config, destination, environment):
    destination.mkdir(exist_ok=True)
    command = [sys.executable, "-m", "jpgen", str(config),
               "--output-dir", str(destination), "--label", destination.name,
               "--experiment", EXPERIMENT, "--progress", "none"]
    with (destination / "launch.log").open("w", encoding="utf-8") as log:
        try:
            result = subprocess.run(command, cwd=ROOT, env=environment,
                                    stdout=log, stderr=subprocess.STDOUT)
        except OSError as error:
            log.write(str(error) + "\n")
            return 1
    return result.returncode


def load_templates():
    templates = []
    reference = None
    for path in sorted(CONFIG_DIR.glob("friction_*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        packing = data["packing"]
        dem = data["dem"]
        mu = dem["contact"]["static_friction"]
        if dem["contact"]["dynamic_friction"] != mu:
            raise ValueError(f"{path}: static and dynamic friction must match")
        if (packing["count"] != 15000 or packing["target_solid_fraction"] != 0.56
                or packing["sizing_method"] != "variable_box_fraction" or "seed" in packing):
            raise ValueError(f"{path}: expected 15000 particles, fraction 0.56 and no seed")
        if dem["engine"] != "liggghts" or dem["backend_options"]["threads"] != 1:
            raise ValueError(f"{path}: expected single-thread LIGGGHTS")
        normalized = deepcopy(data)
        for field in ("static_friction", "dynamic_friction"):
            normalized["dem"]["contact"][field] = 0.0
        if reference is None:
            reference = normalized
        elif normalized != reference:
            raise ValueError(f"{path}: only friction may differ between templates")
        plan = build_packing_plan(packing | {"seed": 0})
        build_dem_plan(dem).validate_box(plan.box)
        templates.append((path.stem, mu, data))
    if tuple(mu for _, mu, _ in templates) != FRICTIONS:
        raise ValueError(f"Expected exactly six coefficients: {FRICTIONS}")
    return templates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate and show workload; write nothing")
    parser.add_argument("--prepare-only", action="store_true", help="Generate shared packings and DEM inputs only")
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261005, help="Master seed for reproducible independent packings")
    parser.add_argument("--workers", type=int, help="Parallel jobs; default 75%% of available CPU threads")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs" / EXPERIMENT)
    args = parser.parse_args()
    if args.repetitions < 1 or args.seed < 0 or args.workers is not None and args.workers < 1:
        parser.error("Repetitions and workers must be positive; seed must be nonnegative")
    try:
        templates = load_templates()
    except (ValueError, KeyError) as error:
        parser.error(str(error))
    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    workers = min(args.workers or max(1, available * 3 // 4), len(templates) * args.repetitions)
    seeds = [repetition_seed(args.seed, rep) for rep in range(1, args.repetitions + 1)]
    print(f"Friction: {FRICTIONS}; shared packings: {args.repetitions}; "
          f"DEM runs: {len(templates) * args.repetitions}; workers: {workers}", flush=True)
    print(f"Master seed: {args.seed}; cycle: 5 -> 200 -> 5 kPa; baseline: 0.4", flush=True)
    if args.dry_run:
        return 0
    if not args.prepare_only:
        # The runtime is common to all templates; probe it once before allocating work.
        dem = build_dem_plan(templates[0][2]["dem"])
        dem.backend.validate(dem)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%fZ")
    batch = args.output_dir.resolve() / stamp
    (batch / "templates").mkdir(parents=True, exist_ok=False)
    for name, _, data in templates:
        write_yaml(batch / "templates" / f"{name}.yaml", data)
    packings = []
    for rep, seed in enumerate(seeds, 1):
        directory = batch / "packings" / f"packing_rep_{rep:02d}"
        directory.mkdir(parents=True)
        config = directory / "packing.yaml"
        write_yaml(config, {"packing": templates[0][2]["packing"] | {"seed": seed}})
        packings.append({"repetition": rep, "seed": seed,
                         "directory": str(directory.relative_to(batch)), "status": "pending"})
    metadata = {"experiment": EXPERIMENT, "master_seed": args.seed,
                "repetitions": args.repetitions, "frictions": FRICTIONS, "baseline": 0.4,
                "workers": workers, "packings": packings, "jobs": []}
    write_json(batch / "batch.json", metadata)
    print(f"Results: {batch}", flush=True)
    environment = os.environ.copy()
    environment.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                       MKL_NUM_THREADS="1", PYTHONNOUSERSITE="1")
    failures = []
    with ThreadPoolExecutor(max_workers=min(workers, args.repetitions)) as pool:
        pending = {pool.submit(run_one, batch / item["directory"] / "packing.yaml",
                               batch / item["directory"], environment): item for item in packings}
        for future in as_completed(pending):
            item = pending[future]
            directory = batch / item["directory"]
            try:
                if future.result():
                    raise ValueError("Packing generation failed; see launch.log")
                manifests = list(directory.glob("*/run.json"))
                if len(manifests) != 1:
                    raise ValueError("Expected one packing run")
                reader = RunReader(manifests[0].parent)
                if reader.manifest["status"] != "completed":
                    raise ValueError("Packing run did not complete")
                source = manifests[0].parent / "stages/packing/results/packing.h5"
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                item.update(status="completed", file=str(source.relative_to(batch)), sha256=digest)
                for name, mu, data in templates:
                    job_name = f"{name}_rep_{item['repetition']:02d}"
                    destination = batch / job_name
                    destination.mkdir()
                    config = destination / "config.yaml"
                    write_yaml(config, {"packing_source": {"file": str(source), "sha256": digest,
                                                          "exports": []}, "dem": data["dem"]})
                    metadata["jobs"].append({"job": job_name, "friction": mu,
                        "repetition": item["repetition"], "seed": item["seed"],
                        "packing_sha256": digest, "status": "prepared"})
            except Exception as error:
                item.update(status="failed", error=str(error))
                failures.append(directory.name)
            write_json(batch / "batch.json", metadata)
            print(f"{item['status'].upper()} {directory.name}", flush=True)

    if not args.prepare_only:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(run_one, batch / job["job"] / "config.yaml",
                                   batch / job["job"], environment): job for job in metadata["jobs"]}
            for future in as_completed(pending):
                job = pending[future]
                try:
                    returncode = future.result()
                except Exception as error:
                    job["error"] = str(error)
                    returncode = 1
                job.update(status="failed" if returncode else "completed", returncode=returncode)
                if returncode:
                    failures.append(job["job"])
                write_json(batch / "batch.json", metadata)
                print(f"{job['status'].upper()} {job['job']} ({returncode})", flush=True)
    expected = len(templates) * args.repetitions
    completion = {"prepared": len(metadata["jobs"]),
                  "completed": sum(job["status"] == "completed" for job in metadata["jobs"]),
                  "failed": failures, "skipped_dem": expected - len(metadata["jobs"]),
                  "prepare_only": args.prepare_only}
    write_json(batch / "completion.json", completion)
    print(json.dumps(completion), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
