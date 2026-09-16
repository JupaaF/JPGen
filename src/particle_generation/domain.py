"""Validated domain values shared by generation, storage and exporters."""

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

import numpy as np


def _readonly_array(value, name, dtype=None):
    """Own a normalized array so callers cannot mutate domain state by aliasing it."""
    try:
        result = np.array(value, dtype=dtype, copy=True)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"Invalid particle array: {name}.") from error
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class Box:
    origin: np.ndarray
    lengths: np.ndarray
    periodic: bool

    def __post_init__(self):
        origin = _readonly_array(self.origin, "box.origin", np.float64)
        lengths = _readonly_array(self.lengths, "box.lengths", np.float64)
        if origin.shape != (3,) or lengths.shape != (3,):
            raise ValueError("Box origin and lengths must contain three values.")
        if not np.all(np.isfinite(origin)) or not np.all(np.isfinite(lengths)) or np.any(lengths <= 0):
            raise ValueError("Invalid box geometry.")
        with np.errstate(over="ignore", invalid="ignore"):
            upper = origin + lengths
            volume = float(np.prod(lengths))
        if not np.all(np.isfinite(upper)) or np.any(upper == origin):
            raise ValueError("Box bounds cannot be represented accurately in float64.")
        if not np.isfinite(volume) or volume <= 0:
            raise ValueError("Box volume must be finite and positive in float64.")
        if not isinstance(self.periodic, (bool, np.bool_)):
            raise ValueError("Box periodicity must be a boolean.")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "lengths", lengths)
        object.__setattr__(self, "periodic", bool(self.periodic))

    @property
    def volume(self):
        return float(np.prod(self.lengths))


@dataclass(frozen=True)
class PackingAudit:
    max_observed_overlap: float
    max_overlap_excess: float
    overlap_tolerance: float

    def __post_init__(self):
        values = (self.max_observed_overlap, self.max_overlap_excess, self.overlap_tolerance)
        if not all(np.isfinite(value) and value >= 0 for value in values):
            raise ValueError("Packing audit values must be finite and nonnegative.")

    def to_dict(self):
        return {
            "max_observed_overlap": self.max_observed_overlap,
            "max_overlap_excess": self.max_overlap_excess,
            "overlap_tolerance": self.overlap_tolerance,
        }


@dataclass(frozen=True)
class PackingStatistics:
    position_draws: int
    iterations: int

    def __post_init__(self):
        if any(isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0
               for value in (self.position_draws, self.iterations)):
            raise ValueError("Packing counters must be nonnegative integers.")

    def to_dict(self):
        return {"position_draws": self.position_draws, "iterations": self.iterations}


@dataclass(frozen=True)
class InsertionStatistics(PackingStatistics):
    max_observed_overlap: float

    def __post_init__(self):
        super().__post_init__()
        if not np.isfinite(self.max_observed_overlap) or self.max_observed_overlap < 0:
            raise ValueError("Observed overlap must be finite and nonnegative.")

    def to_dict(self):
        return {**super().to_dict(), "max_observed_overlap": self.max_observed_overlap}


@dataclass(frozen=True)
class RelaxationStatistics(PackingStatistics):
    perturbations: int

    def __post_init__(self):
        super().__post_init__()
        if isinstance(self.perturbations, bool) or not isinstance(self.perturbations, (int, np.integer)) or self.perturbations < 0:
            raise ValueError("Perturbations must be a nonnegative integer.")

    def to_dict(self):
        return {**super().to_dict(), "perturbations": self.perturbations}


@dataclass(frozen=True)
class GrowthStage:
    scale: float
    accepted: bool
    iterations: int
    max_excess: float

    def __post_init__(self):
        if not np.isfinite(self.scale) or self.scale <= 0:
            raise ValueError("Growth scale must be finite and positive.")
        if not isinstance(self.accepted, bool):
            raise ValueError("Growth acceptance must be boolean.")
        if isinstance(self.iterations, bool) or not isinstance(self.iterations, (int, np.integer)) or self.iterations < 0:
            raise ValueError("Growth iterations must be a nonnegative integer.")
        if not np.isfinite(self.max_excess) or self.max_excess < 0:
            raise ValueError("Growth overlap excess must be finite and nonnegative.")

    def to_dict(self):
        return {
            "scale": self.scale,
            "accepted": self.accepted,
            "iterations": self.iterations,
            "max_excess": self.max_excess,
        }


@dataclass(frozen=True)
class GrowthStatistics(RelaxationStatistics):
    final_scale: float
    stages: tuple[GrowthStage, ...]

    def __post_init__(self):
        super().__post_init__()
        if not np.isfinite(self.final_scale) or self.final_scale <= 0:
            raise ValueError("Final growth scale must be finite and positive.")
        if not isinstance(self.stages, tuple) or not self.stages or not all(
            isinstance(stage, GrowthStage) for stage in self.stages
        ):
            raise ValueError("Growth statistics require typed stage records.")

    def to_dict(self):
        return {
            **super().to_dict(),
            "final_scale": self.final_scale,
            "stages": [stage.to_dict() for stage in self.stages],
            "accepted_stages": sum(stage.accepted for stage in self.stages),
            "rejected_stages": sum(not stage.accepted for stage in self.stages),
        }


def packing_statistics_from_dict(method, values):
    common = {"position_draws": values["position_draws"], "iterations": values["iterations"]}
    if method == "random_sequential":
        return InsertionStatistics(**common, max_observed_overlap=values["max_observed_overlap"])
    if method == "overlap_relaxation":
        return RelaxationStatistics(**common, perturbations=values["perturbations"])
    if method == "progressive_growth":
        stages = tuple(GrowthStage(**stage) for stage in values["stages"])
        return GrowthStatistics(
            **common,
            perturbations=values["perturbations"],
            final_scale=values["final_scale"],
            stages=stages,
        )
    raise ValueError(f"Unsupported packing statistics method: {method!r}.")


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
            "ids": _readonly_array(raw_ids, "ids"),
            "positions": _readonly_array(self.positions, "positions", np.float64),
            "radii": _readonly_array(self.radii, "radii", np.float64),
            "velocities": _readonly_array(self.velocities, "velocities", np.float64),
            "angular_velocities": _readonly_array(
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
        relative = self.positions - self.box.origin
        margin = 0 if self.box.periodic else self.radii[:, None]
        epsilon = 16 * np.finfo(float).eps * np.maximum(
            np.abs(self.box.origin) + self.box.lengths, 1e-300
        )
        if np.any(relative < margin - epsilon) or np.any(
            relative > self.box.lengths - margin + epsilon
        ):
            raise ValueError("Particles lie outside their permitted box bounds.")

    @property
    def solid_fraction(self):
        return float(np.sum((4.0 * np.pi / 3.0) * self.radii**3) / self.box.volume)
