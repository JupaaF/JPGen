"""Boundary operations and pair searches shared by placement algorithms."""

import numpy as np
from scipy.spatial import cKDTree

from ..domain import PlacementAudit
from ...errors import PackingGenerationError


def check_feasibility(radii, box, max_overlap):
    """Check whether a packing operation can satisfy its boundary constraints."""
    largest = float(np.max(radii))
    if not box.periodic and np.any(2 * largest > box.lengths):
        raise PackingGenerationError("A sphere is too large to fit completely inside the nonperiodic box.")
    if box.periodic and np.any(2 * largest * (1 - max_overlap) > box.lengths):
        raise PackingGenerationError("A sphere violates the overlap limit with its own periodic image.")


def constrain(positions, radii, box):
    """Work in box-local coordinates to avoid origin-dependent optimization."""
    if box.periodic:
        return np.mod(positions, box.lengths)
    return np.clip(positions, radii[:, None], box.lengths - radii[:, None])


def random_positions(radii, box, rng):
    lower = np.zeros((len(radii), 3)) if box.periodic else radii[:, None]
    upper = box.lengths if box.periodic else box.lengths - radii[:, None]
    return rng.uniform(lower, upper, size=(len(radii), 3))


def _candidate_pairs(positions, radii, box, skin=0.0):
    """Stream sorted pairs in fixed particle blocks, with per-particle cutoffs."""
    tree = cKDTree(positions, boxsize=box.lengths if box.periodic else None)
    largest = float(np.max(radii))
    for start in range(0, len(radii), 128):
        cutoff = np.nextafter(radii[start:start + 128] + largest + skin, np.inf)
        neighbors = tree.query_ball_point(positions[start:start + 128], cutoff, return_sorted=True)
        sizes = np.fromiter((len(items) for items in neighbors), dtype=np.int64)
        i = np.repeat(np.arange(start, start + len(neighbors)), sizes)
        j = np.concatenate(neighbors).astype(np.int64)
        keep = j > i
        i, j = i[keep], j[keep]
        if len(i):
            yield i, j


class NeighborList:
    """Reuse buffered pairs while every center stays within half the skin.

    One instance belongs to one relax() call with fixed radii and box. Growth
    stages therefore start fresh. Minimum-image displacements handle wrapping
    and also detect perturbations that require a rebuild. Dense configurations
    fall back to streaming rather than retaining an unbounded pair list.
    """

    max_cached_pairs = 1_000_000

    def __init__(self, radii, box):
        self.radii = radii
        self.box = box
        self.skin = 0.25 * float(np.max(radii))
        self.reference = None
        self.blocks = []
        self.streaming = False

    def candidates(self, positions):
        if self.streaming:
            yield from _candidate_pairs(positions, self.radii, self.box)
            return
        if self.reference is not None:
            delta = positions - self.reference
            if self.box.periodic:
                delta -= self.box.lengths * np.rint(delta / self.box.lengths)
            if np.all(np.sum(delta * delta, axis=1) < (0.5 * self.skin)**2):
                yield from self.blocks
                return
        self.reference = None
        self.blocks = []
        count = 0
        for i, j in _candidate_pairs(positions, self.radii, self.box, self.skin):
            count += len(i)
            if count <= self.max_cached_pairs:
                self.blocks.append((i, j))
            else:
                self.blocks = []
                self.streaming = True
            yield i, j
        if not self.streaming:
            self.reference = positions.copy()


def pairs(positions, radii, box, neighbors=None):
    """Yield potentially overlapping unordered pairs in deterministic blocks.

    Query blocks bound temporary memory even for fully overlapping inputs.
    Filter using squared distances before taking square roots; buffered lists
    retain the original block and neighbor order for correction accumulation.
    """
    candidates = (_candidate_pairs(positions, radii, box) if neighbors is None
                  else neighbors.candidates(positions))
    for i, j in candidates:
        delta = positions[i] - positions[j]
        if box.periodic:
            delta -= box.lengths * np.rint(delta / box.lengths)
        distance_squared = np.sum(delta * delta, axis=1)
        keep = distance_squared <= np.nextafter((radii[i] + radii[j])**2, np.inf)
        if np.any(keep):
            yield i[keep], j[keep], delta[keep], np.sqrt(distance_squared[keep])


