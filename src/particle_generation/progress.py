"""Structured progress events and the command-line presentation adapter."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ProgressEvent:
    """Marker base for observable application and algorithm events."""


@dataclass(frozen=True)
class RunStarted(ProgressEvent):
    directory: Path
    seed: int


@dataclass(frozen=True)
class GenerationAttemptStarted(ProgressEvent):
    attempt: int
    total: int


@dataclass(frozen=True)
class ExpectedParticleCount(ProgressEvent):
    count: int


@dataclass(frozen=True)
class GenerationAttemptFailed(ProgressEvent):
    attempt: int
    error: str


@dataclass(frozen=True)
class RelaxationProgress(ProgressEvent):
    iteration: int
    max_overlap_excess: float


@dataclass(frozen=True)
class GrowthStageStarted(ProgressEvent):
    stage: int
    radius_scale: float


@dataclass(frozen=True)
class GrowthStageRejected(ProgressEvent):
    restored_scale: float
    next_increment: float


@dataclass(frozen=True)
class RunCompleted(ProgressEvent):
    directory: Path
    particle_count: int
    solid_fraction: float
    filenames: tuple[str, ...]


@dataclass(frozen=True)
class RunFailed(ProgressEvent):
    directory: Path
    error: str


class ProgressObserver(Protocol):
    def __call__(self, event: ProgressEvent) -> None:
        """Handle one structured progress event."""


def emit(observer, event):
    if observer is not None:
        observer(event)


class ConsoleProgressObserver:
    def __call__(self, event):
        if isinstance(event, RunStarted):
            print(f"Run directory: {event.directory}")
            print(f"Random seed: {event.seed}")
        elif isinstance(event, GenerationAttemptStarted):
            print(f"Generation attempt {event.attempt}/{event.total}")
        elif isinstance(event, ExpectedParticleCount):
            print(f"Expected particle count: {event.count}")
        elif isinstance(event, GenerationAttemptFailed):
            print(f"Attempt failed: {event.error}")
        elif isinstance(event, RelaxationProgress):
            print(
                f"Relaxation iteration {event.iteration}: "
                f"maximum overlap excess {event.max_overlap_excess:.6g}"
            )
        elif isinstance(event, GrowthStageStarted):
            print(f"Growth stage {event.stage}: radius scale {event.radius_scale:.6g}")
        elif isinstance(event, GrowthStageRejected):
            print(
                f"Growth stage rejected; restoring scale {event.restored_scale:.6g}, "
                f"next increment {event.next_increment:.6g}"
            )
        elif isinstance(event, RunCompleted):
            print(
                f"Generated {event.particle_count} particles; "
                f"solid fraction: {event.solid_fraction:.9g}"
            )
            print(f"Saved {', '.join(event.filenames)} to {event.directory}")
        elif isinstance(event, RunFailed):
            print(f"Run failed: {event.error}")
