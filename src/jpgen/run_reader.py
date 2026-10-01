"""Backend-independent queries and rebuildable browser projections for runs."""

import json
from pathlib import Path

import yaml

from .run_repository import FORMAT_VERSION, atomic_json, file_hash, json_safe, relative_path, utc_now


METRICS = {
    "time": {"unit": "s", "definition": "Physical simulation time on this branch"},
    "stage_time": {"unit": "s", "definition": "Physical time since leaf-stage entry"},
    "kinetic_energy": {"unit": "J", "definition": "Translational plus rotational kinetic energy"},
    "normalized_kinetic_energy": {"unit": "1", "definition": "Kinetic energy / (positive contact pressure * cell volume)"},
    "solid_fraction": {"unit": "1", "definition": "Sum of sphere volumes / cell volume; overlaps counted separately"},
    "bulk_density": {"unit": "kg/m^3", "definition": "Particle mass / cell volume"},
    "pressure": {"unit": "Pa", "definition": "Trace of contact stress / 3; compression positive; no kinetic contribution"},
    "unbalanced_force": {"unit": "1", "definition": "RMS particle force imbalance / RMS contact force; excludes moments; zero without contacts"},
    "mean_coordination_number": {"unit": "1", "definition": "Twice the number of contact elements / number of particles"},
    "fabric_tensor": {"unit": "1", "definition": "3x3 mean contact direction outer product; minimum-image branches in periodic cells"},
    "fabric_second_invariant": {"unit": "1", "definition": "sqrt(0.5 * (7.5 * (fabric - I/3)) : (7.5 * (fabric - I/3)))"},
    "thermal_conductivity": {"unit": "1", "definition": "3x3 DEMGen contact geometry tensor: sum(contact area * branch length * direction outer product) / periodic cell volume; not W/(m*K)"},
    "thermal_conductivity_trace": {"unit": "1", "definition": "Trace of the contact geometry tensor / 3"},
    **{f"stress_{axis}": {"unit": "Pa", "definition": "Contact-force stress; no kinetic contribution"}
       for axis in ("xx", "yy", "zz", "xy", "xz", "yz")},
}


def read_jsonl(path):
    """Only newline-terminated records are committed; tolerate a torn last append."""
    path = Path(path)
    if not path.exists():
        return
    with path.open("rb") as stream:
        for line in stream:
            if not line.endswith(b"\n"):
                break
            if line.strip():
                yield json.loads(line)


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _flatten(child, f"{prefix}.{key}" if prefix else key)
    elif isinstance(value, list):
        if not value:
            yield prefix, []
        for index, child in enumerate(value):
            yield from _flatten(child, f"{prefix}[{index}]")
    else:
        yield prefix, value


def _category(path):
    if ".exports" in path:
        return "exports"
    if ".backend_options" in path:
        return "execution"
    if path.startswith("dem.protocol"):
        return "protocol"
    return "physics" if path.startswith("dem.") else "packing"


