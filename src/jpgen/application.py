"""JPGen pipeline orchestration and default dependency composition."""

import platform
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import scipy
import yaml

from . import __version__
from .errors import ConfigurationError
from .packing.application import PackingApplication
from .packing.exporters.kratos import KratosExporter
from .packing.exporters.vtk import VtkExporter
from .packing.generator import PackingGenerator
from .packing.persistence import Hdf5PackingStore
from .progress import (
    ConsoleProgressObserver,
    PackingCompleted,
    PackingFailed,
    PackingStarted,
    RunCompleted,
    RunFailed,
    RunStarted,
    emit,
)
from .run_repository import FileRunRepository, RunRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def runtime_versions():
    return {
        "jpgen": __version__,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "h5py": h5py.__version__,
        "pyyaml": yaml.__version__,
    }


@dataclass(frozen=True)
class JPGenApplication:
    packing: PackingApplication
    runs: RunRepository
    version_provider: Callable[[], dict]

    def run(self, raw, observer=None):
        """Execute the configured pipeline and publish one run."""
        if observer is None:
            observer = ConsoleProgressObserver()
        if "packing" not in raw:
            raise ConfigurationError("Missing required configuration section: packing.")
        plan = self.packing.build_plan(raw["packing"])
        cfg = plan.config
        effective = {"packing": plan.to_config()}
        versions = self.version_provider()
        status = {
            "status": "running",
            "versions": versions,
            "packing": {"status": "running", "seed": cfg["seed"]},
        }
        workspace = self.runs.create(effective, status)

        emit(observer, RunStarted(workspace.directory))
        emit(observer, PackingStarted(cfg["seed"]))
        try:
            result = self.packing.execute(plan, workspace, versions, observer)
            packing = result.packing
            packing_status = packing.metadata.to_dict()
            packing_status.update(
                status="complete",
                box_origin=packing.box.origin.tolist(),
                box_lengths=packing.box.lengths.tolist(),
                periodic=packing.box.periodic,
            )
            status.update(status="complete", packing=packing_status)
            workspace.save_summary(status)
            emit(
                observer,
                PackingCompleted(
                    directory=workspace.directory,
                    particle_count=len(packing.ids),
                    solid_fraction=packing.solid_fraction,
                    filenames=result.filenames,
                ),
            )
            emit(observer, RunCompleted(workspace.directory))
            return workspace.directory
        except Exception as error:
            status.update(status="failed", error=str(error))
            status["packing"].update(status="failed", error=str(error))
            workspace.save_summary(status)
            emit(observer, PackingFailed(workspace.directory, str(error)))
            emit(observer, RunFailed(workspace.directory, str(error)))
            raise


def build_application():
    """Compose the adapters used by the command-line application."""
    return JPGenApplication(
        packing=PackingApplication(
            generator=PackingGenerator(),
            store=Hdf5PackingStore(),
            exporters=(KratosExporter(), VtkExporter()),
        ),
        runs=FileRunRepository(PROJECT_ROOT / "runs"),
        version_provider=runtime_versions,
    )
