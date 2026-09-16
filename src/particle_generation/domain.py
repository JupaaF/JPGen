"""Validated domain values shared by generation, storage and exporters."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping

import numpy as np


def _readonly_array(value, name, dtype=None):
    """Own a normalized array so callers cannot mutate domain state by aliasing it."""
    try:
        result = np.array(value, dtype=dtype, copy=True)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"Invalid particle array: {name}.") from error
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class Box:
    origin: np.ndarray
    lengths: np.ndarray
    periodic: bool

    def __post_init__(self):
        origin = _readonly_array(self.origin, "box.origin", np.float64)
        lengths = _readonly_array(self.lengths, "box.lengths", np.float64)
        if origin.shape != (3,) or lengths.shape != (3,):
            raise ValueError("Box origin and lengths must contain three values.")
        if not np.all(np.isfinite(origin)) or not np.all(np.isfinite(lengths)) or np.any(lengths <= 0):
            raise ValueError("Invalid box geometry.")
        with np.errstate(over="ignore", invalid="ignore"):
            upper = origin + lengths
            volume = float(np.prod(lengths))
        if not np.all(np.isfinite(upper)) or np.any(upper == origin):
            raise ValueError("Box bounds cannot be represented accurately in float64.")
        if not np.isfinite(volume) or volume <= 0:
            raise ValueError("Box volume must be finite and positive in float64.")
        if not isinstance(self.periodic, (bool, np.bool_)):
            raise ValueError("Box periodicity must be a boolean.")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "lengths", lengths)
        object.__setattr__(self, "periodic", bool(self.periodic))

    @property
    def volume(self):
        return float(np.prod(self.lengths))


@dataclass(frozen=True)
class ParticleSet:
    ids: np.ndarray
    positions: np.ndarray
    radii: np.ndarray
    velocities: np.ndarray
    angular_velocities: np.ndarray
    box: Box
    metadata: Mapping

    def __post_init__(self):
        raw_ids = np.asarray(self.ids)
        if not np.issubdtype(raw_ids.dtype, np.integer):
            raise ValueError("Particle IDs must be integers.")
        arrays = {
            "ids": _readonly_array(raw_ids, "ids"),
            "positions": _readonly_array(self.positions, "positions", np.float64),
            "radii": _readonly_array(self.radii, "radii", np.float64),
            "velocities": _readonly_array(self.velocities, "velocities", np.float64),
            "angular_velocities": _readonly_array(
                self.angular_velocities, "angular_velocities", np.float64
            ),
        }
        for name, values in arrays.items():
            object.__setattr__(self, name, values)
        if not isinstance(self.box, Box):
            raise ValueError("Particle box must be a Box.")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("Particle metadata must be a mapping.")
        # Isolate the aggregate from mutations through the caller's input mapping.
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))
        self.validate()

    def validate(self):
        """Check aggregate invariants, including mutations forced outside the API."""
        n = len(self.ids)
        if not n or len(np.unique(self.ids)) != n or np.any(self.ids <= 0):
            raise ValueError("Particle IDs must be unique positive integers and the dataset must not be empty.")
        for field, shape in (
            ("ids", (n,)),
            ("radii", (n,)),
            ("positions", (n, 3)),
            ("velocities", (n, 3)),
            ("angular_velocities", (n, 3)),
        ):
            values = getattr(self, field)
            if values.shape != shape or not np.all(np.isfinite(values)):
                raise ValueError(f"Invalid particle array: {field}.")
        if not np.issubdtype(self.ids.dtype, np.integer):
            raise ValueError("Particle IDs must be integers.")
        if np.any(self.radii <= 0):
            raise ValueError("Radii must be positive.")
        relative = self.positions - self.box.origin
        margin = 0 if self.box.periodic else self.radii[:, None]
        epsilon = 16 * np.finfo(float).eps * np.maximum(
            np.abs(self.box.origin) + self.box.lengths, 1e-300
        )
        if np.any(relative < margin - epsilon) or np.any(
            relative > self.box.lengths - margin + epsilon
        ):
            raise ValueError("Particles lie outside their permitted box bounds.")

    @property
    def solid_fraction(self):
        return float(np.sum((4.0 * np.pi / 3.0) * self.radii**3) / self.box.volume)
