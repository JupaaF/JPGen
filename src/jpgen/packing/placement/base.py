"""Typed contracts for particle placement algorithms."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from ..domain import Box, PlacementStatistics


@dataclass
class PlacementResult:
    positions: np.ndarray
    statistics: PlacementStatistics


@dataclass(frozen=True)
class PlacementConstraints:
    """Geometric limits shared by every placement algorithm."""

    max_overlap: float

    def __post_init__(self):
        if isinstance(self.max_overlap, bool) or not np.isfinite(self.max_overlap):
            raise ValueError("Maximum overlap must be a finite number.")
        if not 0 <= self.max_overlap <= 1:
            raise ValueError("Maximum overlap must be between zero and one.")
        object.__setattr__(self, "max_overlap", float(self.max_overlap))


@dataclass(frozen=True)
class PlacementRequest:
    """Inputs shared by every placement algorithm for one generation attempt."""

    box: Box
    radii: np.ndarray
    constraints: PlacementConstraints
    rng: np.random.Generator


class PlacementStrategy(ABC):
    """Place final radii in a final box without changing either input.

    The coordinator owns full restarts. Algorithms use only the supplied RNG and
    Raise PackingGenerationError on failure; internal displacements are not velocities.
    """

    method: ClassVar[str]

    @property
    def overlap_tolerance(self) -> float:
        return 0.0

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict):
        """Build a strategy from its method-specific packing mapping."""

    @abstractmethod
    def to_config(self) -> dict:
        """Return the complete normalized packing mapping."""

    @abstractmethod
    def place(self, request: PlacementRequest, observer=None) -> PlacementResult:
        """Return final positions and algorithm statistics for one attempt."""
