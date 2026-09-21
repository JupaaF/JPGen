"""Physical inputs and final particle state, independent of solver objects."""

from dataclasses import dataclass

import numpy as np

from ..packing.domain import ParticlePacking
from ..packing.domain.box import Box


@dataclass(frozen=True)
class Material:
    density: float
    young_modulus: float
    poisson_ratio: float


@dataclass(frozen=True)
class Contact:
    model: str
    static_friction: float
    dynamic_friction: float
    friction_decay: float
    restitution: float


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
    adaptive: dict | None = None
    duration: float | None = None

    @property
    def end_time(self):
        return self.duration if self.duration is not None else self.time_step * self.steps


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
        ids = np.asarray(self.ids)
        if ids.ndim != 1 or not len(ids) or not np.issubdtype(ids.dtype, np.integer):
            raise ValueError("DEM particle IDs must be a nonempty integer vector.")
        if np.any(ids <= 0) or len(np.unique(ids)) != len(ids):
            raise ValueError("DEM particle IDs must be unique and positive.")
        n = len(ids)
        for name, shape in (("ids", (n,)), ("positions", (n, 3)), ("radii", (n,)),
                            ("velocities", (n, 3)), ("angular_velocities", (n, 3))):
            array = np.array(getattr(self, name), dtype=np.int64 if name == "ids" else np.float64, copy=True)
            if array.shape != shape or not np.all(np.isfinite(array)):
                raise ValueError(f"Invalid DEM state array: {name}.")
            array.setflags(write=False)
            object.__setattr__(self, name, array)
        if np.any(self.radii <= 0) or not np.isfinite(self.time) or self.time < 0:
            raise ValueError("Invalid DEM radii or simulation time.")
