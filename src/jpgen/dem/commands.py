"""Typed portable actuator commands; also shipped with standalone workers."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class NoActuation:
    """Advance the solver without changing its current cell."""


@dataclass(frozen=True)
class CellStrainRate:
    """Logarithmic strain rate in 1/s; expansion is positive."""
    values: tuple[float, float, float]

    def __post_init__(self):
        _validate(self)


@dataclass(frozen=True)
class SymmetricWallVelocity:
    """Opposing face velocities in m/s; compression is positive."""
    values: tuple[float, float, float]

    def __post_init__(self):
        _validate(self)


def _validate(command):
    values = tuple(command.values)
    if len(values) != 3 or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
        raise ValueError("Actuator command requires three finite numbers.")
    object.__setattr__(command, "values", values)


ActuatorCommand = NoActuation | CellStrainRate | SymmetricWallVelocity
