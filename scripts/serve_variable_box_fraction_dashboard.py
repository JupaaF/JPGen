#!/usr/bin/env python3
"""Serve the live fixed-count variable-box dashboard and JPGen run summaries locally."""

import argparse
import json
import math
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

from jpgen.run_reader import RunReader


ROOT = Path(__file__).resolve().parents[1]
BATCHES = ROOT / "runs" / "variable_box_fraction_characterization"
CONFIG_DIR = ROOT / "examples" / "characterization" / "variable_box_fraction"
PAGE = CONFIG_DIR / "dashboard.html"
VOLUME_FRACTIONS = tuple(sorted(float(yaml.safe_load(path.read_text(encoding="utf-8"))["packing"]["target_solid_fraction"])
                               for path in CONFIG_DIR.glob("fraction_*.yaml")))
REPETITIONS = 10
JOB_PATTERN = re.compile(r"fraction_0_(\d{2})_rep_(\d{2})$")
summary_cache = {}
series_cache = {}
protocol_cache = {}
group_cache = {}


def batch_names():
    return sorted((p.name for p in BATCHES.iterdir() if p.is_dir()), reverse=True) if BATCHES.exists() else []


def selected_batch(query):
    names = batch_names()
    name = query.get("batch", [names[0] if names else ""])[0]
    if name not in names:
        raise ValueError("Batch not found")
    return BATCHES / name


