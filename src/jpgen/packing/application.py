"""Packing stage orchestration and ports."""

from dataclasses import dataclass
from typing import Protocol, Sequence

from .configuration import PackingPlan, build_packing_plan
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
class PackingApplication:
    generator: PackingGenerationService
    store: PackingStore
    exporters: Sequence[PackingExporter]

    def build_plan(self, raw) -> PackingPlan:
        return build_packing_plan(raw)

    def execute(self, plan, workspace, versions, observer=None) -> PackingStageResult:
        packing = self.generator.generate(plan, observer)
        packing = packing.with_metadata(packing.metadata.with_versions(versions))
        filenames = (self.store.filename, *(exporter.filename for exporter in self.exporters))
        effective = {"packing": plan.to_config()}
        with workspace.stage_outputs() as staging:
            self.store.save(staging / self.store.filename, packing, effective)
            restored, _ = self.store.load(staging / self.store.filename)
            for exporter in self.exporters:
                exporter.export(staging / exporter.filename, restored)
            workspace.publish(staging, filenames)
        return PackingStageResult(packing, filenames)
