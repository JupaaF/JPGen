"""Common contract and execution records for DEM engine adapters."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..domain import DemCase, DemState


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
    history: list = field(default_factory=list)
    observables: dict = field(default_factory=dict)


class DemBackend(Protocol):
    name: str

    def to_config(self) -> dict: ...

    def validate(self, plan) -> None:
        """Reject unsupported physics and unavailable runtimes before packing."""

    def prepare(self, case: DemCase, directory: Path) -> PreparedDemCase: ...

    def run(self, prepared: PreparedDemCase, observer=None) -> ExecutionReport: ...

    def collect(self, prepared: PreparedDemCase, report: ExecutionReport) -> DemState: ...
