"""Geometric overlap removal, without masses, contact laws or physical time."""

from dataclasses import dataclass

import numpy as np

from ..configuration_values import integer, mapping, number
from ..sampling import GenerationError
from .base import PackingResult, PackingStrategy
from .geometry import check_feasibility, constrain, evaluate, random_positions


RELAXATION_OPTIONS = {
    "max_iterations", "step_size", "max_displacement", "stagnation_iterations",
    "improvement_tolerance", "max_perturbations", "perturbation", "overlap_tolerance",
}


def normalize_relaxation(config):
    """Normalize shared solver controls for both relaxation-based packers."""
    for name, default, minimum in (("max_iterations", 3000, 1), ("stagnation_iterations", 200, 1),
                                   ("max_perturbations", 3, 0)):
        config[name] = integer(config.get(name, default), f"packing.{name}", minimum)
    for name, default in (("step_size", 1.0), ("max_displacement", 0.2),
                          ("improvement_tolerance", 1e-6), ("perturbation", 0.01),
                          ("overlap_tolerance", 1e-8)):
        config[name] = number(config.get(name, default), f"packing.{name}", 0, 1, strict_min=True)


@dataclass
class RelaxationResult:
    positions: np.ndarray
    converged: bool
    iterations: int
    perturbations: int
    max_excess: float


def relax(positions, radii, box, max_overlap, options, rng, report=None):
    """Relax a copy of local positions; callers retain accepted stages for rollback."""
    positions = constrain(positions.copy(), radii, box)
    best_positions = positions.copy()
    best_energy = float("inf")
    last_progress = 0
    perturbations = 0
    for iteration in range(options["max_iterations"] + 1):
        excess, _, energy, correction = evaluate(positions, radii, box, max_overlap, rng)
        if excess <= options["overlap_tolerance"]:
            return RelaxationResult(positions, True, iteration, perturbations, excess)
        if energy < best_energy:
            if energy < best_energy * (1 - options["improvement_tolerance"]):
                last_progress = iteration
            best_energy = energy
            best_positions = positions.copy()
        if iteration == options["max_iterations"]:
            break
        if report and iteration and iteration % 100 == 0:
            report(f"Relaxation iteration {iteration}: maximum overlap excess {excess:.6g}")
        stalled = iteration - last_progress >= options["stagnation_iterations"]
        if stalled or not np.any(correction):
            if perturbations >= options["max_perturbations"]:
                break
            jitter = rng.normal(size=positions.shape)
            lengths = np.linalg.norm(jitter, axis=1)
            jitter = np.divide(jitter, lengths[:, None], out=np.zeros_like(jitter), where=lengths[:, None] != 0)
            positions = constrain(best_positions + options["perturbation"] * radii[:, None] * jitter, radii, box)
            perturbations += 1
            last_progress = iteration
            continue
        displacement = options["step_size"] * correction
        magnitude = np.linalg.norm(displacement, axis=1)
        cap = options["max_displacement"] * radii
        factor = np.minimum(1, np.divide(cap, magnitude, out=np.ones_like(cap), where=magnitude > 0))
        positions = constrain(positions + displacement * factor[:, None], radii, box)
    excess, _, _, _ = evaluate(best_positions, radii, box, max_overlap)
    return RelaxationResult(best_positions, False, iteration, perturbations, excess)


class OverlapRelaxation(PackingStrategy):
    def validate_config(self, config):
        mapping(config, "packing", {"method"} | RELAXATION_OPTIONS)
        normalize_relaxation(config)

    def pack(self, box, radii, config, rng, report=None):
        check_feasibility(radii, box, config["max_overlap"])
        initial = random_positions(radii, box, rng)
        result = relax(initial, radii, box, config["max_overlap"], config["packing"], rng, report)
        if not result.converged:
            raise GenerationError(f"Overlap relaxation did not converge after {result.iterations} iterations; maximum overlap excess {result.max_excess:.6g}.")
        return PackingResult(result.positions + box.origin, {
            "position_draws": len(radii), "iterations": result.iterations,
            "perturbations": result.perturbations,
        })
