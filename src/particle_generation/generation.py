"""Random sequential insertion with a spatial hash and periodic minimum images."""

from itertools import product

import numpy as np

from .domain import ParticleSet
from .sampling import GenerationError, stream, vectors
from .strategies import GEOMETRY_STRATEGIES, solid_volume


OFFSETS = tuple(product((-1, 0, 1), repeat=3))


def place(radii, box, max_overlap, attempts, rng):
    largest = float(np.max(radii))
    if not box.periodic and np.any(2.0 * largest > box.lengths):
        raise GenerationError("A sphere is too large to fit completely inside the nonperiodic box.")
    # A sphere must also respect the overlap limit with its own periodic images.
    if box.periodic and np.any(2.0 * largest * (1.0 - max_overlap) > box.lengths):
        raise GenerationError("A sphere violates the overlap limit with its own periodic image.")
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


def generate(cfg, report=None):
    strategy = GEOMETRY_STRATEGIES[cfg["mode"]]()
    last_error = None
    for restart in range(cfg["restarts"] + 1):
        if report:
            report(f"Generation attempt {restart + 1}/{cfg['restarts'] + 1}")
        try:
            box, radii = strategy.prepare(cfg, stream(cfg["seed"], restart, 0))
            if "count" not in cfg and report:
                report(f"Expected particle count: {len(radii)}")
            volume = solid_volume(radii)
            if not np.all(np.isfinite(box.lengths)) or not np.isfinite(box.volume) or box.volume <= 0:
                raise GenerationError("Generated box is not representable in float64.")
            fraction = volume / box.volume
            if "target_solid_fraction" in cfg and abs(fraction - cfg["target_solid_fraction"]) > cfg["solid_fraction_tolerance"] + 1e-14:
                raise GenerationError(f"Sample solid fraction {fraction:.9g} is outside the requested tolerance.")
            positions, overlap, draws = place(radii, box, cfg["max_overlap"], cfg["position_attempts"], stream(cfg["seed"], restart, 1))
            count = len(radii)
            return ParticleSet(
                np.arange(1, count + 1, dtype=np.int64), positions, radii,
                vectors(cfg["velocity"], count, stream(cfg["seed"], restart, 2), stream(cfg["seed"], restart, 3)),
                vectors(cfg["angular_velocity"], count, stream(cfg["seed"], restart, 4), stream(cfg["seed"], restart, 5)),
                box,
                {"seed": cfg["seed"], "successful_restart": restart, "position_draws": draws,
                 "max_observed_overlap": overlap, "solid_fraction": fraction,
                 "count": count, "rng": "PCG64", "stream_scheme": "SeedSequence(seed, spawn_key=(restart, role)); roles: radii=0, positions=1, speed=2, direction=3, angular_speed=4, angular_direction=5"},
            )
        except GenerationError as error:
            last_error = error
            if report:
                report(f"Attempt failed: {error}")
    raise GenerationError(f"Generation failed after {cfg['restarts'] + 1} attempts. {last_error}")
