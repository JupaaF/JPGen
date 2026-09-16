"""Structural checks for generated and restored particle datasets."""

import numpy as np


def validate_particles(particles):
    n = len(particles.ids)
    if not n or len(np.unique(particles.ids)) != n or np.any(particles.ids <= 0):
        raise ValueError("Particle IDs must be unique positive integers and the dataset must not be empty.")
    for field, shape in (("ids", (n,)), ("radii", (n,)),
                         ("positions", (n, 3)), ("velocities", (n, 3)), ("angular_velocities", (n, 3))):
        values = getattr(particles, field)
        if values.shape != shape or not np.all(np.isfinite(values)):
            raise ValueError(f"Invalid particle array: {field}.")
    if not np.issubdtype(particles.ids.dtype, np.integer):
        raise ValueError("Particle IDs must be integers.")
    if np.any(particles.radii <= 0):
        raise ValueError("Radii must be positive.")
    box = particles.box
    if box.origin.shape != (3,) or box.lengths.shape != (3,) or not np.all(np.isfinite(box.origin)) or not np.all(np.isfinite(box.lengths)) or np.any(box.lengths <= 0):
        raise ValueError("Invalid box geometry.")
    relative = particles.positions - box.origin
    margin = 0 if box.periodic else particles.radii[:, None]
    eps = 16 * np.finfo(float).eps * np.maximum(np.abs(box.origin) + box.lengths, 1e-300)
    if np.any(relative < margin - eps) or np.any(relative > box.lengths - margin + eps):
        raise ValueError("Particles lie outside their permitted box bounds.")
