"""Pairwise sphere overlap reductions, also copied into standalone DEM cases."""

import math

import numpy as np


OVERLAP_OBSERVABLES = {
    'overlap_length', 'overlap_area', 'overlap_volume',
    'normalized_overlap_length', 'normalized_overlap_area', 'normalized_overlap_volume',
}


def measure_overlap(first, second, distances, *, cell_volume=None):
    """Sum unique contact pairs; normalize only when a periodic volume is given.

    Area means the intersection circle, not the lens surface. Contained spheres
    have no intersection circle: their area is zero and their overlap volume is
    the smaller sphere's volume. Length remains max(ri + rj - d, 0).
    """
    first = np.asarray(first, dtype=float)
    second = np.asarray(second, dtype=float)
    distances = np.asarray(distances, dtype=float)
    if (first.shape != second.shape or first.shape != distances.shape or first.ndim != 1
            or not all(np.all(np.isfinite(a)) for a in (first, second, distances))
            or np.any(first <= 0) or np.any(second <= 0) or np.any(distances < 0)):
        raise ValueError('Invalid sphere overlap geometry.')
    depths = np.maximum(first + second - distances, 0)
    active = depths > 0
    contained = active & (distances <= np.abs(first - second))
    partial = active & ~contained
    volumes = np.zeros_like(distances)
    areas = np.zeros_like(distances)
    volumes[contained] = 4 * np.pi / 3 * np.minimum(first[contained], second[contained])**3
    # Cap heights expressed in penetration depth avoid cancellation near tangency.
    depth = depths[partial]
    r1, r2, d = first[partial], second[partial], distances[partial]
    h1 = np.clip(depth * (2 * r2 - depth) / (2 * d), 0, 2 * r1)
    h2 = np.clip(depth * (2 * r1 - depth) / (2 * d), 0, 2 * r2)
    areas[partial] = np.pi * np.maximum(h1 * (2 * r1 - h1), 0)
    volumes[partial] = np.pi / 3 * (h1**2 * (3 * r1 - h1) + h2**2 * (3 * r2 - h2))
    result = {
        'overlap_length': float(np.sum(depths)),
        'overlap_area': float(np.sum(areas)),
        'overlap_volume': float(np.sum(volumes)),
    }
    if cell_volume is not None:
        if not math.isfinite(cell_volume) or cell_volume <= 0:
            raise ValueError('Overlap normalization requires a positive finite cell volume.')
        length = cell_volume**(1 / 3)
        result.update(
            normalized_overlap_length=result['overlap_length'] / length,
            normalized_overlap_area=result['overlap_area'] / length**2,
            normalized_overlap_volume=result['overlap_volume'] / cell_volume,
        )
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError('Nonfinite sphere overlap observable.')
    return result
