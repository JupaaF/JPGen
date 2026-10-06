#!/usr/bin/env python3
"""Export equilibrated friction paths and paired differences against mu=0.4."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import yaml
from jpgen.run_reader import RunReader

from analyze_contact_distributions import extract


FIELDS = ("mean_coordination_number", "solid_fraction", "bulk_density",
          "overlap_length", "overlap_area", "overlap_volume", "cv_depth",
          "mean_depth_D50", "thermal_tensor_trace", "fabric_second_invariant")


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def checkpoints(batch, job):
    manifests = list((batch / job["job"]).glob("*/run.json"))
    if len(manifests) != 1:
        raise ValueError("Expected one run")
    reader = RunReader(manifests[0].parent)
    if reader.manifest["status"] != "completed":
        raise ValueError(f"Run status: {reader.manifest['status']}")
    effective = reader.directory / "config/effective.yaml"
    configuration = yaml.safe_load(effective.read_text(encoding="utf-8"))
    # JPGen serializes its own snapshot; its file hash can differ from the input.
    sources = json.loads((reader.directory / "provenance/sources.json").read_text(encoding="utf-8"))["sources"]
    if not any(source.get("relationship") == "uses_packing"
               and source.get("sha256") == job["packing_sha256"] for source in sources):
        raise ValueError("Shared packing hash mismatch")
    snapshot = reader.directory / "stages/packing/results/packing.h5"
    if hashlib.sha256(snapshot.read_bytes()).hexdigest() != configuration["packing_source"]["sha256"]:
        raise ValueError("Run packing snapshot hash mismatch")
    contact = configuration["dem"]["contact"]
    if any(contact[field] != job["friction"] for field in ("static_friction", "dynamic_friction")):
        raise ValueError("Friction does not match batch")
    rows = []
    for record in reader.states(accepted_only=True):
        if record.get("phase") != "end" or record.get("target", {}).get("observable") != "pressure":
            continue
        path = record["path"]
        if "loading_5_to_200kPa/" in path:
            stage = "loading"
        elif "unloading_200_to_5kPa/" in path:
            stage = "unloading"
        else:
            continue
        obs = record["observables"]
        row = {"run": job["job"], "run_id": reader.manifest["run_id"],
               "state_id": record["state_id"], "friction": job["friction"],
               "repetition": job["repetition"], "seed": job["seed"],
               "packing_sha256": job["packing_sha256"], "stage": stage,
               "checkpoint": record["target"]["index"], "target_pressure": record["target"]["value"],
               "pressure": obs["pressure"], "solid_fraction": obs["solid_fraction"],
               "mean_coordination_number": obs["mean_coordination_number"],
               "bulk_density": obs["bulk_density"],
               "fabric_second_invariant": obs["fabric_second_invariant"],
               "thermal_tensor_trace": 3 * obs["thermal_conductivity_trace"],
               "normalized_kinetic_energy": obs["normalized_kinetic_energy"],
               "unbalanced_force": obs["unbalanced_force"]}
        # Use the same exact periodic contact geometry as the existing overlap study.
        geometry = extract(reader.directory, row, audit_overlaps=False)
        row.update(overlap_length=geometry["sum_depth_m"], overlap_area=geometry["sum_area_m2"],
                   overlap_volume=geometry["sum_volume_m3"], cv_depth=geometry["cv_depth"],
                   mean_depth_D50=geometry["mean_depth_D50"])
        if abs(geometry["contact_count_difference"]) > 0.5:
            raise ValueError("Geometric contact count differs from DEM MCN")
        if not np.isclose(geometry["thermal_tensor_trace"], row["thermal_tensor_trace"], rtol=1e-7, atol=1e-12):
            raise ValueError("Reconstructed thermal trace differs from DEM")
        rows.append(row)
    for stage in ("loading", "unloading"):
        branch = [row for row in rows if row["stage"] == stage]
        if len(branch) != 20 or {row["checkpoint"] for row in branch} != set(range(1, 21)):
            raise ValueError(f"Incomplete {stage} path")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path, help="Batch directory containing batch.json")
    parser.add_argument("--bootstrap", type=int, default=2000)
    args = parser.parse_args()
    if args.bootstrap < 1:
        parser.error("Bootstrap count must be positive")
    batch = args.batch.resolve()
    metadata = json.loads((batch / "batch.json").read_text(encoding="utf-8"))
    if metadata["experiment"] != "friction_characterization":
        parser.error("Expected a friction characterization batch")
    rows, excluded = [], []
    for job in metadata["jobs"]:
        try:
            rows.extend(checkpoints(batch, job))
            print(f"Read {job['job']}", flush=True)
        except (OSError, ValueError, KeyError) as error:
            excluded.append({"job": job["job"], "reason": str(error)})
            print(f"Excluded {job['job']}: {error}", flush=True)
    if not rows:
        parser.error("No complete equilibrated paths available")

    # Interpolate each branch in log(actual pressure), without extrapolation.
    # Each coefficient is paired with the baseline from the SAME initial packing.
    paired = []
    for mu in metadata["frictions"]:
        if mu == metadata["baseline"]:
            continue
        for rep in range(1, metadata["repetitions"] + 1):
            for stage in ("loading", "unloading"):
                selected = []
                for coefficient in (mu, metadata["baseline"]):
                    branch = sorted((r for r in rows if r["friction"] == coefficient
                                     and r["repetition"] == rep and r["stage"] == stage),
                                    key=lambda r: r["target_pressure"])
                    selected.append(branch)
                current, baseline = selected
                if not current or not baseline:
                    continue
                if (current[0]["packing_sha256"] != baseline[0]["packing_sha256"]
                        or current[0]["seed"] != baseline[0]["seed"]):
                    raise ValueError("Cannot pair different initial packings")
                p, p0 = [np.array([r["pressure"] for r in branch]) for branch in selected]
                if np.any(np.diff(p) <= 0) or np.any(np.diff(p0) <= 0):
                    raise ValueError("Actual pressure must increase with targets for interpolation")
                for target in [r["target_pressure"] for r in baseline]:
                    if not max(p[0], p0[0]) <= target <= min(p[-1], p0[-1]):
                        continue
                    row = {"friction": mu, "baseline": metadata["baseline"], "repetition": rep,
                           "seed": current[0]["seed"], "packing_sha256": current[0]["packing_sha256"],
                           "stage": stage, "pressure": target}
                    for field in FIELDS:
                        value = np.interp(np.log(target), np.log(p), [r[field] for r in current])
                        reference = np.interp(np.log(target), np.log(p0), [r[field] for r in baseline])
                        row[field + "_delta"] = float(value - reference)
                    paired.append(row)
    rng = np.random.default_rng(20261005)
    summary = []
    for mu, stage, pressure in sorted({(r["friction"], r["stage"], r["pressure"]) for r in paired}):
        group = [r for r in paired if (r["friction"], r["stage"], r["pressure"]) == (mu, stage, pressure)]
        indices = rng.integers(len(group), size=(args.bootstrap, len(group)))
        for field in FIELDS:
            values = np.array([r[field + "_delta"] for r in group])
            low, high = np.quantile(values[indices].mean(axis=1), [0.025, 0.975])
            summary.append({"friction": mu, "baseline": metadata["baseline"], "stage": stage,
                            "pressure": pressure, "observable": field, "pairs": len(group),
                            "mean_delta": float(values.mean()),
                            "ci95_low": float(low) if len(group) > 1 else "",
                            "ci95_high": float(high) if len(group) > 1 else ""})
    output = batch / "analysis"
    output.mkdir(exist_ok=True)
    write_csv(output / "checkpoints.csv", rows)
    if paired:
        write_csv(output / "paired_differences.csv", paired)
        write_csv(output / "paired_summary.csv", summary)
    else:
        # Remove obsolete derived tables when the available run set no longer has pairs.
        for name in ("paired_differences.csv", "paired_summary.csv"):
            (output / name).unlink(missing_ok=True)
    (output / "analysis.json").write_text(json.dumps({
        "baseline": metadata["baseline"], "checkpoints": len(rows), "paired_points": len(paired),
        "excluded": excluded, "bootstrap": args.bootstrap, "bootstrap_seed": 20261005,
        "matching": "Linear interpolation in log(actual pressure), no extrapolation; separate branches",
        "difference": "mu minus baseline, paired by initial packing",
        "thermal_tensor_trace": "Dimensionless geometric tensor trace, not W/(m*K)",
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Analysis: {output}; excluded runs: {len(excluded)}; paired points: {len(paired)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
