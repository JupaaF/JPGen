"""Placement audits and algorithm-specific statistics."""

from dataclasses import dataclass
from typing import ClassVar

import numpy as np


@dataclass(frozen=True)
class PlacementAudit:
    max_observed_overlap: float
    max_overlap_excess: float
    overlap_tolerance: float

    def __post_init__(self):
        values = (self.max_observed_overlap, self.max_overlap_excess, self.overlap_tolerance)
        if not all(np.isfinite(value) and value >= 0 for value in values):
            raise ValueError("Placement audit values must be finite and nonnegative.")

    def to_dict(self):
        return {
            "max_observed_overlap": self.max_observed_overlap,
            "max_overlap_excess": self.max_overlap_excess,
            "overlap_tolerance": self.overlap_tolerance,
        }


PLACEMENT_STATISTICS_TYPES = {}


@dataclass(frozen=True)
class PlacementStatistics:
    method: ClassVar[str | None] = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        method = cls.__dict__.get("method")
        if method is None:
            return
        if not isinstance(method, str) or not method or method in PLACEMENT_STATISTICS_TYPES:
            raise ValueError(f"Invalid or duplicate placement statistics method: {method!r}.")
        PLACEMENT_STATISTICS_TYPES[method] = cls

    @classmethod
    def from_dict(cls, values):
        return cls(**values)

    position_draws: int
    iterations: int

    def __post_init__(self):
        if any(isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0
               for value in (self.position_draws, self.iterations)):
            raise ValueError("Placement counters must be nonnegative integers.")

    def to_dict(self):
        return {"position_draws": self.position_draws, "iterations": self.iterations}


@dataclass(frozen=True)
class InsertionStatistics(PlacementStatistics):
    method: ClassVar[str] = "random_sequential"

    max_observed_overlap: float

    def __post_init__(self):
        super().__post_init__()
        if not np.isfinite(self.max_observed_overlap) or self.max_observed_overlap < 0:
            raise ValueError("Observed overlap must be finite and nonnegative.")

    def to_dict(self):
        return {**super().to_dict(), "max_observed_overlap": self.max_observed_overlap}


@dataclass(frozen=True)
class RelaxationStatistics(PlacementStatistics):
    method: ClassVar[str] = "overlap_relaxation"

    perturbations: int

    def __post_init__(self):
        super().__post_init__()
        if isinstance(self.perturbations, bool) or not isinstance(self.perturbations, (int, np.integer)) or self.perturbations < 0:
            raise ValueError("Perturbations must be a nonnegative integer.")

    def to_dict(self):
        return {**super().to_dict(), "perturbations": self.perturbations}


@dataclass(frozen=True)
class GrowthStage:
    scale: float
    accepted: bool
    iterations: int
    max_excess: float

    def __post_init__(self):
        if not np.isfinite(self.scale) or self.scale <= 0:
            raise ValueError("Growth scale must be finite and positive.")
        if not isinstance(self.accepted, bool):
            raise ValueError("Growth acceptance must be boolean.")
        if isinstance(self.iterations, bool) or not isinstance(self.iterations, (int, np.integer)) or self.iterations < 0:
            raise ValueError("Growth iterations must be a nonnegative integer.")
        if not np.isfinite(self.max_excess) or self.max_excess < 0:
            raise ValueError("Growth overlap excess must be finite and nonnegative.")

    def to_dict(self):
        return {
            "scale": self.scale,
            "accepted": self.accepted,
            "iterations": self.iterations,
            "max_excess": self.max_excess,
        }


@dataclass(frozen=True)
class GrowthStatistics(RelaxationStatistics):
    method: ClassVar[str] = "progressive_growth"

    @classmethod
    def from_dict(cls, values):
        return cls(
            position_draws=values["position_draws"],
            iterations=values["iterations"],
            perturbations=values["perturbations"],
            final_scale=values["final_scale"],
            stages=tuple(GrowthStage(**stage) for stage in values["stages"]),
        )

    final_scale: float
    stages: tuple[GrowthStage, ...]

    def __post_init__(self):
        super().__post_init__()
        if not np.isfinite(self.final_scale) or self.final_scale <= 0:
            raise ValueError("Final growth scale must be finite and positive.")
        if not isinstance(self.stages, tuple) or not self.stages or not all(
            isinstance(stage, GrowthStage) for stage in self.stages
        ):
            raise ValueError("Growth statistics require typed stage records.")

    def to_dict(self):
        return {
            **super().to_dict(),
            "final_scale": self.final_scale,
            "stages": [stage.to_dict() for stage in self.stages],
            "accepted_stages": sum(stage.accepted for stage in self.stages),
            "rejected_stages": sum(not stage.accepted for stage in self.stages),
        }


def placement_statistics_from_dict(method, values):
    statistics_type = PLACEMENT_STATISTICS_TYPES.get(method)
    if statistics_type is None:
        raise ValueError(f"Unsupported placement statistics method: {method!r}.")
    return statistics_type.from_dict(values)
