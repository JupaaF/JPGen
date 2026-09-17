"""Packing output port implemented by solver and visualization adapters."""

from typing import Protocol

from ..domain import ParticlePacking


class PackingExporter(Protocol):
    filename: str

    def export(self, path, packing: ParticlePacking) -> None:
        """Write one external representation of a validated packing."""
