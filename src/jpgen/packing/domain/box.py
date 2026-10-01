"""Validated axis-aligned domain occupied by a particle packing."""

from dataclasses import dataclass

import numpy as np

from ._arrays import readonly_array
from ...particle_data import validate_box_geometry


@dataclass(frozen=True)
class Box:
    origin: np.ndarray
    lengths: np.ndarray
    periodic: bool

    def __post_init__(self):
        origin = readonly_array(self.origin, "box.origin", np.float64)
        lengths = readonly_array(self.lengths, "box.lengths", np.float64)
        validate_box_geometry(origin, lengths, self.periodic)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "lengths", lengths)
        object.__setattr__(self, "periodic", bool(self.periodic))

    @property
    def volume(self):
        return float(np.prod(self.lengths))
