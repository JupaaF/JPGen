"""Packing methods independent of geometry preparation and solver setup."""

from .base import PackingResult, PackingStrategy
from .growth import ProgressiveGrowth
from .insertion import RandomSequentialInsertion
from .relaxation import OverlapRelaxation


PACKING_STRATEGIES = {
    "random_sequential": RandomSequentialInsertion,
    "overlap_relaxation": OverlapRelaxation,
    "progressive_growth": ProgressiveGrowth,
}
