"""Strategies for preparing a box and radii, independent of particle placement."""

from abc import ABC, abstractmethod

import numpy as np

from .configuration_values import ConfigurationError, integer, number
from .distributions import ExplicitDistribution
from .domain import Box
from .sampling import GenerationError

VOLUME_FACTOR = 4.0 * np.pi / 3.0


def _validate_count(config):
    config["count"] = integer(config.get("count"), "count")
    if config["count"] > config["max_particles"]:
        raise ConfigurationError("count exceeds max_particles.")
    if isinstance(config["radii"], ExplicitDistribution) and len(config["radii"].values) != config["count"]:
        raise ConfigurationError("Explicit radii must match count.")


def _validate_target_fraction(config):
    config["target_solid_fraction"] = number(
        config.get("target_solid_fraction"), "target_solid_fraction", 0, strict_min=True)
    if config["solid_fraction_tolerance"] >= config["target_solid_fraction"]:
        raise ConfigurationError("solid_fraction_tolerance must be smaller than target_solid_fraction.")


def _box_from_config(cfg):
    return Box(np.array(cfg["box"]["origin"], dtype=np.float64),
               np.array(cfg["box"]["lengths"], dtype=np.float64), cfg["box"]["periodic"])


def solid_volume(radii):
    """Return total sphere volume, rejecting invalid numerical values."""
    with np.errstate(over="ignore", under="ignore"):
        volumes = VOLUME_FACTOR * radii**3
        total = float(np.sum(volumes))
    if not len(radii) or not np.all(np.isfinite(volumes)) or np.any(volumes <= 0) or not np.isfinite(total):
        raise GenerationError("Particle volumes must be finite and positive in float64.")
    return total


class GeometryStrategy(ABC):
    """Stateless preparation using validated inputs and the supplied random stream.

    prepare() must return fresh geometry without mutating config or owning RNG state.
    Raise GenerationError when an attempt cannot produce feasible geometry.
    """

    # Additional accepted fields beyond the shared generation configuration.
    config_options: frozenset[str] = frozenset()

    @abstractmethod
    def validate_config(self, config: dict) -> None:
        """Normalize mode-specific fields in the coordinator's private config copy.

        Shared validation has already completed. Do not call super() or use RNGs.
        Raise ConfigurationError for invalid mode-specific inputs.
        """

    @abstractmethod
    def prepare(self, config: dict, rng: np.random.Generator) -> tuple[Box, np.ndarray]:
        """Return the final box and radii before any particle is placed."""


class FixedCount(GeometryStrategy):
    config_options = frozenset({"count"})

    def validate_config(self, config):
        _validate_count(config)

    def prepare(self, config, rng):
        return _box_from_config(config), config["radii"].sample(config["count"], rng)


class FixedBoxFraction(GeometryStrategy):
    config_options = frozenset({"target_solid_fraction"})

    def validate_config(self, config):
        _validate_target_fraction(config)

    def prepare(self, config, rng):
        box = _box_from_config(config)
        return box, _radii_for_fraction(config, rng, box.volume)


class VariableBoxFraction(GeometryStrategy):
    config_options = frozenset({"count", "target_solid_fraction"})

    def validate_config(self, config):
        _validate_count(config)
        _validate_target_fraction(config)

    def prepare(self, config, rng):
        box = _box_from_config(config)
        radii = config["radii"].sample(config["count"], rng)
        scale = (solid_volume(radii) / config["target_solid_fraction"] / box.volume) ** (1.0 / 3.0)
        return Box(box.origin, box.lengths * scale, box.periodic), radii


GEOMETRY_STRATEGIES = {
    "fixed_count": FixedCount,
    "fixed_box_fraction": FixedBoxFraction,
    "variable_box_fraction": VariableBoxFraction,
}


def _radii_for_fraction(cfg, rng, volume):
    spec = cfg["radii"]
    if isinstance(spec, ExplicitDistribution):
        return spec.sample(cfg.get("count", len(spec.values)), rng)
    target = cfg["target_solid_fraction"] * volume
    tolerance = cfg["solid_fraction_tolerance"] * volume
    # Keep an unmodified prefix of the sampled distribution; never shrink the last sphere.
    chunks = []
    total = 0.0
    size = 0
    while size < cfg["max_particles"]:
        draws = spec.sample(min(4096, cfg["max_particles"] - size), rng)
        volumes = VOLUME_FACTOR * draws**3
        if not np.all(np.isfinite(volumes)) or np.any(volumes <= 0):
            raise GenerationError("Particle volumes must be finite and positive in float64.")
        cumulative = total + np.cumsum(volumes)
        crossing = int(np.searchsorted(cumulative, target))
        if crossing < len(draws):
            choices = [(abs(cumulative[crossing] - target), crossing + 1)]
            if size + crossing > 0:
                before = cumulative[crossing - 1] if crossing else total
                choices.append((abs(before - target), crossing))
            error, take = min(choices)
            if error > tolerance:
                raise GenerationError("Discrete particle volumes cannot reach the target within its tolerance for this sample.")
            chunks.append(draws[:take])
            return np.concatenate(chunks)
        chunks.append(draws)
        total = float(cumulative[-1])
        size += len(draws)
        if abs(total - target) <= tolerance:
            return np.concatenate(chunks)
    raise GenerationError("Target requires more than max_particles; increase the limit or revise the target.")
