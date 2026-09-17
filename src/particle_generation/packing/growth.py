"""Progressive temporary-radius growth, composed with geometric relaxation."""

from dataclasses import dataclass

from ..configuration_values import integer, mapping, number
from ..domain import GrowthStage, GrowthStatistics
from ..errors import ConfigurationError, GenerationError
from ..progress import GrowthStageRejected, GrowthStageStarted, emit
from .base import PackingRequest, PackingResult, PackingStrategy
from .geometry import check_feasibility, random_positions
from .relaxation import RELAXATION_OPTIONS, RelaxationOptions, relax


@dataclass(frozen=True)
class ProgressiveGrowth(PackingStrategy):
    method = "progressive_growth"
    options: RelaxationOptions
    initial_scale: float
    initial_increment: float
    min_increment: float
    max_increment: float
    max_stages: int

    @property
    def overlap_tolerance(self):
        return self.options.overlap_tolerance

    @classmethod
    def from_config(cls, config):
        mapping(config, "packing", {"method", "initial_scale", "initial_increment", "min_increment",
                                    "max_increment", "max_stages"} | RELAXATION_OPTIONS)
        values = {}
        for name, default in (("initial_scale", 0.25), ("initial_increment", 0.05),
                              ("min_increment", 1e-4), ("max_increment", 0.1)):
            values[name] = number(config.get(name, default), f"packing.{name}", 0, 1, strict_min=True)
        if values["initial_scale"] >= 1:
            raise ConfigurationError("packing.initial_scale must be smaller than 1.")
        if not values["min_increment"] <= values["initial_increment"] <= values["max_increment"]:
            raise ConfigurationError("Growth increments must satisfy min_increment <= initial_increment <= max_increment.")
        return cls(
            RelaxationOptions.from_config(config),
            max_stages=integer(config.get("max_stages", 200), "packing.max_stages"),
            **values,
        )

    def to_config(self):
        return {
            "method": self.method,
            **self.options.to_config(),
            "initial_scale": self.initial_scale,
            "initial_increment": self.initial_increment,
            "min_increment": self.min_increment,
            "max_increment": self.max_increment,
            "max_stages": self.max_stages,
        }

    def pack(self, request: PackingRequest, observer=None):
        check_feasibility(request.radii, request.box, request.constraints.max_overlap)
        scale = self.initial_scale
        temporary_radii = scale * request.radii
        result = relax(random_positions(temporary_radii, request.box, request.rng), temporary_radii,
                       request.box, request.constraints.max_overlap, self.options, request.rng, observer)
        if not result.converged:
            raise GenerationError(f"Initial growth stage at scale {scale:.6g} did not converge; maximum overlap excess {result.max_excess:.6g}.")
        accepted = result.positions
        iterations = result.iterations
        perturbations = result.perturbations
        history = [GrowthStage(scale, True, result.iterations, result.max_excess)]
        increment = self.initial_increment
        while scale < 1:
            if len(history) >= self.max_stages:
                raise GenerationError(f"Growth stage limit reached at scale {scale:.6g}; final radii were not reached.")
            trial_scale = min(1.0, scale + increment)
            if trial_scale <= scale:
                raise GenerationError("Growth increment is too small to change the radius scale.")
            emit(observer, GrowthStageStarted(len(history) + 1, trial_scale))
            # relax() copies accepted positions. Failed stages never overwrite this checkpoint.
            result = relax(accepted, trial_scale * request.radii, request.box,
                           request.constraints.max_overlap,
                           self.options, request.rng, observer)
            iterations += result.iterations
            perturbations += result.perturbations
            history.append(GrowthStage(trial_scale, result.converged, result.iterations, result.max_excess))
            if result.converged:
                accepted = result.positions
                scale = trial_scale
                if result.iterations <= max(1, self.options.max_iterations // 4):
                    increment = min(self.max_increment, increment * 1.25)
            else:
                increment = (trial_scale - scale) * 0.5
                emit(observer, GrowthStageRejected(scale, increment))
                if increment < self.min_increment:
                    raise GenerationError(f"Growth stalled at scale {scale:.6g}; increment fell below min_increment. Final radii were not reached.")
        return PackingResult(
            accepted + request.box.origin,
            GrowthStatistics(
                position_draws=len(request.radii),
                iterations=iterations,
                perturbations=perturbations,
                final_scale=scale,
                stages=tuple(history),
            ),
        )
