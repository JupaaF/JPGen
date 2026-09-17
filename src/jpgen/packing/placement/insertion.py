"""Place particles by random sequential insertion."""

from dataclasses import dataclass
from functools import lru_cache
from itertools import product

import numpy as np

from ...configuration_values import integer, mapping
from ..domain import InsertionStatistics
from ...errors import PackingGenerationError
from .base import PlacementRequest, PlacementResult, PlacementStrategy
from .geometry import check_feasibility


@dataclass(frozen=True)
class RandomSequentialInsertion(PlacementStrategy):
    method = "random_sequential"
    position_attempts: int

    @classmethod
    def from_config(cls, config):
        mapping(config, "placement", {"method", "position_attempts"})
        attempts = integer(config.get("position_attempts", 1000), "placement.position_attempts")
        return cls(attempts)

    def to_config(self):
        return {"method": self.method, "position_attempts": self.position_attempts}

    def place(self, request: PlacementRequest, observer=None):
        positions, overlap, draws = _place_particles(
            request.radii,
            request.box,
            request.constraints.max_overlap,
            self.position_attempts,
            request.rng,
        )
        return PlacementResult(
            positions,
            InsertionStatistics(position_draws=draws, iterations=0, max_observed_overlap=overlap),
        )


def _place_particles(radii, box, max_overlap, attempts, rng):
    largest = float(np.max(radii))
    check_feasibility(radii, box, max_overlap)
    positions = np.empty((len(radii), 3), dtype=np.float64)
    cells = {}
    # Cell widths >= the largest possible interaction distance; cap indexing for tiny radii.
    counts = np.maximum(1, np.minimum(np.floor(box.lengths / (2 * largest)), 1_000_000)).astype(np.int64)
    widths = box.lengths / counts
    axis_counts = tuple(int(count) for count in counts)
    roundoff = 16 * np.finfo(float).eps

    @lru_cache(maxsize=4096)
    def axis_neighbors(axis, coordinate):
        count = axis_counts[axis]
        if box.periodic:
            # One- and two-cell axes must not contribute duplicate neighbors.
            return tuple(sorted({(coordinate + offset) % count for offset in (-1, 0, 1)}))
        return tuple(range(max(0, coordinate - 1), min(count, coordinate + 2)))

    observed = max(0.0, 1.0 - float(np.min(box.lengths)) / (2 * largest)) if box.periodic else 0.0
    position_draws = 0
    # Largest first improves insertion success; output remains in original ID/radius order.
    for index in np.argsort(-radii, kind="stable"):
        radius = radii[index]
        low = np.zeros(3) if box.periodic else np.full(3, radius)
        high = box.lengths if box.periodic else box.lengths - radius
        for _ in range(attempts):
            position_draws += 1
            candidate = rng.uniform(low, high)
            cell = tuple(np.minimum((candidate / widths).astype(np.int64), counts - 1).tolist())
            # Sorted axes give the same lexicographic order as sorted cell keys.
            neighbor_keys = product(*(axis_neighbors(axis, coordinate) for axis, coordinate in enumerate(cell)))
            neighbors = [j for key in neighbor_keys for j in cells.get(key, ())]
            local_overlap = 0.0
            rejected = False
            for start in range(0, len(neighbors), 128):
                indices = neighbors[start:start + 128]
                delta = np.abs(positions[indices] - candidate)
                if box.periodic:
                    delta = np.minimum(delta, box.lengths - delta)
                distance_squared = np.sum(delta * delta, axis=1)
                other_radii = radii[indices]
                if max_overlap < 1:
                    required = radius + other_radii - 2 * max_overlap * np.minimum(radius, other_radii)
                    # Leave near-threshold cases to the original overlap formula
                    # below, so rounding cannot introduce an early rejection.
                    safe_required = np.maximum(0, required - roundoff * (radius + other_radii))
                    if np.any(distance_squared < safe_required**2):
                        rejected = True
                        break
                distances = np.sqrt(distance_squared)
                overlaps = np.clip((radius + other_radii - distances) / (2 * np.minimum(radius, other_radii)), 0, 1)
                local_overlap = max(local_overlap, float(np.max(overlaps)))
                if local_overlap > max_overlap:
                    rejected = True
                    break
            if rejected:
                continue
            positions[index] = candidate
            cells.setdefault(cell, []).append(int(index))
            observed = max(observed, local_overlap)
            break
        else:
            raise PackingGenerationError(f"Could not place particle {index + 1} after {attempts} position attempts ({sum(map(len, cells.values()))}/{len(radii)} placed).")
    return positions + box.origin, observed, position_draws
