"""Packing stage orchestration and ports."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from ..configuration_values import mapping
from ..errors import ConfigurationError
from .configuration import PackingPlan, build_packing_plan, normalized_exports
from .domain import ParticlePacking
from .exporters.base import PackingExporter


class PackingStore(Protocol):
    filename: str

    def save(self, path, packing, configuration) -> None:
        """Persist a packing and its effective configuration."""

    def load(self, path):
        """Restore a packing and its effective configuration."""


class PackingGenerationService(Protocol):
    def generate(self, plan, observer=None) -> ParticlePacking:
        """Build a validated particle packing from an executable plan."""


@dataclass(frozen=True)
class PackingStageResult:
    packing: ParticlePacking
    filenames: tuple[str, ...]


@dataclass(frozen=True)
class PackingSourcePlan:
    packing: ParticlePacking
    configuration: dict
    path: Path
    sha256: str
    exports: tuple[str, ...]

    def to_config(self):
        return {"file": str(self.path), "sha256": self.sha256, "exports": list(self.exports)}


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

    def build_plan(self, raw) -> PackingPlan:
        return build_packing_plan(raw, self.exporters)

    def build_source_plan(self, raw):
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

    def import_source(self, plan, workspace):
        return self._publish(plan.packing, plan.configuration, plan.exports, workspace)

    def execute(self, plan, workspace, versions, observer=None) -> PackingStageResult:
        packing = self.generator.generate(plan, observer)
        packing = packing.with_metadata(packing.metadata.with_versions(versions))
        return self._publish(
            packing, {"packing": plan.to_packing_config()}, plan.exports, workspace
        )

    def _publish(self, packing, effective, export_formats, workspace):
        exporters = tuple(self.exporters[name] for name in export_formats)
        filenames = (self.store.filename, *(exporter.filename for exporter in exporters))
        with workspace.stage_outputs() as staging:
            self.store.save(staging / self.store.filename, packing, effective)
            restored, _ = self.store.load(staging / self.store.filename)
            for exporter in exporters:
                exporter.export(staging / exporter.filename, restored)
            workspace.publish(staging, filenames)
        return PackingStageResult(restored, filenames)
