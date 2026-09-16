"""Data shared by generation, storage and exporters; no solver dependencies."""

from dataclasses import dataclass

import numpy as np


@dataclass
class Box:
    origin: np.ndarray
    lengths: np.ndarray
    periodic: bool

    @property
    def volume(self):
        return float(np.prod(self.lengths))


@dataclass
class ParticleSet:
    ids: np.ndarray
    positions: np.ndarray
    radii: np.ndarray
    velocities: np.ndarray
    angular_velocities: np.ndarray
    box: Box
    metadata: dict

    @property
    def solid_fraction(self):
        return float(np.sum((4.0 * np.pi / 3.0) * self.radii**3) / self.box.volume)
