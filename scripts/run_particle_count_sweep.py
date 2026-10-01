#!/usr/bin/env python3
"""Run each logarithmic particle-count configuration ten times, using half the available CPUs."""

import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "examples" / "characterization" / "particle_count_log"


def run_one(config: Path, repetition: int, batch: Path, environment: dict[str, str]) -> tuple[str, int]:
    name = f"{config.stem}_rep_{repetition:02d}"
    destination = batch / name
    destination.mkdir()
    command = [
        sys.executable, "-m", "jpgen", str(config),
        "--output-dir", str(destination),
        "--label", name,
        "--experiment", "particle_count_characterization",
        "--progress", "none",
    ]
    with (destination / "launch.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
    return name, result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show the workload without starting simulations")
    args = parser.parse_args()

    configs = sorted(CONFIG_DIR.glob("particles_*.yaml"))
    expected = [1000, 1459, 2129, 3107, 4534, 6616, 9655, 14089, 20559, 30000]
    counts = []
    for config in configs:
        data = yaml.safe_load(config.read_text(encoding="utf-8"))
        counts.append(data["packing"]["count"])
        if data["dem"].get("backend_options", {}).get("threads", 1) != 1:
            parser.error(f"{config} must use exactly one Kratos thread per run")
    if counts != expected:
        parser.error(f"Expected ten logarithmically spaced YAML configurations with counts {expected}")

    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    workers = max(1, available // 2)
    print(f"Available CPU threads: {available}; parallel runs: {workers}; total runs: {len(configs) * 10}", flush=True)
    if args.dry_run:
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%SZ")
    batch = ROOT / "runs" / "particle_count_characterization" / stamp
    batch.mkdir(parents=True, exist_ok=False)
    print(f"Results: {batch}", flush=True)

    environment = os.environ.copy()
    environment.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", PYTHONNOUSERSITE="1")
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, config, repetition, batch, environment)
                   for config in configs for repetition in range(1, 11)]
        for future in as_completed(futures):
            name, returncode = future.result()
            if returncode:
                failures.append(name)
            print(f"{'FAIL' if returncode else 'OK  '} {name} ({returncode})", flush=True)

    print(f"Completed: {len(configs) * 10 - len(failures)}; failed: {len(failures)}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
