"""Packing methods independent of geometry preparation and solver setup."""

from .base import PackingConstraints, PackingRequest, PackingResult, PackingStrategy
from .growth import ProgressiveGrowth
from .insertion import RandomSequentialInsertion
from .relaxation import OverlapRelaxation


PACKING_STRATEGIES = {
    RandomSequentialInsertion.method: RandomSequentialInsertion,
    OverlapRelaxation.method: OverlapRelaxation,
    ProgressiveGrowth.method: ProgressiveGrowth,
}
