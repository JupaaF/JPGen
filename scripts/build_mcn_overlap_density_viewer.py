#!/usr/bin/env python3
"""Build an offline 3D HTML snapshot of completed MCN/overlap/density runs."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
BATCHES = ROOT / "runs" / "mcn_overlap_density_characterization"
TEMPLATE = ROOT / "examples" / "characterization" / "mcn_overlap_density_dashboard.html"


def read_records(path):
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def measure_overlap(first, second, distances, cell_volume):
    """Reduce pair intersections without modifying any saved particle state."""
    depth = np.maximum(first + second - distances, 0)
    contained = distances <= np.abs(first - second)
    partial = ~contained
    area, volume = np.zeros_like(depth), np.zeros_like(depth)
    volume[contained] = 4 * np.pi / 3 * np.minimum(first[contained], second[contained])**3
    r1, r2, d, penetration = first[partial], second[partial], distances[partial], depth[partial]
    h1 = np.clip(penetration * (2 * r2 - penetration) / (2 * d), 0, 2 * r1)
    h2 = np.clip(penetration * (2 * r1 - penetration) / (2 * d), 0, 2 * r2)
    area[partial] = np.pi * np.maximum(h1 * (2 * r1 - h1), 0)
    volume[partial] = np.pi / 3 * (h1**2 * (3 * r1 - h1) + h2**2 * (3 * r2 - h2))
    total_length, total_area, total_volume = float(depth.sum()), float(area.sum()), float(volume.sum())
    length = cell_volume**(1 / 3)
    return {
        "overlap_length": total_length, "overlap_area": total_area, "overlap_volume": total_volume,
        "normalized_overlap_length": total_length / length,
        "normalized_overlap_area": total_area / length**2,
        "normalized_overlap_volume": total_volume / cell_volume,
    }


def geometry_overlaps(stem):
    metadata = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
    box = np.asarray(metadata["box"]["lengths"], dtype=float)
    if not metadata["box"]["periodic"]:
        raise ValueError(f"Expected a periodic checkpoint: {stem}")
    with np.load(stem.with_suffix(".npz"), allow_pickle=False) as arrays:
        radii = arrays["radii"]
        positions = (arrays["positions"] - metadata["box"]["origin"]) % box
        pairs = cKDTree(positions, boxsize=box).query_pairs(
            2 * float(radii.max()), output_type="ndarray")
        delta = np.abs(positions[pairs[:, 0]] - positions[pairs[:, 1]])
        distances = np.linalg.norm(np.minimum(delta, box - delta), axis=1)
        first, second = radii[pairs[:, 0]], radii[pairs[:, 1]]
        active = distances < first + second
        # Each unordered pair is counted once, including across periodic faces.
        return measure_overlap(first[active], second[active], distances[active],
                               cell_volume=float(np.prod(box)))


def extract_run(run, manifest):
    states = read_records(run / "stages/dem/results/states.jsonl")
    # A single checkpoint is often referenced by both the end and next start.
    boundaries = {state["state_id"]: state for state in states
                  if state.get("kind") == "stage" and state.get("phase") == "end"
                  and (not state.get("target") or state.get("accepted") is True)}
    required = {"mean_coordination_number", "solid_fraction", "bulk_density", "pressure"}
    wanted_steps = {state["step"] for state in boundaries.values()
                    if not required.issubset(state.get("observables", {}))}
    samples = {}
    with (run / "stages/dem/results/observables.jsonl").open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                sample = json.loads(line)
                if sample["step"] in wanted_steps:
                    samples[sample["step"]] = sample["observables"]
                    if wanted_steps.issubset(samples):
                        break
    result = []
    for state in sorted(boundaries.values(), key=lambda item: item["state_id"]):
        observed = dict(samples.get(state["step"], {}))
        observed.update(state.get("observables", {}))
        for field in ("mean_coordination_number", "solid_fraction", "bulk_density", "pressure"):
            if field not in observed:
                raise ValueError(f"Missing exact checkpoint observable {field}: {run}/{state['state_id']}")
        stem = run / state["state"]
        overlaps = geometry_overlaps(stem)
        path = state["path"]
        stage = "loading" if "loading_5_to" in path else "unloading" if "unloading_200_to" in path else "free"
        result.append({
            "run": manifest["label"], "run_id": manifest["run_id"],
            "checkpoint": int(state["state_id"].removeprefix("state_")),
            "state_id": state["state_id"], "stage": stage,
            "step": state["step"], "time": state["time"],
            "target_index": state.get("target", {}).get("index"),
            "target_pressure": state.get("target", {}).get("value"),
            **{field: observed[field] for field in
               ("mean_coordination_number", "solid_fraction", "bulk_density", "pressure")},
            **overlaps,
        })
    return result


def signature(run):
    paths = [run / "run.json", run / "stages/dem/results/states.jsonl",
             run / "stages/dem/results/observables.jsonl"]
    paths += sorted((run / "stages/dem/results/states").glob("*"))
    return [[str(path.relative_to(run)), path.stat().st_size, path.stat().st_mtime_ns]
            for path in paths if path.is_file()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, help="Batch directory (defaults to latest)")
    parser.add_argument("--output", type=Path, help="Output HTML (defaults to batch/viewer_3d.html)")
    args = parser.parse_args()
    batches = sorted(path for path in BATCHES.iterdir() if path.is_dir() and (path / "batch.json").is_file())
    if args.batch is None and not batches:
        parser.error("No study batches found")
    batch = (args.batch or batches[-1]).resolve()
    output = (args.output or batch / "viewer_3d.html").resolve()
    cache_path = output.with_suffix(".cache.json")
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    statuses = Counter()
    completed = []
    for job in sorted(batch.glob("mcn_overlap_density_rep_*")):
        manifests = sorted(job.glob("*/run.json"))
        if not manifests:
            statuses["queued"] += 1
            continue
        for path in manifests:
            manifest = json.loads(path.read_text())
            statuses[manifest["status"]] += 1
            if manifest["status"] == "completed":
                completed.append((path.parent, manifest))
    points, updated, failures = [], {}, []
    jobs = {}
    # Two extraction threads leave resources available for the running suite.
    with ThreadPoolExecutor(max_workers=2) as pool:
        for run, manifest in completed:
            key, source_signature = manifest["run_id"], signature(run)
            cached = cache.get(key)
            if cached and cached["signature"] == source_signature:
                updated[key] = cached
                points.extend(cached["points"])
            else:
                jobs[pool.submit(extract_run, run, manifest)] = (key, source_signature, manifest["label"])
        for future in as_completed(jobs):
            key, source_signature, label = jobs[future]
            try:
                rows = future.result()
                updated[key] = {"signature": source_signature, "points": rows}
                points.extend(rows)
                print(f"{label}: {len(rows)} checkpoints", flush=True)
            except (OSError, ValueError, KeyError) as error:
                failures.append(f"{label}: {error}")
                print(f"Skipped {label}: {error}", flush=True)
    points.sort(key=lambda point: (point["run"], point["checkpoint"]))
    payload = {
        "batch": batch.name, "created_at": datetime.now(timezone.utc).isoformat(),
        "statuses": dict(statuses), "completed": len(completed),
        "included": len(updated), "errors": failures, "points": points,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(updated, allow_nan=False), encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    output.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", data), encoding="utf-8")
    print(f"HTML: {output}\nRuns: {len(updated)}; points: {len(points)}; skipped: {len(failures)}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
