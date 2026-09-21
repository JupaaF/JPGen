"""DEM stage orchestration."""

from dataclasses import dataclass

import numpy as np

from ..errors import DemExecutionError
from .configuration import build_dem_plan
from .persistence import DemResultStore


@dataclass(frozen=True)
class DemStageResult:
    summary: dict
    filenames: tuple[str, ...]


@dataclass(frozen=True)
class DemApplication:
    store: DemResultStore
    backends: dict

    def build_plan(self, raw):
        return build_dem_plan(raw, self.backends)

    def execute(self, plan, packing, workspace, observer=None):
        case = plan.create_case(packing)
        prepared = plan.backend.prepare(case, workspace.directory / "dem")
        report = plan.backend.run(prepared, observer)
        state = plan.backend.collect(prepared, report)
        with np.errstate(over="ignore", invalid="ignore"):
            mass = (4.0 * np.pi / 3.0) * state.radii**3 * case.material.density
            translation = 0.5 * mass * np.sum(state.velocities**2, axis=1)
            rotation = 0.2 * mass * state.radii**2 * np.sum(state.angular_velocities**2, axis=1)
            kinetic_energy = float(np.sum(translation + rotation))
        if not np.isfinite(kinetic_energy):
            raise DemExecutionError("DEM final kinetic energy is not finite.")
        destination = prepared.directory / self.store.filename
        temporary = destination.with_suffix(".h5.tmp")
        self.store.save(temporary, state, case, plan.to_config(), report)
        temporary.replace(destination)
        return DemStageResult({
            "status": "complete", "engine": plan.backend.name, "time": state.time,
            "steps": report.steps, "particle_count": len(state.ids),
            "kinetic_energy": kinetic_energy, "kinetic_energy_units": "J",
            "elapsed_seconds": report.elapsed_seconds, "versions": report.versions,
            "stop_reason": report.stop_reason, "return_code": report.return_code,
            "protocol_history": report.history, "observables": report.observables,
        }, ("dem/" + self.store.filename,))
