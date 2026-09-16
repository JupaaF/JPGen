"""Application service and default dependency composition for one run."""

import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

import h5py
import numpy as np
import scipy
import yaml

from . import __version__
from .configuration import build_generation_plan
from .exporters.base import ParticleExporter
from .exporters.kratos import KratosExporter
from .exporters.vtk import VtkExporter
from .generation import ParticleGenerator
from .persistence import Hdf5ParticleStore
from .run_repository import FileRunRepository, RunRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ParticleStore(Protocol):
    filename: str

    def write(self, path, particles, configuration) -> None:
        """Persist a particle aggregate and its effective configuration."""

    def read(self, path):
        """Restore a particle aggregate and its effective configuration."""


class GenerationService(Protocol):
    def generate(self, plan, report=None):
        """Build a validated particle aggregate from an executable plan."""


def runtime_versions():
    return {
        "jpgen_particle_generation": __version__,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "h5py": h5py.__version__,
        "pyyaml": yaml.__version__,
    }


@dataclass(frozen=True)
class ParticleGenerationApplication:
    generator: GenerationService
    runs: RunRepository
    store: ParticleStore
    exporters: Sequence[ParticleExporter]
    version_provider: Callable[[], dict]

    def run(self, raw, report=print):
        """Execute and publish one run from a particle-generation mapping."""
        plan = build_generation_plan(raw)
        cfg = plan.config
        effective = {"particle_generation": plan.to_config()}
        versions = self.version_provider()
        status = {"status": "running", "seed": cfg["seed"], "versions": versions}
        workspace = self.runs.create(effective, status)

        report(f"Run directory: {workspace.directory}")
        report(f"Random seed: {cfg['seed']}")
        try:
            particles = self.generator.generate(plan, report)
            particles.metadata["versions"] = versions
            filenames = [self.store.filename, *(exporter.filename for exporter in self.exporters)]
            with workspace.stage_outputs() as staging:
                self.store.write(staging / self.store.filename, particles, effective)
                restored, _ = self.store.read(staging / self.store.filename)
                for exporter in self.exporters:
                    exporter.export(staging / exporter.filename, restored)
                workspace.publish(staging, filenames)
            status.update(particles.metadata)
            status.update(
                status="complete",
                box_origin=particles.box.origin.tolist(),
                box_lengths=particles.box.lengths.tolist(),
                periodic=particles.box.periodic,
            )
            workspace.save_summary(status)
            report(f"Generated {len(particles.ids)} particles; solid fraction: {particles.solid_fraction:.9g}")
            report(f"Saved {', '.join(filenames)} to {workspace.directory}")
            return workspace.directory
        except Exception as error:
            status.update(status="failed", error=str(error))
            workspace.save_summary(status)
            raise


def build_application():
    """Compose the adapters used by the command-line application."""
    return ParticleGenerationApplication(
        generator=ParticleGenerator(),
        runs=FileRunRepository(PROJECT_ROOT / "runs"),
        store=Hdf5ParticleStore(),
        exporters=(KratosExporter(), VtkExporter()),
        version_provider=runtime_versions,
    )
