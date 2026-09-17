"""Particle aggregates and reproducibility metadata."""

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

import numpy as np

from ._arrays import readonly_array
from .box import Box
from .packing import (
    GrowthStatistics,
    InsertionStatistics,
    PackingAudit,
    PackingStatistics,
    RelaxationStatistics,
    packing_statistics_from_dict,
)


@dataclass(frozen=True)
class GenerationMetadata:
    seed: int
    successful_restart: int
    packing_method: str
    packing: PackingStatistics
    audit: PackingAudit
    solid_fraction: float
    count: int
    rng: str
    stream_scheme: str
    versions: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("Metadata seed must be a nonnegative integer.")
        if isinstance(self.successful_restart, bool) or not isinstance(self.successful_restart, int) or self.successful_restart < 0:
            raise ValueError("Successful restart must be a nonnegative integer.")
        expected_statistics = {
            "random_sequential": InsertionStatistics,
            "overlap_relaxation": RelaxationStatistics,
            "progressive_growth": GrowthStatistics,
        }
        if (
            self.packing_method not in expected_statistics
            or type(self.packing) is not expected_statistics[self.packing_method]
        ):
            raise ValueError("Packing method and statistics type are inconsistent.")
        if not isinstance(self.audit, PackingAudit):
            raise ValueError("Metadata requires typed packing statistics and audit.")
        if not np.isfinite(self.solid_fraction) or self.solid_fraction <= 0:
            raise ValueError("Solid fraction must be finite and positive.")
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count <= 0:
            raise ValueError("Particle count must be a positive integer.")
        if not isinstance(self.versions, Mapping):
            raise ValueError("Versions must be a mapping.")
        if not isinstance(self.rng, str) or not isinstance(self.stream_scheme, str):
            raise ValueError("Random generator metadata must be textual.")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in self.versions.items()):
            raise ValueError("Version names and values must be strings.")
        object.__setattr__(self, "versions", MappingProxyType(deepcopy(dict(self.versions))))

    def with_versions(self, versions):
        return GenerationMetadata(
            seed=self.seed,
            successful_restart=self.successful_restart,
            packing_method=self.packing_method,
            packing=self.packing,
            audit=self.audit,
            solid_fraction=self.solid_fraction,
            count=self.count,
            rng=self.rng,
            stream_scheme=self.stream_scheme,
            versions=versions,
        )

    def to_dict(self):
        return {
            "seed": self.seed,
            "successful_restart": self.successful_restart,
            "packing_method": self.packing_method,
            "packing": self.packing.to_dict(),
            **self.audit.to_dict(),
            "solid_fraction": self.solid_fraction,
            "count": self.count,
            "rng": self.rng,
            "stream_scheme": self.stream_scheme,
            "versions": dict(self.versions),
        }

    @classmethod
    def from_dict(cls, values):
        method = values["packing_method"]
        return cls(
            seed=values["seed"],
            successful_restart=values["successful_restart"],
            packing_method=method,
            packing=packing_statistics_from_dict(method, values["packing"]),
            audit=PackingAudit(
                max_observed_overlap=values["max_observed_overlap"],
                max_overlap_excess=values["max_overlap_excess"],
                overlap_tolerance=values["overlap_tolerance"],
            ),
            solid_fraction=values["solid_fraction"],
            count=values["count"],
            rng=values["rng"],
            stream_scheme=values["stream_scheme"],
            versions=values.get("versions", {}),
        )


@dataclass(frozen=True)
class ParticleSet:
    ids: np.ndarray
    positions: np.ndarray
    radii: np.ndarray
    velocities: np.ndarray
    angular_velocities: np.ndarray
    box: Box
    metadata: GenerationMetadata

    def __post_init__(self):
        raw_ids = np.asarray(self.ids)
        if not np.issubdtype(raw_ids.dtype, np.integer):
            raise ValueError("Particle IDs must be integers.")
        arrays = {
            "ids": readonly_array(raw_ids, "ids"),
            "positions": readonly_array(self.positions, "positions", np.float64),
            "radii": readonly_array(self.radii, "radii", np.float64),
            "velocities": readonly_array(self.velocities, "velocities", np.float64),
            "angular_velocities": readonly_array(
                self.angular_velocities, "angular_velocities", np.float64
            ),
        }
        for name, values in arrays.items():
            object.__setattr__(self, name, values)
        if not isinstance(self.box, Box):
            raise ValueError("Particle box must be a Box.")
        if not isinstance(self.metadata, GenerationMetadata):
            raise ValueError("Particle metadata must be GenerationMetadata.")
        self.validate()

    def with_metadata(self, metadata):
        if not isinstance(metadata, GenerationMetadata):
            raise ValueError("Particle metadata must be GenerationMetadata.")
        result = object.__new__(ParticleSet)
        for name in ("ids", "positions", "radii", "velocities", "angular_velocities", "box"):
            object.__setattr__(result, name, getattr(self, name))
        object.__setattr__(result, "metadata", metadata)
        result.validate()
        return result

    def validate(self):
        """Check aggregate invariants, including mutations forced outside the API."""
        n = len(self.ids)
        if not n or len(np.unique(self.ids)) != n or np.any(self.ids <= 0):
            raise ValueError("Particle IDs must be unique positive integers and the dataset must not be empty.")
        for field, shape in (
            ("ids", (n,)),
            ("radii", (n,)),
            ("positions", (n, 3)),
            ("velocities", (n, 3)),
            ("angular_velocities", (n, 3)),
        ):
            values = getattr(self, field)
            if values.shape != shape or not np.all(np.isfinite(values)):
                raise ValueError(f"Invalid particle array: {field}.")
        if not np.issubdtype(self.ids.dtype, np.integer):
            raise ValueError("Particle IDs must be integers.")
        if np.any(self.radii <= 0):
            raise ValueError("Radii must be positive.")
        if self.metadata.count != n:
            raise ValueError("Particle metadata count does not match the particle arrays.")
        solid_fraction = self._calculate_solid_fraction()
        if not np.isfinite(solid_fraction) or solid_fraction <= 0:
            raise ValueError("Particle solid fraction must be finite and positive.")
        if not np.isclose(
            self.metadata.solid_fraction,
            solid_fraction,
            rtol=1e-12,
            atol=0.0,
        ):
            raise ValueError("Particle metadata solid fraction does not match the particle geometry.")
        relative = self.positions - self.box.origin
        margin = 0 if self.box.periodic else self.radii[:, None]
        epsilon = 16 * np.finfo(float).eps * np.maximum(
            np.abs(self.box.origin) + self.box.lengths, 1e-300
        )
        if np.any(relative < margin - epsilon) or np.any(
            relative > self.box.lengths - margin + epsilon
        ):
            raise ValueError("Particles lie outside their permitted box bounds.")

    def _calculate_solid_fraction(self):
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            return float(np.sum((4.0 * np.pi / 3.0) * self.radii**3) / self.box.volume)

    @property
    def solid_fraction(self):
        return self._calculate_solid_fraction()
