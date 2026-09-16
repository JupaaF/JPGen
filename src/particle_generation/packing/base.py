"""Independent contracts for placement algorithms and their results."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from ..domain import Box


@dataclass
class PackingResult:
    positions: np.ndarray
    statistics: dict


class PackingStrategy(ABC):
    """Place final radii in a final box without changing either input.

    The coordinator owns full restarts. Algorithms use only the supplied RNG and
    raise GenerationError on failure; internal displacements are not velocities.
    """

    @abstractmethod
    def validate_config(self, config: dict) -> None:
        """Validate and normalize the packing-specific configuration in place."""

    @abstractmethod
    def pack(self, box: Box, radii: np.ndarray, config: dict,
             rng: np.random.Generator, report=None) -> PackingResult:
        """Return final positions and algorithm statistics for one attempt."""
