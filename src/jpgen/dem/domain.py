"""Physical inputs and final particle state, independent of solver objects."""

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ..packing.domain import ParticlePacking
from ..packing.domain.box import Box
from ..particle_data import ARRAYS, validate_particle_arrays, validate_particle_array, validate_time
from ..packing.domain._arrays import readonly_array


@dataclass(frozen=True)
class Material:
    density: float
    young_modulus: float
    poisson_ratio: float


class Contact(Protocol):
    """A portable contact specification with model-specific parameters."""
    @property
    def model(self) -> str: ...

    def to_config(self) -> dict: ...


@dataclass(frozen=True)
class Integration:
    translation: str = "symplectic_euler"
    rotation: str = "direct"


@dataclass(frozen=True)
class DemCase:
    packing: ParticlePacking
    material: Material
    contact: Contact
    boundary: str
    gravity: tuple[float, float, float]
    time_step: float
    steps: int
    protocol: dict | None = None
    integration: Integration = Integration()

    @property
    def end_time(self):
        return self.time_step * self.steps


@dataclass(frozen=True)
class DemState:
    """Final state; open boundaries may place particles outside the initial box."""

    ids: np.ndarray
    positions: np.ndarray
    radii: np.ndarray
    velocities: np.ndarray
    angular_velocities: np.ndarray
    time: float
    box: Box | None = None

    def __post_init__(self):
        if self.box is not None and not isinstance(self.box, Box):
            raise ValueError("DEM state box must be a Box.")
        validate_particle_arrays({name: getattr(self, name) for name in ARRAYS})
        validate_time(self.time)
        for name in ARRAYS:
            array = readonly_array(getattr(self, name), name,
                                   np.int64 if name == "ids" else np.float64)
            validate_particle_array(name, array, len(self.ids), strict_dtype=True)
            object.__setattr__(self, name, array)
