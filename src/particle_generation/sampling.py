"""Independent random streams and isotropic vector construction."""

import numpy as np


def stream(seed, restart, role):
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=(restart, role))))


def vectors(distribution, count, magnitude_rng, direction_rng):
    magnitudes = distribution.sample(count, magnitude_rng)
    z = direction_rng.uniform(-1.0, 1.0, count)
    angle = direction_rng.uniform(0.0, 2.0 * np.pi, count)
    radial = np.sqrt(np.maximum(0.0, 1.0 - z * z))
    return magnitudes[:, None] * np.column_stack((radial * np.cos(angle), radial * np.sin(angle), z))