def evaluate(positions, radii, box, max_overlap, rng=None, relax_all_overlaps=True,
             *, neighbors=None, compute_energy=True):
    """Measure violations and optionally assemble overlap corrections.

    When ``relax_all_overlaps`` is true, ``max_overlap`` is only the acceptance
    threshold and all overlaps are pushed towards zero. Otherwise, only the
    portion exceeding ``max_overlap`` contributes to the correction.
    ``compute_energy=False`` skips the energy metric (returns zero), allowing
    audits without an RNG to skip all correction and energy work.
    """
    correction = np.zeros_like(positions) if rng is not None else None
    degree = np.zeros(len(radii), dtype=np.int64) if rng is not None else None
    observed = max(0.0, 1 - float(np.min(box.lengths)) / (2 * float(np.max(radii)))) if box.periodic else 0.0
    maximum = 0.0
    energy = 0.0
    for i, j, delta, distance in pairs(positions, radii, box, neighbors):
        diameter = 2 * np.minimum(radii[i], radii[j])
        overlap = np.clip((radii[i] + radii[j] - distance) / diameter, 0, 1)
        observed = max(observed, float(overlap.max()))
        if max_overlap == 1:
            continue  # Complete containment is allowed, even for unequal radii.
        overlap_distance = np.maximum(0, radii[i] + radii[j] - distance)
        excess = np.maximum(0, overlap_distance - max_overlap * diameter)
        violation = excess > 0
        if np.any(violation):
            normalized = excess[violation] / diameter[violation]
            maximum = max(maximum, float(normalized.max()))
        if rng is None and not compute_energy:
            continue
        separation = overlap_distance if relax_all_overlaps else excess
        active = separation > 0
        if not np.any(active):
            continue
        if compute_energy:
            normalized_overlap = separation[active] / diameter[active]
            energy += float(np.sum(normalized_overlap**2))
        if rng is None:
            continue
        i, j = i[active], j[active]
        delta, distance = delta[active], distance[active]
        separation = separation[active]
        coincident = distance == 0
        direction = np.divide(delta, distance[:, None], out=np.zeros_like(delta), where=distance[:, None] != 0)
        if np.any(coincident):
            # Unit vectors sampled without privileging an axis; all randomness uses the packing stream.
            z = rng.uniform(-1, 1, int(coincident.sum()))
            angle = rng.uniform(0, 2 * np.pi, len(z))
            radial = np.sqrt(np.maximum(0, 1 - z*z))
            direction[coincident] = np.column_stack((radial*np.cos(angle), radial*np.sin(angle), z))
        shifts = 0.5 * separation[:, None] * direction
        np.add.at(correction, i, shifts)
        np.add.at(correction, j, -shifts)
        np.add.at(degree, i, 1)
        np.add.at(degree, j, 1)
    if correction is not None:
        correction /= np.maximum(degree, 1)[:, None]
    return maximum, observed, energy, correction


def audit_placement(positions, radii, box, max_overlap, tolerance):
    """Audit algorithm output against containment and overlap constraints."""
    check_feasibility(radii, box, max_overlap)
    if positions.shape != (len(radii), 3) or not np.all(np.isfinite(positions)):
        raise PackingGenerationError("Placement returned invalid positions.")
    local = positions - box.origin
    margin = 0 if box.periodic else radii[:, None]
    epsilon = 16 * np.finfo(float).eps * np.maximum(np.abs(box.origin) + box.lengths, 1e-300)
    if np.any(local < margin - epsilon) or np.any(local > box.lengths - margin + epsilon):
        raise PackingGenerationError("Placement returned centers outside the permitted bounds.")
    # Normalize only roundoff at boundaries before the periodic neighbor query.
    local = constrain(local, radii, box)
    excess, observed, _, _ = evaluate(local, radii, box, max_overlap, compute_energy=False)
    if excess > tolerance + 64 * np.finfo(float).eps:
        raise PackingGenerationError(f"Final placement exceeds the overlap limit by {excess:.6g}; tolerance is {tolerance:.6g}.")
    return PlacementAudit(
        max_observed_overlap=observed,
        max_overlap_excess=excess,
        overlap_tolerance=tolerance,
    )
