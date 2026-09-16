"""Progressive temporary-radius growth, composed with geometric relaxation."""

from ..configuration_values import ConfigurationError, integer, mapping, number
from ..sampling import GenerationError
from .base import PackingResult, PackingStrategy
from .geometry import check_feasibility, random_positions
from .relaxation import RELAXATION_OPTIONS, normalize_relaxation, relax


class ProgressiveGrowth(PackingStrategy):
    def validate_config(self, config):
        mapping(config, "packing", {"method", "initial_scale", "initial_increment", "min_increment",
                                    "max_increment", "max_stages"} | RELAXATION_OPTIONS)
        normalize_relaxation(config)
        for name, default in (("initial_scale", 0.25), ("initial_increment", 0.05),
                              ("min_increment", 1e-4), ("max_increment", 0.1)):
            config[name] = number(config.get(name, default), f"packing.{name}", 0, 1, strict_min=True)
        if config["initial_scale"] >= 1:
            raise ConfigurationError("packing.initial_scale must be smaller than 1.")
        if not config["min_increment"] <= config["initial_increment"] <= config["max_increment"]:
            raise ConfigurationError("Growth increments must satisfy min_increment <= initial_increment <= max_increment.")
        config["max_stages"] = integer(config.get("max_stages", 200), "packing.max_stages")

    def pack(self, box, radii, config, rng, report=None):
        check_feasibility(radii, box, config["max_overlap"])
        options = config["packing"]
        scale = options["initial_scale"]
        temporary_radii = scale * radii
        result = relax(random_positions(temporary_radii, box, rng), temporary_radii,
                       box, config["max_overlap"], options, rng, report)
        if not result.converged:
            raise GenerationError(f"Initial growth stage at scale {scale:.6g} did not converge; maximum overlap excess {result.max_excess:.6g}.")
        accepted = result.positions
        iterations = result.iterations
        perturbations = result.perturbations
        history = [{"scale": scale, "accepted": True, "iterations": result.iterations,
                    "max_excess": result.max_excess}]
        increment = options["initial_increment"]
        while scale < 1:
            if len(history) >= options["max_stages"]:
                raise GenerationError(f"Growth stage limit reached at scale {scale:.6g}; final radii were not reached.")
            trial_scale = min(1.0, scale + increment)
            if trial_scale <= scale:
                raise GenerationError("Growth increment is too small to change the radius scale.")
            if report:
                report(f"Growth stage {len(history) + 1}: radius scale {trial_scale:.6g}")
            # relax() copies accepted positions. Failed stages never overwrite this checkpoint.
            result = relax(accepted, trial_scale * radii, box, config["max_overlap"], options, rng, report)
            iterations += result.iterations
            perturbations += result.perturbations
            history.append({"scale": trial_scale, "accepted": result.converged,
                            "iterations": result.iterations, "max_excess": result.max_excess})
            if result.converged:
                accepted = result.positions
                scale = trial_scale
                if result.iterations <= max(1, options["max_iterations"] // 4):
                    increment = min(options["max_increment"], increment * 1.25)
            else:
                increment = (trial_scale - scale) * 0.5
                if report:
                    report(f"Growth stage rejected; restoring scale {scale:.6g}, next increment {increment:.6g}")
                if increment < options["min_increment"]:
                    raise GenerationError(f"Growth stalled at scale {scale:.6g}; increment fell below min_increment. Final radii were not reached.")
        return PackingResult(accepted + box.origin, {
            "position_draws": len(radii), "iterations": iterations, "perturbations": perturbations,
            "final_scale": scale, "stages": history,
            "accepted_stages": sum(stage["accepted"] for stage in history),
            "rejected_stages": sum(not stage["accepted"] for stage in history),
        })
