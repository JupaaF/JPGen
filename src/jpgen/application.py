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
from .configuration_values import mapping
from .dem.application import DemApplication
from .dem.backends import DEM_BACKENDS
from .dem.persistence import Hdf5DemResultStore
from .errors import ConfigurationError
from .packing.application import PackingApplication
from .packing.exporters import build_packing_exporters
from .packing.generator import PackingGenerator
from .packing.persistence import Hdf5PackingStore
from .progress import (
    DemCompleted,
    DemFailed,
    DemStarted,
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
    dem: DemApplication | None = None

    def run(self, raw, observer=None):
        """Execute the configured pipeline and publish one run."""

        mapping(raw, "pipeline", {"packing", "packing_source", "dem"})

        plan = self.packing.prepare(raw)
        seed = plan.seed
        effective = plan.to_pipeline_config()
        dem_plan = None
        if raw.get("dem") is not None:
            if self.dem is None:
                raise ConfigurationError("DEM stage is not configured in this application.")
            dem_plan = self.dem.build_plan(raw["dem"])
            dem_plan.validate_box(plan.box)
            dem_plan.backend.validate(dem_plan)
            effective["dem"] = dem_plan.to_config()
        versions = self.version_provider()
        status = {
            "status": "running",
            "versions": versions,
            "packing": {"status": "running", "seed": seed},
        }
        if dem_plan is not None:
            status["dem"] = {"status": "pending", "engine": dem_plan.backend.name}
        workspace = self.runs.create(effective, status)

        emit(observer, RunStarted(workspace.directory))
        emit(observer, PackingStarted(seed))
        active_stage = "packing"
        try:
            result = self.packing.execute(plan, workspace, versions, observer)
            packing = result.packing
            status["packing"] = result.summary
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
            if dem_plan is not None:
                active_stage = "dem"
                status["dem"]["status"] = "running"
                workspace.save_summary(status)
                emit(observer, DemStarted(dem_plan.backend.name))
                dem_result = self.dem.execute(dem_plan, packing, workspace, observer)
                status["dem"] = dem_result.summary
                workspace.save_summary(status)
                emit(observer, DemCompleted(workspace.directory, dem_result.summary["time"], dem_result.filenames))
            active_stage = None
            status["status"] = "complete"
            workspace.save_summary(status)
            emit(observer, RunCompleted(workspace.directory))
            return workspace.directory
        except (Exception, KeyboardInterrupt) as error:
            message = str(error) or "Run interrupted."
            status.update(status="failed", error=message)
            if active_stage is not None:
                status[active_stage].update(status="failed", error=message)
            if active_stage == "dem" and hasattr(error, "execution_report"):
                report = error.execution_report
                status["dem"].update(
                    accepted_targets=report.accepted_targets,
                    attempted_duration=report.attempted_duration,
                    diagnostics=report.diagnostics,
                    failed_stage=report.failed_stage,
                    stop_reason=report.stop_reason,
                )
                if report.accepted_targets:
                    status["dem"]["accepted_states_index"] = "dem/native_results/accepted_states.jsonl"
            if active_stage == "packing" and dem_plan is not None:
                status["dem"]["status"] = "skipped"
            workspace.save_summary(status)
            if active_stage == "packing":
                emit(observer, PackingFailed(workspace.directory, message))
            elif active_stage == "dem":
                emit(observer, DemFailed(workspace.directory, message))
            emit(observer, RunFailed(workspace.directory, message))
            raise


def build_application():
    """Compose the adapters used by the command-line application."""
    return JPGenApplication(
        packing=PackingApplication(
            generator=PackingGenerator(),
            store=Hdf5PackingStore(),
            exporters=build_packing_exporters(),
        ),
        runs=FileRunRepository(PROJECT_ROOT / "runs"),
        version_provider=runtime_versions,
        dem=DemApplication(store=Hdf5DemResultStore(), backends=DEM_BACKENDS),
    )