def flatten_numbers(value, prefix=""):
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            result.update(flatten_numbers(child, f"{prefix}_{key}" if prefix else key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.update(flatten_numbers(child, f"{prefix}_{index}"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        result[prefix] = value
    return result


def observable_values(observables):
    values = flatten_numbers(observables)
    diagonal = [values.get(f"fabric_tensor_{index}_{index}") for index in range(3)]
    if all(value is not None and math.isfinite(value) for value in diagonal):
        values["fabric_trace"] = sum(diagonal)
    return values


def records_for(run_dir):
    source = run_dir / "stages" / "dem" / "results" / "observables.jsonl"
    if not source.is_file():
        return []
    signature = (source.stat().st_size, source.stat().st_mtime_ns)
    key = str(run_dir)
    cached = series_cache.get(key)
    if cached and cached[0] == signature:
        return cached[1]
    records = []
    for record in RunReader(run_dir).series():
        obs = observable_values(record.get("observables", {}))
        records.append({"time": obs.get("time"), "stage": record.get("stage"),
                        "step": record.get("step"), "values": obs})
    series_cache[key] = (signature, records)
    if len(series_cache) > 8:
        series_cache.pop(next(iter(series_cache)))
    return records


def protocol_for(run_dir):
    config = run_dir / "config" / "effective.yaml"
    if not config.is_file():
        return None
    signature = config.stat().st_mtime_ns
    cached = protocol_cache.get(str(config))
    if cached and cached[0] == signature:
        return cached[1]
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    stages = data.get("dem", {}).get("protocol", {}).get("stages", [])
    variant = "with_relaxation" if any(s.get("name") == "relaxation" for s in stages) else "without_relaxation"
    protocol_cache[str(config)] = (signature, variant)
    return variant


def job_run_dir(job_dir):
    return next(job_dir.glob("*/run.json"), None)


def summary(batch):
    jobs = []
    metrics = set()
    for job_dir in sorted(batch.iterdir()):
        match = JOB_PATTERN.fullmatch(job_dir.name) if job_dir.is_dir() else None
        if not match:
            continue
        item = {"job": job_dir.name, "fraction": int(match[1]) / 100, "repetition": int(match[2]),
                "status": "pending", "values": {}}
        manifest_path = job_run_dir(job_dir)
        if manifest_path:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                item["status"] = manifest.get("status", "running")
                item["run_id"] = manifest.get("run_id")
                item["protocol"] = protocol_for(manifest_path.parent)
                if item["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                    cache_key = str(manifest_path)
                    signature = manifest_path.stat().st_mtime_ns
                    cached = summary_cache.get(cache_key)
                    if cached and cached[0] == signature:
                        item["values"] = cached[1]
                    else:
                        last = None
                        for record in RunReader(manifest_path.parent).series():
                            last = record
                        item["values"] = observable_values(last.get("observables", {})) if last else {}
                        summary_cache[cache_key] = (signature, item["values"])
                    if item["status"] == "completed":
                        metrics.update(item["values"])
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                item["status"] = "reading"
        jobs.append(item)
    fractions = sorted(set(VOLUME_FRACTIONS) | {job["fraction"] for job in jobs})
    return {"batch": batch.name, "jobs": jobs, "metrics": sorted(metrics),
            "fractions": fractions, "repetitions": REPETITIONS, "expected": len(fractions) * REPETITIONS}


def series(batch, query):
    job = query.get("job", [""])[0]
    if not JOB_PATTERN.fullmatch(job):
        raise ValueError("Invalid job")
    job_dir = batch / job
    if not job_dir.is_dir():
        raise ValueError("Job not found")
    manifest = job_run_dir(job_dir)
    if manifest is None:
        return {"job": job, "records": [], "total": 0}
    records = records_for(manifest.parent)
    stride = max(1, (len(records) + 1199) // 1200)
    selected = records[::stride]
    if records and selected[-1] is not records[-1]:
        selected.append(records[-1])
    return {"job": job, "records": selected, "total": len(records), "stride": stride}


def group_series(batch, query):
    try:
        fraction = float(query.get("fraction", [""])[0])
    except ValueError as error:
        raise ValueError("Invalid volume fraction") from error
    if not math.isfinite(fraction) or not 0 <= fraction < 1 or fraction != round(fraction, 2):
        raise ValueError("Invalid volume fraction")
    job_prefix = f"fraction_{fraction:.2f}".replace(".", "_")
    protocol = query.get("protocol", [""])[0]
    metric = query.get("metric", [""])[0]
    if (fraction not in VOLUME_FRACTIONS and not any(batch.glob(f"{job_prefix}_rep_*"))) or protocol not in {"with_relaxation", "without_relaxation"} or not re.fullmatch(r"[a-z][a-z0-9_]*", metric):
        raise ValueError("Invalid group selection")

    runs = []
    for job_dir in sorted(batch.glob(f"{job_prefix}_rep_*")):
        manifest_path = job_run_dir(job_dir)
        if manifest_path is None:
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "completed" or protocol_for(manifest_path.parent) != protocol:
            continue
        source = manifest_path.parent / "stages" / "dem" / "results" / "observables.jsonl"
        if source.is_file():
            runs.append((job_dir.name, manifest_path.parent, source.stat().st_size, source.stat().st_mtime_ns))

    key = (batch.name, fraction, protocol, metric)
    signature = tuple((name, size, mtime) for name, _, size, mtime in runs)
    cached = group_cache.get(key)
    if cached and cached[0] == signature:
        return cached[1]

    stages = {}
    for _, run_dir, _, _ in runs:
        positions = {}
        for record in RunReader(run_dir).series():
            stage = str(record.get("stage") or "unknown").split(":", 1)[-1]
            observables = record.get("observables", {})
            value = observable_values(observables).get(metric)
            pressure = observables.get("pressure")
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                continue
            index = positions.get(stage, 0)
            positions[stage] = index + 1
            points = stages.setdefault(stage, [])
            if index == len(points):
                points.append({"n": 0, "mean": 0.0, "m2": 0.0, "pressure_n": 0, "pressure_mean": 0.0})
            point = points[index]
            point["n"] += 1
            delta = value - point["mean"]
            point["mean"] += delta / point["n"]
            point["m2"] += delta * (value - point["mean"])
            if isinstance(pressure, (int, float)) and math.isfinite(pressure):
                point["pressure_n"] += 1
                point["pressure_mean"] += (pressure - point["pressure_mean"]) / point["pressure_n"]

    result_stages = {}
    for stage, points in stages.items():
        stride = max(1, (len(points) + 1199) // 1200)
        indices = list(range(0, len(points), stride))
        if points and indices[-1] != len(points) - 1:
            indices.append(len(points) - 1)
        result_stages[stage] = {"total": len(points), "stride": stride, "points": [
            {"sample": index + 1, "n": points[index]["n"],
             "mean": points[index]["mean"],
             "pressure": points[index]["pressure_mean"] if points[index]["pressure_n"] == points[index]["n"] else None,
             "std": math.sqrt(points[index]["m2"] / (points[index]["n"] - 1)) if points[index]["n"] > 1 else None}
            for index in indices]}
    result = {"fraction": fraction, "protocol": protocol, "metric": metric,
              "runs": len(runs), "stages": result_stages}
    group_cache[key] = (signature, result)
    if len(group_cache) > 8:
        group_cache.pop(next(iter(group_cache)))
    return result


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = urlsplit(self.path)
        query = parse_qs(route.query)
        try:
            if route.path in ("/", "/dashboard.html"):
                body = PAGE.read_bytes()
                content_type = "text/html; charset=utf-8"
            elif route.path == "/api/batches":
                body = json.dumps({"batches": batch_names()}).encode()
                content_type = "application/json"
            elif route.path == "/api/summary":
                body = json.dumps(summary(selected_batch(query))).encode()
                content_type = "application/json"
            elif route.path == "/api/series":
                body = json.dumps(series(selected_batch(query), query)).encode()
                content_type = "application/json"
            elif route.path == "/api/group-series":
                body = json.dumps(group_series(selected_batch(query), query)).encode()
                content_type = "application/json"
            else:
                self.send_error(404)
                return
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            self.send_error(400, str(error))
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Open http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
