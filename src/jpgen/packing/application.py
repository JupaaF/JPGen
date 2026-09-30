"""Packing stage orchestration."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from ..configuration_values import mapping
from ..errors import ConfigurationError
from ..run_repository import file_hash
from .configuration import (
    PackingPlan,
    PackingSourcePlan,
    build_packing_plan,
    normalized_exports,
)
from .domain import ParticlePacking
from .exporters.base import PackingExporter
from .generator import PackingGenerationService
from .persistence import PackingStore


@dataclass(frozen=True)
class PackingStageResult:
    packing: ParticlePacking
    filenames: tuple[str, ...]
    summary: dict


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class PackingApplication:
    generator: PackingGenerationService
    store: PackingStore
    exporters: Mapping[str, PackingExporter]

    def prepare(self, raw) -> PackingPlan | PackingSourcePlan:
        """Select and validate the packing input before a run is created."""
        if ("packing" in raw) == ("packing_source" in raw):
            raise ConfigurationError("Provide exactly one of packing or packing_source.")
        if "packing_source" in raw:
            return self.build_source_plan(raw["packing_source"])
        return self.build_plan(raw["packing"])

    def build_plan(self, raw) -> PackingPlan:
        return build_packing_plan(raw, self.exporters)

    def build_source_plan(self, raw) -> PackingSourcePlan:
        mapping(raw, "packing_source", {"file", "sha256", "exports"}, {"file"})
        if not isinstance(raw["file"], str) or not raw["file"].strip():
            raise ConfigurationError("packing_source.file must be a path to packing.h5.")
        path = Path(raw["file"]).expanduser().resolve()
        digest = _sha256(path)
        if "sha256" in raw and raw["sha256"] != digest:
            raise ConfigurationError("packing_source SHA-256 does not match its recorded content.")
        packing, configuration = self.store.load(path)
        if _sha256(path) != digest:
            raise ConfigurationError("packing_source changed while it was being loaded.")
        exports = normalized_exports(raw.get("exports", []), self.exporters)
        return PackingSourcePlan(packing, configuration, path, digest, exports)

    def execute(
        self, plan: PackingPlan | PackingSourcePlan, workspace, versions, observer=None
    ) -> PackingStageResult:
        if isinstance(plan, PackingSourcePlan):
            packing = plan.packing
            effective = plan.configuration
        else:
            packing = self.generator.generate(plan, observer)
            packing = packing.with_metadata(packing.metadata.with_versions(versions))
            effective = {"packing": plan.to_packing_config()}
        restored, filenames = self._publish(packing, effective, plan.exports, workspace)
        summary = restored.metadata.to_dict()
        summary.update(
            status="completed",
            box_origin=restored.box.origin.tolist(),
            box_lengths=restored.box.lengths.tolist(),
            periodic=restored.box.periodic,
        )
        if isinstance(plan, PackingSourcePlan):
            summary["source"] = {"sha256": plan.sha256, "provenance": "provenance/sources.json"}
            effective_pipeline = plan.to_pipeline_config()
            snapshot = workspace.directory / "stages/packing/results/packing.h5"
            effective_pipeline["packing_source"].update(file="../stages/packing/results/packing.h5", sha256=file_hash(snapshot))
            current = yaml.safe_load((workspace.directory / "config/effective.yaml").read_text())
            current["packing_source"] = effective_pipeline["packing_source"]
            workspace.save_configuration(current)
        return PackingStageResult(restored, filenames, summary)

    def _publish(self, packing, effective, export_formats, workspace):
        exporters = tuple(self.exporters[name] for name in export_formats)
        filenames = (self.store.filename, *(exporter.filename for exporter in exporters))
        files = {
            name: (f"stages/packing/{'results' if name == self.store.filename else 'exports'}/{name}",
                   "packing" if name == self.store.filename else "export") for name in filenames
        }
        with workspace.stage_outputs() as staging:
            self.store.save(staging / self.store.filename, packing, effective)
            restored, _ = self.store.load(staging / self.store.filename)
            for exporter in exporters:
                exporter.export(staging / exporter.filename, restored)
            workspace.publish(staging, files)
        return restored, tuple(relative for relative, _ in files.values())
