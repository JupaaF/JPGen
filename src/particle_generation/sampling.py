"""Independent random streams, bounded magnitude sampling and isotropic vectors."""

import numpy as np


class GenerationError(ValueError):
    pass


def stream(seed, restart, role):
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=(restart, role))))


def sample(spec, count, rng):
    kind = spec["type"]
    if kind == "explicit":
        return np.array(spec["values"], dtype=np.float64)
    if kind == "constant":
        return np.full(count, spec["value"], dtype=np.float64)
    if kind == "uniform":
        return rng.uniform(spec["min"], spec["max"], count)
    result = np.empty(count, dtype=np.float64)
    pending = np.arange(count)
    for _ in range(1000):
        if not len(pending):
            return result
        with np.errstate(over="ignore", invalid="ignore"):
            if kind == "normal":
                draws = rng.normal(spec["mean"], spec["std"], len(pending))
            else:
                draws = rng.lognormal(np.log(spec["median"]), spec["sigma"], len(pending))
        valid = np.isfinite(draws) & (draws >= spec["min"]) & (draws <= spec["max"])
        result[pending[valid]] = draws[valid]
        pending = pending[~valid]
    raise GenerationError("Distribution rejection limit reached (1000 draws per value); revise its parameters or bounds.")


def vectors(spec, count, magnitude_rng, direction_rng):
    magnitudes = sample(spec, count, magnitude_rng)
    z = direction_rng.uniform(-1.0, 1.0, count)
    angle = direction_rng.uniform(0.0, 2.0 * np.pi, count)
    radial = np.sqrt(np.maximum(0.0, 1.0 - z * z))
    return magnitudes[:, None] * np.column_stack((radial * np.cos(angle), radial * np.sin(angle), z))
