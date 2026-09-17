"""Particle placement methods independent of sizing and DEM setup."""

from .base import PlacementConstraints, PlacementRequest, PlacementResult, PlacementStrategy
from .growth import ProgressiveGrowth
from .insertion import RandomSequentialInsertion
from .relaxation import OverlapRelaxation


PLACEMENT_STRATEGIES = {
    RandomSequentialInsertion.method: RandomSequentialInsertion,
    OverlapRelaxation.method: OverlapRelaxation,
    ProgressiveGrowth.method: ProgressiveGrowth,
}
