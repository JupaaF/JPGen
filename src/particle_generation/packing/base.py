"""Typed contracts for placement algorithms and their results."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from ..domain import Box, PackingStatistics


@dataclass
class PackingResult:
    positions: np.ndarray
    statistics: PackingStatistics


@dataclass(frozen=True)
class PackingConstraints:
    """Geometric limits shared by every placement algorithm."""

    max_overlap: float

    def __post_init__(self):
        if isinstance(self.max_overlap, bool) or not np.isfinite(self.max_overlap):
            raise ValueError("Maximum overlap must be a finite number.")
        if not 0 <= self.max_overlap <= 1:
            raise ValueError("Maximum overlap must be between zero and one.")
        object.__setattr__(self, "max_overlap", float(self.max_overlap))


@dataclass(frozen=True)
class PackingRequest:
    """Inputs shared by every placement algorithm for one generation attempt."""

    box: Box
    radii: np.ndarray
    constraints: PackingConstraints
    rng: np.random.Generator


class PackingStrategy(ABC):
    """Place final radii in a final box without changing either input.

    The coordinator owns full restarts. Algorithms use only the supplied RNG and
    raise GenerationError on failure; internal displacements are not velocities.
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
    def pack(self, request: PackingRequest, observer=None) -> PackingResult:
        """Return final positions and algorithm statistics for one attempt."""
