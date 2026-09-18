"""Structured progress events and console and logging observers."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ProgressEvent:
    """Marker base for observable application and algorithm events."""


@dataclass(frozen=True)
class RunStarted(ProgressEvent):
    directory: Path


@dataclass(frozen=True)
class PackingStarted(ProgressEvent):
    seed: int


@dataclass(frozen=True)
class PackingAttemptStarted(ProgressEvent):
    attempt: int
    total: int


@dataclass(frozen=True)
class ExpectedParticleCount(ProgressEvent):
    count: int


@dataclass(frozen=True)
class PackingAttemptFailed(ProgressEvent):
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
class PackingCompleted(ProgressEvent):
    directory: Path
    particle_count: int
    solid_fraction: float
    filenames: tuple[str, ...]


@dataclass(frozen=True)
class PackingFailed(ProgressEvent):
    directory: Path
    error: str


@dataclass(frozen=True)
class DemStarted(ProgressEvent):
    engine: str


@dataclass(frozen=True)
class DemCompleted(ProgressEvent):
    directory: Path
    time: float
    filenames: tuple[str, ...]


@dataclass(frozen=True)
class DemFailed(ProgressEvent):
    directory: Path
    error: str


@dataclass(frozen=True)
class RunCompleted(ProgressEvent):
    directory: Path


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


class LoggingProgressObserver:
    """Log progress events, optionally adding a handler inside each run.

    Uses this module's logger unless the caller supplies one and emits the
    same descriptive messages as the console observer.
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        run_filename: str | None = None,
    ) -> None:
        self.logger = logger if logger is not None else logging.getLogger(__name__)
        self.run_filename = run_filename
        self._run_handler = None

    def __call__(self, event: ProgressEvent) -> None:
        if isinstance(event, RunStarted) and self.run_filename is not None:
            self._open_run_log(event.directory)
        if isinstance(event, RunStarted):
            self.logger.info("Run directory: %s", event.directory)
        elif isinstance(event, PackingStarted):
            self.logger.info("Random seed: %s", event.seed)
        elif isinstance(event, PackingAttemptStarted):
            self.logger.info("Packing attempt %s/%s", event.attempt, event.total)
        elif isinstance(event, ExpectedParticleCount):
            self.logger.info("Expected particle count: %s", event.count)
        elif isinstance(event, PackingAttemptFailed):
            self.logger.warning("Attempt failed: %s", event.error)
        elif isinstance(event, RelaxationProgress):
            self.logger.debug(
                "Relaxation iteration %s: maximum overlap excess %.6g",
                event.iteration,
                event.max_overlap_excess,
            )
        elif isinstance(event, GrowthStageStarted):
            self.logger.info(
                "Growth stage %s: radius scale %.6g", event.stage, event.radius_scale
            )
        elif isinstance(event, GrowthStageRejected):
            self.logger.warning(
                "Growth stage rejected; restoring scale %.6g, next increment %.6g",
                event.restored_scale,
                event.next_increment,
            )
        elif isinstance(event, PackingCompleted):
            self.logger.info(
                "Packing contains %s particles; solid fraction: %.9g",
                event.particle_count,
                event.solid_fraction,
            )
            self.logger.info(
                "Saved %s to %s", ", ".join(event.filenames), event.directory
            )
        elif isinstance(event, PackingFailed):
            self.logger.error("Packing failed: %s", event.error)
        elif isinstance(event, RunCompleted):
            self.logger.info("Run completed: %s", event.directory)
        elif isinstance(event, DemStarted):
            self.logger.info(
                "DEM started with %s; solver output is saved under dem/logs.",
                event.engine,
            )
        elif isinstance(event, DemCompleted):
            self.logger.info(
                "DEM reached %.9g s; saved %s", event.time, ", ".join(event.filenames)
            )
        elif isinstance(event, DemFailed):
            self.logger.error("DEM failed: %s", event.error)
        elif isinstance(event, RunFailed):
            self.logger.error("Run failed: %s", event.error)
        if isinstance(event, (RunCompleted, RunFailed)):
            self._close_run_log()

    def _open_run_log(self, directory):
        self._close_run_log()
        handler = logging.FileHandler(directory / self.run_filename, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
        self.logger.addHandler(handler)
        self._run_handler = handler

    def _close_run_log(self):
        if self._run_handler is None:
            return
        self.logger.removeHandler(self._run_handler)
        self._run_handler.close()
        self._run_handler = None


class ConsoleProgressObserver:
    def __call__(self, event):
        if isinstance(event, RunStarted):
            print(f"Run directory: {event.directory}")
        elif isinstance(event, PackingStarted):
            print(f"Random seed: {event.seed}")
        elif isinstance(event, PackingAttemptStarted):
            print(f"Packing attempt {event.attempt}/{event.total}")
        elif isinstance(event, ExpectedParticleCount):
            print(f"Expected particle count: {event.count}")
        elif isinstance(event, PackingAttemptFailed):
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
        elif isinstance(event, PackingCompleted):
            print(
                f"Packing contains {event.particle_count} particles; "
                f"solid fraction: {event.solid_fraction:.9g}"
            )
            print(f"Saved {', '.join(event.filenames)} to {event.directory}")
        elif isinstance(event, PackingFailed):
            print(f"Packing failed: {event.error}")
        elif isinstance(event, RunCompleted):
            print(f"Run completed: {event.directory}")
        elif isinstance(event, DemStarted):
            print(f"DEM started with {event.engine}; solver output is saved under dem/logs.")
        elif isinstance(event, DemCompleted):
            print(f"DEM reached {event.time:.9g} s; saved {', '.join(event.filenames)}")
        elif isinstance(event, DemFailed):
            print(f"DEM failed: {event.error}")
        elif isinstance(event, RunFailed):
            print(f"Run failed: {event.error}")
