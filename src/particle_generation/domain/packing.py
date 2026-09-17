"""Packing audits and algorithm-specific generation statistics."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PackingAudit:
    max_observed_overlap: float
    max_overlap_excess: float
    overlap_tolerance: float

    def __post_init__(self):
        values = (self.max_observed_overlap, self.max_overlap_excess, self.overlap_tolerance)
        if not all(np.isfinite(value) and value >= 0 for value in values):
            raise ValueError("Packing audit values must be finite and nonnegative.")

    def to_dict(self):
        return {
            "max_observed_overlap": self.max_observed_overlap,
            "max_overlap_excess": self.max_overlap_excess,
            "overlap_tolerance": self.overlap_tolerance,
        }


@dataclass(frozen=True)
class PackingStatistics:
    position_draws: int
    iterations: int

    def __post_init__(self):
        if any(isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0
               for value in (self.position_draws, self.iterations)):
            raise ValueError("Packing counters must be nonnegative integers.")

    def to_dict(self):
        return {"position_draws": self.position_draws, "iterations": self.iterations}


@dataclass(frozen=True)
class InsertionStatistics(PackingStatistics):
    max_observed_overlap: float

    def __post_init__(self):
        super().__post_init__()
        if not np.isfinite(self.max_observed_overlap) or self.max_observed_overlap < 0:
            raise ValueError("Observed overlap must be finite and nonnegative.")

    def to_dict(self):
        return {**super().to_dict(), "max_observed_overlap": self.max_observed_overlap}


@dataclass(frozen=True)
class RelaxationStatistics(PackingStatistics):
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


def packing_statistics_from_dict(method, values):
    common = {"position_draws": values["position_draws"], "iterations": values["iterations"]}
    if method == "random_sequential":
        return InsertionStatistics(**common, max_observed_overlap=values["max_observed_overlap"])
    if method == "overlap_relaxation":
        return RelaxationStatistics(**common, perturbations=values["perturbations"])
    if method == "progressive_growth":
        stages = tuple(GrowthStage(**stage) for stage in values["stages"])
        return GrowthStatistics(
            **common,
            perturbations=values["perturbations"],
            final_scale=values["final_scale"],
            stages=stages,
        )
    raise ValueError(f"Unsupported packing statistics method: {method!r}.")
