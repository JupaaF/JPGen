"""Validated axis-aligned particle domain."""

from dataclasses import dataclass

import numpy as np

from ._arrays import readonly_array


@dataclass(frozen=True)
class Box:
    origin: np.ndarray
    lengths: np.ndarray
    periodic: bool

    def __post_init__(self):
        origin = readonly_array(self.origin, "box.origin", np.float64)
        lengths = readonly_array(self.lengths, "box.lengths", np.float64)
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
