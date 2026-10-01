"""Versioned, portable run workspaces and atomic artifact publication."""

import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import yaml


FORMAT_VERSION = "1.0"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, indent=2, allow_nan=False) + "\n")


def atomic_text(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(value)
            stream.flush()
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def relative_path(root, relative):
    """Resolve a portable artifact reference without allowing directory escape."""
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Expected a run-relative path: {relative}")
    result = (Path(root) / relative).resolve()
    if not result.is_relative_to(Path(root).resolve()):
        raise ValueError("Artifact path escapes the run.")
    return result


@dataclass(frozen=True)
class RunWorkspace:
    directory: Path

    def read_manifest(self):
        return json.loads((self.directory / "run.json").read_text(encoding="utf-8"))

    def save_configuration(self, configuration, name="effective"):
        atomic_text(self.directory / "config" / f"{name}.yaml",
                    yaml.safe_dump(configuration, sort_keys=False))

    def record_event(self, event):
        record = {"timestamp": utc_now(), "event": type(event).__name__,
                  "data": asdict(event)}
        # Seeds and particle IDs can exceed JavaScript's exact integer range.
        record = json_safe(record)
        line = json.dumps(record, default=str, allow_nan=False)
        with (self.directory / "logs/events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
        with (self.directory / "logs/jpgen.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{record['timestamp']} {record['event']} {line}\n")

    def save_summary(self, summary):
        manifest = self.read_manifest()
        now = utc_now()
        manifest.update(status=summary["status"], updated_at=now)
        if summary["status"] in TERMINAL:
            manifest["finished_at"] = now
        if "error" in summary:
            manifest["error"] = summary["error"]
        for stage in ("packing", "dem"):
            if stage not in summary:
                continue
            item = summary[stage]
            reference = f"stages/{stage}/summary.json"
            atomic_json(self.directory / reference, json_safe(item))
            previous = manifest["stages"].get(stage, {})
            entry = {**previous, "status": item["status"], "summary": reference}
            if item["status"] == "running":
                entry.setdefault("started_at", now)
            if item["status"] in TERMINAL | {"skipped"}:
                entry.setdefault("finished_at", now)
            manifest["stages"][stage] = entry
        atomic_json(self.directory / "run.json", manifest)

    @contextmanager
    def stage_outputs(self):
        with tempfile.TemporaryDirectory(prefix=".output-", dir=self.directory) as staging:
            yield Path(staging)

    def publish(self, staging, files):
        """Commit validated files, then atomically publish their inventory entries.

        ``files`` maps staging names to (run-relative destination, role).
        The inventory is the commit marker; unlisted files are not published.
        """
        destinations = [value[0] for value in files.values()]
        if len(set(destinations)) != len(destinations):
            raise ValueError("Duplicate output destination.")
        for name, (relative, _) in files.items():
            if not relative_path(staging, name).is_file():
                raise FileNotFoundError(name)
            if relative_path(self.directory, relative).exists():
                raise FileExistsError(relative)
        moved = []
        try:
            for name, (relative, role) in files.items():
                destination = relative_path(self.directory, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                (staging / name).replace(destination)
                moved.append((name, relative))
            self.register([(relative, role, "validated") for relative, role in files.values()])
        except BaseException:
            for name, relative in reversed(moved):
                (self.directory / relative).replace(staging / name)
            raise

    def register(self, entries, *, closed=True):
        path = self.directory / "artifacts.json"
        inventory = json.loads(path.read_text(encoding="utf-8"))
        indexed = {item["path"]: item for item in inventory["artifacts"]}
        run_id = uuid.UUID(self.read_manifest()["run_id"])
        for relative, role, validation in entries:
            artifact = relative_path(self.directory, relative)
            indexed[relative] = {
                "artifact_id": uuid.uuid5(run_id, relative).hex,
                "path": relative, "role": role, "format": artifact.suffix.lstrip("."),
                "size_bytes": artifact.stat().st_size,
                "sha256": file_hash(artifact) if closed else None,
                "availability": "complete" if closed else "streaming",
                "validation": validation,
                **artifact_schema(artifact, relative, role),
            }
        inventory["artifacts"] = list(indexed.values())
        inventory["updated_at"] = utc_now()
        atomic_json(path, inventory)

    def finalize(self):
        """Inventory closed diagnostics, preserving stronger publication validation."""
        manifest = self.read_manifest()
        if manifest["retention"] == "analysis" and manifest["status"] in TERMINAL:
            for checkpoints in (self.directory / "stages/dem/backend").glob("*/checkpoints"):
                shutil.rmtree(checkpoints)
        inventory = json.loads((self.directory / "artifacts.json").read_text())
        known = {item["path"]: item for item in inventory["artifacts"]}
        entries = []
        for path in sorted(self.directory.rglob("*")):
            relative = path.relative_to(self.directory).as_posix()
            if (not path.is_file() or path.is_symlink() or any(part.startswith(".") or part.endswith(".tmp") for part in path.relative_to(self.directory).parts)
                    or path.suffix == ".tmp" or relative in {"run.json", "artifacts.json"}
                    or relative.startswith("view/")):
                continue
            prior = known.get(relative)
            role = prior["role"] if prior else artifact_role(relative)
            validation = prior["validation"] if prior else "not_validated"
            entries.append((relative, role, validation))
        self.register(entries)
        # Availability comes from actual committed state indices, even after failure.
        from .run_reader import RunReader
        reader = RunReader(self.directory)
        states = reader.states()
        manifest["results"] = {
            "packing": any(role == "packing" for _, role, _ in entries),
            "dem_final": any(role == "dem_final" for _, role, _ in entries),
            "saved_states": len({state["state_id"] for state in states}),
            "accepted_targets": sum(state.get("accepted") is True and "target" in state for state in states),
            "observables": (self.directory / "stages/dem/results/observables.jsonl").is_file(),
        }
        manifest["updated_at"] = utc_now()
        atomic_json(self.directory / "run.json", manifest)
        try:
            RunReader(self.directory).export_view()
        except (OSError, ValueError, KeyError) as error:
            # Derived previews may be regenerated without changing execution status.
            manifest["view_error"] = str(error)
            atomic_json(self.directory / "run.json", manifest)
        # A catalog is a cache, never a reason to invalidate scientific results.
        try:
            rebuild_catalog(self.directory.parent)
        except OSError:
            pass


def json_safe(value):
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
        return str(value)
    return value


def artifact_schema(path, relative, role):
    if role in {"packing", "dem_final"}:
        import h5py
        with h5py.File(path, "r") as file:
            return {key: str(file.attrs[key]) for key in ("schema", "schema_version")}
    schemas = {
        "packing": ("JPGen.packing", "4.0"), "dem_final": ("JPGen.dem", "1.1"),
        "particle_state": ("JPGen.dem.state", "1.0"),
    }
    if relative.endswith(".target.json"):
        return {"schema": "JPGen.dem.target", "schema_version": "1.0"}
    if role in schemas:
        schema, version = schemas[role]
        return {"schema": schema, "schema_version": version}
    if relative.startswith("stages/dem/") and relative.endswith(".jsonl"):
        return {"schema": "JPGen.dem.record", "schema_version": "1.0"}
    return {}


def artifact_role(relative):
    if relative.startswith("config/"):
        return "configuration"
    if relative.startswith("provenance/"):
        return "provenance"
    if "/logs/" in relative or relative.startswith("logs/"):
        return "log"
    if "/backend/" in relative:
        return "checkpoint" if "/checkpoints/" in relative else "backend"
    if "/execution/" in relative:
        return "execution"
    if relative.endswith("summary.json"):
        return "summary"
    if relative.endswith(".target.json"):
        return "target_metadata"
    if "/states/" in relative:
        return "particle_state"
    if relative.endswith("observables.jsonl"):
        return "observables"
    return "index" if relative.endswith(".jsonl") else "diagnostic"


class RunRepository(Protocol):
    def create(self, configuration, initial_summary, *, requested=None, metadata=None) -> RunWorkspace: ...


@dataclass(frozen=True)
class FileRunRepository:
    root: Path

    def create(self, configuration, initial_summary, *, requested=None, metadata=None):
        metadata = metadata or {}
        if "dem" in configuration:
            dem = configuration["dem"]
            default_label = f"{dem['engine']}-{'protocol' if dem.get('protocol') else 'dem'}"
        else:
            method = configuration.get("packing", {}).get("placement", {}).get("method", "imported")
            default_label = f"packing-{method}"
        label = metadata.get("label") or default_label
        slug = re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-_")[:60] or "run"
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%SZ")
        while True:
            run_id = uuid.uuid4()
            directory = self.root / f"{stamp}__{slug}__{run_id.hex[:8]}"
            try:
                directory.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                continue
        (directory / "logs").mkdir()
        workspace = RunWorkspace(directory)
        now = utc_now()
        atomic_json(directory / "run.json", {
            "schema": "JPGen.run", "schema_version": FORMAT_VERSION,
            "run_id": str(run_id), "label": label, "tags": metadata.get("tags", []),
            "experiment_id": metadata.get("experiment_id"),
            "created_at": now, "started_at": now, "updated_at": now, "finished_at": None,
            "status": "running", "stages": {}, "results": {},
            "configuration": "config/effective.yaml", "artifacts": "artifacts.json",
            "provenance": "provenance/sources.json", "retention": metadata.get("retention", "full"),
        })
        atomic_json(directory / "artifacts.json", {
            "schema": "JPGen.artifacts", "schema_version": FORMAT_VERSION, "artifacts": []})
        workspace.save_configuration(configuration)
        workspace.save_configuration(requested if requested is not None else configuration, "requested")
        from .packing.placement._backend import name as placement_backend
        atomic_json(directory / "provenance/environment.json", {
            "versions": initial_summary.get("versions", {}), "platform": platform.platform(),
            "machine": platform.machine(), "placement_backend": placement_backend,
            "placement_backend_requested": os.environ.get("JPGEN_PLACEMENT_BACKEND", "auto"),
        })
        atomic_json(directory / "provenance/sources.json", {"sources": []})
        workspace.save_summary(initial_summary)
        try:
            rebuild_catalog(self.root)
        except OSError:
            pass
        return workspace


def rebuild_catalog(root):
    """Reconstruct the browser index; concurrent writers never share temp files."""
    root = Path(root)
    runs, errors = [], []
    for path in sorted(root.glob("*/run.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or manifest.get("schema") != "JPGen.run" or manifest.get("schema_version") != FORMAT_VERSION:
                raise ValueError("Unsupported run format")
            runs.append({key: manifest.get(key) for key in (
                "run_id", "label", "tags", "experiment_id", "status", "created_at", "updated_at", "results")}
                | {"path": path.parent.name, "manifest": f"{path.parent.name}/run.json"})
        except (OSError, ValueError) as error:
            errors.append({"path": path.parent.name, "error": str(error)})
    catalog = {"schema": "JPGen.catalog", "schema_version": FORMAT_VERSION,
               "generated_at": utc_now(), "runs": runs, "errors": errors}
    atomic_json(root / "catalog.json", catalog)
    return catalog