class RunReader:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.manifest = json.loads((self.directory / "run.json").read_text(encoding="utf-8"))
        if (not isinstance(self.manifest, dict) or self.manifest.get("schema") != "JPGen.run" or
                self.manifest.get("schema_version") != FORMAT_VERSION):
            raise ValueError("Unsupported JPGen run format.")

    def _records(self, relative):
        for record in read_jsonl(self.directory / relative):
            if (not isinstance(record, dict) or record.get("schema") != "JPGen.dem.record"
                    or record.get("schema_version") != "1.0"):
                raise ValueError(f"Unsupported DEM index record in {relative}.")
            yield record

    def artifact(self, artifact_id):
        inventory = json.loads((self.directory / "artifacts.json").read_text(encoding="utf-8"))
        for item in inventory["artifacts"]:
            if item["artifact_id"] == artifact_id:
                return relative_path(self.directory, item["path"])
        raise KeyError(artifact_id)

    def verify(self):
        inventory = json.loads((self.directory / "artifacts.json").read_text(encoding="utf-8"))
        errors = []
        for item in inventory["artifacts"]:
            path = relative_path(self.directory, item["path"])
            if not path.is_file():
                errors.append({"path": item["path"], "error": "missing"})
            elif item.get("sha256") and file_hash(path) != item["sha256"]:
                errors.append({"path": item["path"], "error": "checksum_mismatch"})
        return {"run_id": self.manifest["run_id"], "artifacts_checked": len(inventory["artifacts"]), "errors": errors}

    def configuration(self):
        return yaml.safe_load(relative_path(self.directory, self.manifest["configuration"]).read_text(encoding="utf-8"))

    def compare(self, other):
        if not isinstance(other, RunReader):
            other = RunReader(other)
        left, right = dict(_flatten(self.configuration())), dict(_flatten(other.configuration()))
        return [{"field": key, "category": _category(key),
                 "left_present": key in left, "right_present": key in right,
                 "left": json_safe(left.get(key)), "right": json_safe(right.get(key))}
                for key in sorted(left.keys() | right.keys())
                if key not in left or key not in right or left[key] != right[key]]

    def states(self, *, accepted_only=False):
        result = []
        for record in self._records("stages/dem/results/states.jsonl"):
            if accepted_only and record.get("accepted") is not True:
                continue
            # Missing pairs are never presented as usable scientific states.
            stem = relative_path(self.directory, record["state"])
            if Path(str(stem) + ".json").is_file() and Path(str(stem) + ".npz").is_file():
                result.append(record)
        return result

    def load_state(self, state_id):
        from .dem.state_exchange import read_state
        for record in self.states():
            if record["state_id"] == state_id:
                path = relative_path(self.directory, record["state"])
                return read_state(path.parent, path.name)
        raise KeyError(state_id)

    def series(self, *, include_discarded=False):
        outcomes = {}
        for record in self._records("stages/dem/execution/attempts.jsonl"):
            key = (record.get("stage"), record.get("attempt_id"))
            if record.get("event") in {"accepted", "discarded", "accepted_target"}:
                outcomes[key] = "accepted" if record["event"] == "accepted_target" else record["event"]
        for record in self._records("stages/dem/results/observables.jsonl"):
            attempt = record.get("attempt_id")
            disposition = outcomes.get((record.get("stage"), attempt), "pending") if attempt is not None else "accepted"
            if record.get("legacy_branch_unknown"):
                disposition = "unknown"
            if include_discarded or disposition == "accepted":
                yield dict(record, disposition=disposition)

    def export_view(self, max_points=2000):
        """Bounded previews; full precision scientific arrays remain in their stores."""
        if max_points < 2:
            raise ValueError("max_points must be at least 2.")
        self.manifest = RunReader(self.directory).manifest
        root = self.directory / "view"
        summaries = {}
        for name, stage in self.manifest["stages"].items():
            summaries[name] = json.loads(relative_path(self.directory, stage["summary"]).read_text())
        atomic_json(root / "summary.json", {
            "schema": "JPGen.view", "schema_version": FORMAT_VERSION,
            "generated_at": utc_now(), "run_id": self.manifest["run_id"],
            "source": "run.json", "source_sha256": file_hash(self.directory / "run.json"),
            "manifest": self.manifest, "summaries": summaries, "metrics": METRICS,
        })
        states_source = self.directory / "stages/dem/results/states.jsonl"
        atomic_json(root / "states.json", {
            "schema": "JPGen.states_view", "schema_version": FORMAT_VERSION,
            "source": "stages/dem/results/states.jsonl",
            "source_sha256": file_hash(states_source) if states_source.exists() else None,
            "states": self.states(),
        })
        # Two streaming passes avoid loading an unbounded time series into memory.
        count = sum(1 for _ in self.series())
        stride = max(1, (max(0, count - 1) + max_points - 2) // (max_points - 1))
        selected = []
        for index, record in enumerate(self.series()):
            if index % stride == 0 or index == count - 1:
                selected.append(record)
        series_source = self.directory / "stages/dem/results/observables.jsonl"
        atomic_json(root / "series/observables.json", {
            "schema": "JPGen.series_view", "schema_version": FORMAT_VERSION,
            "source": "stages/dem/results/observables.jsonl",
            "source_sha256": file_hash(series_source) if series_source.exists() else None,
            "sampling": "uniform_stride", "stride": stride, "source_count": count,
            "includes_discarded": False, "records": json_safe(selected),
        })
        packing = self.directory / "stages/packing/results/packing.h5"
        if packing.exists():
            import h5py
            with h5py.File(packing, "r") as file:
                particles = file["particles"]
                count = len(particles["ids"])
                stride = max(1, (count + max_points - 1) // max_points)
                data = {key: particles[key][::stride].tolist() for key in ("ids", "positions", "radii")}
            atomic_json(root / "previews/packing.json", {
                "schema": "JPGen.packing_view", "schema_version": FORMAT_VERSION,
                "source": "stages/packing/results/packing.h5", "source_sha256": file_hash(packing), "sampled": stride > 1,
                "particle_count": count, "stride": stride, "particles": json_safe(data),
            })
        return root
