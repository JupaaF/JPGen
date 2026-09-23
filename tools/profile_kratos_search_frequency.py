"""Measure neighbour-search frequency on a prepared JPGen Kratos case.

The copied cases keep the packing, material, time step and first protocol
controller.  Only ``NeighbourSearchFrequency`` changes.  The protocol is
truncated to an exact, common number of steps so final particle states and
sampled macroscopic observables can be compared directly.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import statistics
import subprocess
import sys
import time

import numpy as np


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def prepare(source, target, frequency, tolerance_percent, steps, sample_every):
    shutil.copytree(source / "input", target / "input")
    (target / "native_results").mkdir()

    parameters_path = target / "input/ProjectParametersDEM.json"
    parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
    dt = parameters["MaxTimeStep"]
    duration = steps * dt
    parameters.update(NeighbourSearchFrequency=frequency, DeltaOption="Relative",
                      SearchToleranceMultiplier=tolerance_percent / 100.0,
                      FinalTime=duration,
                      BoundingBoxStopTime=duration)
    parameters_path.write_text(json.dumps(parameters, indent=2) + "\n", encoding="utf-8")

    execution_path = target / "input/execution.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    first_stage = execution["protocol"]["stages"][0]
    first_stage["until"] = {"observable": "stage_time", "op": "above", "value": duration}
    first_stage["max_duration"] = duration
    execution["protocol"] = {"sample_every": sample_every, "stages": [first_stage]}
    execution.update(steps=steps, end_time=duration)
    execution_path.write_text(json.dumps(execution, indent=2) + "\n", encoding="utf-8")


def read_state(directory):
    metadata = json.loads((directory / "final_state.json").read_text(encoding="utf-8"))
    with np.load(directory / "final_state.npz", allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    order = np.argsort(arrays["ids"])
    return metadata, {name: values[order] for name, values in arrays.items()}


def compare_states(reference, candidate, density):
    ref_meta, ref = read_state(reference)
    other_meta, other = read_state(candidate)
    if not np.array_equal(ref["ids"], other["ids"]):
        raise ValueError("Particle IDs changed")
    if not np.array_equal(ref["radii"], other["radii"]):
        raise ValueError("Particle radii changed")
    if ref_meta["time"] != other_meta["time"]:
        raise ValueError("Final times differ")
    if not all(np.isfinite(values).all() for values in other.values()):
        raise ValueError("Candidate state contains non-finite values")

    ref_lengths = np.asarray(ref_meta["box"]["lengths"])
    other_lengths = np.asarray(other_meta["box"]["lengths"])
    position_delta = other["positions"] - ref["positions"]
    position_delta -= ref_lengths * np.rint(position_delta / ref_lengths)
    mass = density * 4.0 * np.pi / 3.0 * ref["radii"] ** 3
    inertia = 0.4 * mass * ref["radii"] ** 2

    def relative_l2(name):
        denominator = np.linalg.norm(ref[name])
        return float(np.linalg.norm(other[name] - ref[name]) / denominator) if denominator else None

    def energy(state):
        return float(0.5 * np.sum(mass[:, None] * state["velocities"] ** 2)
                     + 0.5 * np.sum(inertia[:, None] * state["angular_velocities"] ** 2))

    ref_energy = energy(ref)
    other_energy = energy(other)
    return {
        "box_length_max_abs_m": float(np.max(np.abs(other_lengths - ref_lengths))),
        "position_max_m": float(np.max(np.linalg.norm(position_delta, axis=1))),
        "velocity_max_m_s": float(np.max(np.linalg.norm(other["velocities"] - ref["velocities"], axis=1))),
        "angular_velocity_max_rad_s": float(np.max(np.linalg.norm(
            other["angular_velocities"] - ref["angular_velocities"], axis=1))),
        "velocity_relative_l2": relative_l2("velocities"),
        "angular_velocity_relative_l2": relative_l2("angular_velocities"),
        "kinetic_energy_relative_error": abs(other_energy / ref_energy - 1.0) if ref_energy else None,
    }


def read_observables(directory):
    records = []
    with (directory / "observables.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            records.append(json.loads(line))
    return records


def compare_observables(reference, candidate):
    ref = read_observables(reference)
    other = read_observables(candidate)
    if [row["step"] for row in ref] != [row["step"] for row in other]:
        raise ValueError("Observable samples are not aligned")
    result = {}
    for name in ("pressure", "solid_fraction", "kinetic_energy"):
        left = np.asarray([row["observables"][name] for row in ref])
        right = np.asarray([row["observables"][name] for row in other])
        scale = np.sqrt(np.mean(left ** 2))
        result[name + "_relative_rmse"] = float(np.sqrt(np.mean((right - left) ** 2)) / scale) if scale else None
        result[name + "_max_abs"] = float(np.max(np.abs(right - left)))
        result[name + "_final_relative_error"] = float(abs(right[-1] / left[-1] - 1.0)) if left[-1] else None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path, help="Prepared dem directory")
    parser.add_argument("output", type=Path)
    parser.add_argument("--frequencies", type=int, nargs="+", default=[1, 2, 5, 10])
    parser.add_argument("--search-tolerance-percentages", type=float, nargs="+",
                        default=[0.0, 0.1, 1.0],
                        help="Neighbour-search margins as percentages of each particle radius")
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--sample-every", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--resume", action="store_true",
                        help="Continue an interrupted campaign and keep completed variants")
    args = parser.parse_args()
    if (min(args.frequencies) < 1 or min(args.search_tolerance_percentages) < 0
            or min(args.steps, args.sample_every, args.repeats, args.threads) < 1):
        parser.error("frequencies, steps, sampling, repeats and threads must be positive")

    root = Path(__file__).resolve().parents[1]
    installation = root / "Kratos/bin/Release"
    args.output.mkdir(parents=True, exist_ok=args.resume)
    variants = [(frequency, percentage) for frequency in args.frequencies
                for percentage in args.search_tolerance_percentages]
    jobs = [(frequency, percentage, repeat) for repeat in range(args.repeats)
            for frequency, percentage in variants]
    random.Random(20260922).shuffle(jobs)
    rows = []
    total = len(jobs)
    for frequency, percentage, repeat in jobs:
        percentage_label = format(percentage, ".12g").replace(".", "p")
        target = (args.output / f"frequency_{frequency}_tolerance_{percentage_label}pct_repeat_{repeat}").resolve()
        measurement_path = target / "measurement.json"
        if args.resume and measurement_path.is_file():
            previous = json.loads(measurement_path.read_text(encoding="utf-8"))
            if previous.get("returncode") == 0:
                rows.append(previous)
                continue
        if target.exists():
            if target.parent != args.output.resolve():
                raise ValueError(f"Refusing to replace unexpected path: {target}")
            shutil.rmtree(target)
        write_json(args.output / "progress.json", {
            "status": "running", "completed": len(rows), "total": total,
            "current": {"frequency": frequency,
                        "search_tolerance_percent": percentage, "repeat": repeat},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        target.mkdir()
        prepare(args.case, target, frequency, percentage, args.steps, args.sample_every)
        environment = os.environ.copy()
        environment.update(OMP_NUM_THREADS=str(args.threads), OPENBLAS_NUM_THREADS="1")
        environment["PYTHONPATH"] = str(installation) + os.pathsep + environment.get("PYTHONPATH", "")
        environment["LD_LIBRARY_PATH"] = str(installation / "libs") + os.pathsep + environment.get("LD_LIBRARY_PATH", "")
        command = [sys.executable, str(root / "tools/kratos_phase_profile.py"),
                   str(target / "input/run.py")]
        started = time.perf_counter()
        with (target / "stdout.log").open("w") as stdout, (target / "stderr.log").open("w") as stderr:
            completed = subprocess.run(command, env=environment, stdout=stdout, stderr=stderr,
                                       timeout=args.timeout)
        row = {"frequency": frequency, "search_tolerance_percent": percentage,
               "repeat": repeat, "threads": args.threads,
               "steps": args.steps, "wall_seconds": time.perf_counter() - started,
               "returncode": completed.returncode}
        report_path = target / "native_results/execution_report.json"
        if report_path.exists():
            row["execution"] = json.loads(report_path.read_text(encoding="utf-8"))
        match = re.search(r"Elapsed processing time \(sum across cores\): ([0-9.]+) seconds",
                          (target / "stdout.log").read_text(encoding="utf-8"))
        if match:
            row["solver_cpu_seconds"] = float(match.group(1))
        write_json(measurement_path, row)
        print(json.dumps(row), flush=True)
        if completed.returncode:
            raise RuntimeError(f"Kratos failed in {target}")
        rows.append(row)
        write_json(args.output / "progress.json", {
            "status": "running", "completed": len(rows), "total": total,
            "current": None, "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    references = sorted(args.output.glob("frequency_1_tolerance_0pct_repeat_*"))
    if not references:
        raise ValueError("Frequency 1 is required as the numerical reference")
    reference = references[0] / "native_results"
    execution = json.loads((args.case / "input/execution.json").read_text(encoding="utf-8"))
    summary = {}
    for frequency, percentage in variants:
        subset = [row for row in rows if row["frequency"] == frequency
                  and row["search_tolerance_percent"] == percentage]
        percentage_label = format(percentage, ".12g").replace(".", "p")
        key = f"frequency_{frequency}_tolerance_{percentage_label}pct"
        representative = args.output / f"{key}_repeat_0" / "native_results"
        wall = [row["wall_seconds"] for row in subset]
        summary[key] = {
            "frequency": frequency, "search_tolerance_percent": percentage,
            "repetitions": len(subset), "median_wall_seconds": statistics.median(wall),
            "min_wall_seconds": min(wall), "max_wall_seconds": max(wall),
            "state_error": compare_states(reference, representative, execution["density"]),
            "observable_error": compare_observables(reference, representative),
        }
        cpu = [row.get("solver_cpu_seconds") for row in subset]
        if all(value is not None for value in cpu):
            summary[key]["median_solver_cpu_seconds"] = statistics.median(cpu)
    baseline = summary["frequency_1_tolerance_0pct"]["median_wall_seconds"]
    for values in summary.values():
        values["speedup_vs_frequency_1"] = baseline / values["median_wall_seconds"]

    result = {"method": {"source_case": str(args.case.resolve()),
                         "frequencies": args.frequencies,
                         "search_tolerance_percentages": args.search_tolerance_percentages,
                         "steps": args.steps, "sample_every": args.sample_every,
                         "repeats": args.repeats, "threads": args.threads,
                         "packing_sha256": digest(args.case / "input/particlesDEM.mdpa")},
              "summary": summary, "runs": rows}
    write_json(args.output / "summary.json", result)
    write_json(args.output / "progress.json", {
        "status": "complete", "completed": total, "total": total,
        "current": None, "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
