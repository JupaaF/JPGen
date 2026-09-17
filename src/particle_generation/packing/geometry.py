"""Boundary operations and bounded-memory pair searches shared by packers."""

import numpy as np
from scipy.spatial import cKDTree

from ..domain import PackingAudit
from ..errors import GenerationError


def check_feasibility(radii, box, max_overlap):
    """Check whether a packing operation can satisfy its boundary constraints."""
    largest = float(np.max(radii))
    if not box.periodic and np.any(2 * largest > box.lengths):
        raise GenerationError("A sphere is too large to fit completely inside the nonperiodic box.")
    if box.periodic and np.any(2 * largest * (1 - max_overlap) > box.lengths):
        raise GenerationError("A sphere violates the overlap limit with its own periodic image.")


def constrain(positions, radii, box):
    """Work in box-local coordinates to avoid origin-dependent optimization."""
    if box.periodic:
        return np.mod(positions, box.lengths)
    return np.clip(positions, radii[:, None], box.lengths - radii[:, None])


def random_positions(radii, box, rng):
    lower = np.zeros((len(radii), 3)) if box.periodic else radii[:, None]
    upper = box.lengths if box.periodic else box.lengths - radii[:, None]
    return rng.uniform(lower, upper, size=(len(radii), 3))


def pairs(positions, radii, box):
    """Yield each nearby unordered pair once; rebuild neighbors after every move.

    Query blocks bound temporary memory, including for fully overlapping inputs.
    Sorting neighbors makes pair accumulation deterministic within an environment.
    """
    tree = cKDTree(positions, boxsize=box.lengths if box.periodic else None)
    cutoff = 2 * float(np.max(radii))
    for start in range(0, len(radii), 128):
        neighbors = tree.query_ball_point(positions[start:start + 128], cutoff, return_sorted=True)
        sizes = np.fromiter((len(items) for items in neighbors), dtype=np.int64)
        i = np.repeat(np.arange(start, start + len(neighbors)), sizes)
        j = np.concatenate(neighbors).astype(np.int64)
        keep = j > i
        i, j = i[keep], j[keep]
        if not len(i):
            continue
        delta = positions[i] - positions[j]
        if box.periodic:
            delta -= box.lengths * np.rint(delta / box.lengths)
        yield i, j, delta, np.linalg.norm(delta, axis=1)


def evaluate(positions, radii, box, max_overlap, rng=None):
    """Measure violations and optionally assemble damped pair-separation directions."""
    correction = np.zeros_like(positions) if rng is not None else None
    degree = np.zeros(len(radii), dtype=np.int64) if rng is not None else None
    observed = max(0.0, 1 - float(np.min(box.lengths)) / (2 * float(np.max(radii)))) if box.periodic else 0.0
    maximum = 0.0
    energy = 0.0
    for i, j, delta, distance in pairs(positions, radii, box):
        diameter = 2 * np.minimum(radii[i], radii[j])
        overlap = np.clip((radii[i] + radii[j] - distance) / diameter, 0, 1)
        observed = max(observed, float(overlap.max()))
        if max_overlap == 1:
            continue  # Complete containment is allowed, even for unequal radii.
        excess = np.maximum(0, radii[i] + radii[j] - max_overlap * diameter - distance)
        active = excess > 0
        if not np.any(active):
            continue
        normalized = excess / diameter
        maximum = max(maximum, float(normalized.max()))
        energy += float(np.sum(normalized**2))
        if rng is None:
            continue
        i, j = i[active], j[active]
        delta, distance, excess = delta[active], distance[active], excess[active]
        coincident = distance == 0
        direction = np.divide(delta, distance[:, None], out=np.zeros_like(delta), where=distance[:, None] != 0)
        if np.any(coincident):
            # Unit vectors sampled without privileging an axis; all randomness uses the packing stream.
            z = rng.uniform(-1, 1, int(coincident.sum()))
            angle = rng.uniform(0, 2 * np.pi, len(z))
            radial = np.sqrt(np.maximum(0, 1 - z*z))
            direction[coincident] = np.column_stack((radial*np.cos(angle), radial*np.sin(angle), z))
        shifts = 0.5 * excess[:, None] * direction
        np.add.at(correction, i, shifts)
        np.add.at(correction, j, -shifts)
        np.add.at(degree, i, 1)
        np.add.at(degree, j, 1)
    if correction is not None:
        correction /= np.maximum(degree, 1)[:, None]
    return maximum, observed, energy, correction


def audit_packing(positions, radii, box, max_overlap, tolerance):
    """Audit algorithm output against containment and overlap constraints."""
    check_feasibility(radii, box, max_overlap)
    if positions.shape != (len(radii), 3) or not np.all(np.isfinite(positions)):
        raise GenerationError("Packing returned invalid positions.")
    local = positions - box.origin
    margin = 0 if box.periodic else radii[:, None]
    epsilon = 16 * np.finfo(float).eps * np.maximum(np.abs(box.origin) + box.lengths, 1e-300)
    if np.any(local < margin - epsilon) or np.any(local > box.lengths - margin + epsilon):
        raise GenerationError("Packing returned centers outside the permitted bounds.")
    # Normalize only roundoff at boundaries before the periodic neighbor query.
    local = constrain(local, radii, box)
    excess, observed, _, _ = evaluate(local, radii, box, max_overlap)
    if excess > tolerance + 64 * np.finfo(float).eps:
        raise GenerationError(f"Final packing exceeds the overlap limit by {excess:.6g}; tolerance is {tolerance:.6g}.")
    return PackingAudit(
        max_observed_overlap=observed,
        max_overlap_excess=excess,
        overlap_tolerance=tolerance,
    )
