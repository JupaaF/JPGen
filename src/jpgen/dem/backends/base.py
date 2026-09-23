"""Common contract and execution records for DEM engine adapters."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ...errors import ConfigurationError
from ..domain import DemCase, DemState
from ..commands import ActuatorCommand


@dataclass(frozen=True)
class DemCapabilities:
    """Solver-independent features required by a portable JPGen protocol."""

    boundaries: frozenset[str]
    controls: frozenset[str]
    observables: frozenset[str]
    contact_models: frozenset[str] = frozenset()
    integration_schemes: frozenset[tuple[str, str]] = frozenset()
    actuator_commands: frozenset[str] = frozenset()
    native_controls: frozenset[str] = frozenset()
    particle_snapshots: bool = False
    native_restart_export: bool = False
    state_restore: bool = False
    contact_parameter_updates: bool = False
    contact_history_checkpoint: bool = False
    rollback: bool = False
    target_publication: bool = False

    def validate(self, plan) -> None:
        from ..protocol import control_types, required_actuator_commands, required_observables

        if plan.contact.model not in self.contact_models:
            raise ConfigurationError(f"Backend {plan.backend.name} does not support contact model {plan.contact.model}.")
        schemes = (plan.integration.translation, plan.integration.rotation)
        if schemes not in self.integration_schemes:
            raise ConfigurationError(f"Backend {plan.backend.name} does not support integration schemes {schemes}.")
        if plan.boundary not in self.boundaries:
            raise ConfigurationError(f"Backend {plan.backend.name} does not support {plan.boundary} boundaries.")
        if not plan.protocol:
            return
        if not self.particle_snapshots:
            raise ConfigurationError(f"Backend {plan.backend.name} cannot export protocol boundary snapshots.")
        controls = control_types(plan.protocol["stages"])
        if 'density_continuation' in controls:
            required = ('state_restore', 'contact_parameter_updates',
                        'contact_history_checkpoint', 'rollback',
                        'target_publication', 'native_restart_export')
            missing = [name for name in required if not getattr(self, name)]
            if missing:
                raise ConfigurationError(f"Backend {plan.backend.name} cannot run density_continuation: "
                                         f"missing {', '.join(missing)}.")
        unsupported_controls = controls - self.controls
        if unsupported_controls:
            raise ConfigurationError(f"Backend {plan.backend.name} does not support controls: "
                                     f"{', '.join(sorted(unsupported_controls))}.")
        unsupported_observables = required_observables(plan.protocol["stages"]) - self.observables - {"time", "stage_time"}
        if unsupported_observables:
            raise ConfigurationError(f"Backend {plan.backend.name} cannot measure: "
                                     f"{', '.join(sorted(unsupported_observables))}.")
        unsupported_commands = required_actuator_commands(plan.protocol["stages"]) - self.actuator_commands
        if unsupported_commands:
            raise ConfigurationError(f"Backend {plan.backend.name} cannot apply actuator commands: "
                                     f"{', '.join(sorted(unsupported_commands))}.")

    def to_config(self) -> dict:
        return {
            "contact_models": sorted(self.contact_models),
            "integration_schemes": [{"translation": t, "rotation": r} for t, r in sorted(self.integration_schemes)],
            "boundaries": sorted(self.boundaries),
            "controls": sorted(self.controls),
            "observables": sorted(self.observables),
            "actuator_commands": sorted(self.actuator_commands),
            "native_controls": sorted(self.native_controls),
            "particle_snapshots": self.particle_snapshots,
            "native_restart_export": self.native_restart_export,
            "state_restore": self.state_restore,
            "contact_parameter_updates": self.contact_parameter_updates,
            "contact_history_checkpoint": self.contact_history_checkpoint,
            "rollback": self.rollback,
            "target_publication": self.target_publication,
        }


class DemControlPort(Protocol):
    """Live solver operations consumed by the engine-independent protocol."""

    def control_context(self, dt: float) -> dict: ...

    def apply(self, command: ActuatorCommand, dt: float) -> None: ...

    def observe(self, observables: set[str]) -> dict: ...

    def box(self) -> dict: ...


class DemContinuationPort(Protocol):
    """Stateful paths require complete, equivalent solver restoration.

    A checkpoint includes integrator, contact history, cell, active material
    parameters and protocol-local state. Exporting a native restart alone does
    not satisfy this contract.
    """

    def checkpoint(self, stage: str, physical_step: int, time: float, observables: dict) -> object: ...

    def restore(self, checkpoint: object) -> None: ...

    def friction(self) -> tuple[float, float]: ...

    def set_friction(self, static: float, dynamic: float) -> None: ...

    def publish_target(self, checkpoint: object, metadata: dict) -> None: ...

    def log_attempt(self, record: dict) -> None: ...


@dataclass(frozen=True)
class PreparedDemCase:
    directory: Path
    case: DemCase


@dataclass(frozen=True)
class ExecutionReport:
    return_code: int
    elapsed_seconds: float
    versions: dict
    steps: int = 0
    stop_reason: str = "end_time"
    completed_stages: int = 0
    accepted_targets: int = 0
    attempted_duration: float = 0.0
    diagnostics: dict = field(default_factory=dict)
    failed_stage: str | None = None
    observables: dict = field(default_factory=dict)
    time: float | None = None
    time_step: dict = field(default_factory=dict)
    control: dict = field(default_factory=dict)


class DemBackend(Protocol):
    name: str
    capabilities: DemCapabilities

    def to_config(self) -> dict: ...

    def validate(self, plan) -> None:
        """Reject unsupported physics and unavailable runtimes before packing."""

    def prepare(self, case: DemCase, directory: Path) -> PreparedDemCase: ...

    def run(self, prepared: PreparedDemCase, observer=None) -> ExecutionReport: ...

    def collect(self, prepared: PreparedDemCase, report: ExecutionReport) -> DemState:
        """Translate native results, including final geometry and periodic wrapping.

        The application validates the report and state against the physical case.
        Particle ordering is unrestricted; IDs must retain their original meaning.
        """
