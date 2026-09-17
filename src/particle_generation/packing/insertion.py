"""Random sequential insertion; previously accepted particles remain fixed."""

from dataclasses import dataclass
from itertools import product

import numpy as np

from ..configuration_values import integer, mapping
from ..domain import InsertionStatistics
from ..errors import GenerationError
from .base import PackingRequest, PackingResult, PackingStrategy
from .geometry import check_feasibility


@dataclass(frozen=True)
class RandomSequentialInsertion(PackingStrategy):
    method = "random_sequential"
    position_attempts: int

    @classmethod
    def from_config(cls, config):
        mapping(config, "packing", {"method", "position_attempts"})
        attempts = integer(config.get("position_attempts", 1000), "packing.position_attempts")
        return cls(attempts)

    def to_config(self):
        return {"method": self.method, "position_attempts": self.position_attempts}

    def pack(self, request: PackingRequest, observer=None):
        positions, overlap, draws = place(
            request.radii,
            request.box,
            request.constraints.max_overlap,
            self.position_attempts,
            request.rng,
        )
        return PackingResult(
            positions,
            InsertionStatistics(position_draws=draws, iterations=0, max_observed_overlap=overlap),
        )


OFFSETS = tuple(product((-1, 0, 1), repeat=3))


def place(radii, box, max_overlap, attempts, rng):
    largest = float(np.max(radii))
    check_feasibility(radii, box, max_overlap)
    positions = np.empty((len(radii), 3), dtype=np.float64)
    cells = {}
    # Cell widths >= the largest possible interaction distance; cap indexing for tiny radii.
    counts = np.maximum(1, np.minimum(np.floor(box.lengths / (2 * largest)), 1_000_000)).astype(np.int64)
    widths = box.lengths / counts
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
            cell = np.minimum((candidate / widths).astype(np.int64), counts - 1)
            neighbor_keys = set()
            for offset in OFFSETS:
                key = tuple(int(cell[axis]) + offset[axis] for axis in range(3))
                if box.periodic:
                    key = tuple(key[axis] % int(counts[axis]) for axis in range(3))
                elif any(key[axis] < 0 or key[axis] >= counts[axis] for axis in range(3)):
                    continue
                neighbor_keys.add(key)
            neighbors = [j for key in sorted(neighbor_keys) for j in cells.get(key, ())]
            local_overlap = 0.0
            if neighbors:
                delta = np.abs(positions[neighbors] - candidate)
                if box.periodic:
                    delta = np.minimum(delta, box.lengths - delta)
                distances = np.linalg.norm(delta, axis=1)
                other_radii = radii[neighbors]
                overlaps = np.clip((radius + other_radii - distances) / (2 * np.minimum(radius, other_radii)), 0, 1)
                local_overlap = float(np.max(overlaps))
                if local_overlap > max_overlap:
                    continue
            positions[index] = candidate
            cells.setdefault(tuple(int(v) for v in cell), []).append(int(index))
            observed = max(observed, local_overlap)
            break
        else:
            raise GenerationError(f"Could not place particle {index + 1} after {attempts} position attempts ({sum(map(len, cells.values()))}/{len(radii)} placed).")
    return positions + box.origin, observed, position_draws
