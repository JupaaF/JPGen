"""Output port implemented by solver and visualization adapters."""

from typing import Protocol

from ..domain import ParticleSet


class ParticleExporter(Protocol):
    filename: str

    def export(self, path, particles: ParticleSet) -> None:
        """Write one external representation of a validated particle set."""
