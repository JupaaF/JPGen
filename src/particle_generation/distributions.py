"""Validated, polymorphic particle-property distributions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from .configuration_values import ConfigurationError, mapping, number
from .sampling import GenerationError


class Distribution(ABC):
    kind: ClassVar[str]
    fields: ClassVar[frozenset[str]]

    @classmethod
    @abstractmethod
    def from_config(cls, config, name, positive):
        """Build a validated distribution from its complete mapping."""

    @abstractmethod
    def sample(self, count, rng):
        """Draw ``count`` scalar values."""

    @abstractmethod
    def to_config(self):
        """Return the normalized serializable mapping."""


@dataclass(frozen=True)
class ConstantDistribution(Distribution):
    kind = "constant"
    fields = frozenset({"value"})
    value: float

    @classmethod
    def from_config(cls, config, name, positive):
        return cls(number(config["value"], f"{name}.value", 0, strict_min=positive))

    def sample(self, count, rng):
        return np.full(count, self.value, dtype=np.float64)

    def to_config(self):
        return {"type": self.kind, "value": self.value}


@dataclass(frozen=True)
class UniformDistribution(Distribution):
    kind = "uniform"
    fields = frozenset({"min", "max"})
    minimum: float
    maximum: float

    @classmethod
    def from_config(cls, config, name, positive):
        minimum = number(config["min"], f"{name}.min", 0, strict_min=positive)
        maximum = number(config["max"], f"{name}.max", 0, strict_min=positive)
        if minimum >= maximum:
            raise ConfigurationError(f"{name}.min must be less than max.")
        return cls(minimum, maximum)

    def sample(self, count, rng):
        return rng.uniform(self.minimum, self.maximum, count)

    def to_config(self):
        return {"type": self.kind, "min": self.minimum, "max": self.maximum}


class BoundedDistribution(Distribution):
    minimum: float
    maximum: float

    def sample(self, count, rng):
        result = np.empty(count, dtype=np.float64)
        pending = np.arange(count)
        for _ in range(1000):
            if not len(pending):
                return result
            with np.errstate(over="ignore", invalid="ignore"):
                draws = self._draw(len(pending), rng)
            valid = np.isfinite(draws) & (draws >= self.minimum) & (draws <= self.maximum)
            result[pending[valid]] = draws[valid]
            pending = pending[~valid]
        raise GenerationError(
            "Distribution rejection limit reached (1000 draws per value); revise its parameters or bounds."
        )

    @abstractmethod
    def _draw(self, count, rng):
        """Draw unbounded candidate values."""


@dataclass(frozen=True)
class NormalDistribution(BoundedDistribution):
    kind = "normal"
    fields = frozenset({"mean", "std", "min", "max"})
    mean: float
    std: float
    minimum: float
    maximum: float

    @classmethod
    def from_config(cls, config, name, positive):
        mean = number(config["mean"], f"{name}.mean")
        std = number(config["std"], f"{name}.std", 0, strict_min=True)
        minimum = number(config["min"], f"{name}.min", 0, strict_min=positive)
        maximum = number(config["max"], f"{name}.max", 0, strict_min=positive)
        if minimum >= maximum:
            raise ConfigurationError(f"{name}.min must be less than max.")
        return cls(mean, std, minimum, maximum)

    def _draw(self, count, rng):
        return rng.normal(self.mean, self.std, count)

    def to_config(self):
        return {
            "type": self.kind,
            "mean": self.mean,
            "std": self.std,
            "min": self.minimum,
            "max": self.maximum,
        }


@dataclass(frozen=True)
class LognormalDistribution(BoundedDistribution):
    kind = "lognormal"
    fields = frozenset({"median", "sigma", "min", "max"})
    median: float
    sigma: float
    minimum: float
    maximum: float

    @classmethod
    def from_config(cls, config, name, positive):
        median = number(config["median"], f"{name}.median", 0, strict_min=True)
        sigma = number(config["sigma"], f"{name}.sigma", 0, strict_min=True)
        minimum = number(config["min"], f"{name}.min", 0, strict_min=positive)
        maximum = number(config["max"], f"{name}.max", 0, strict_min=positive)
        if minimum >= maximum:
            raise ConfigurationError(f"{name}.min must be less than max.")
        return cls(median, sigma, minimum, maximum)

    def _draw(self, count, rng):
        return rng.lognormal(np.log(self.median), self.sigma, count)

    def to_config(self):
        return {
            "type": self.kind,
            "median": self.median,
            "sigma": self.sigma,
            "min": self.minimum,
            "max": self.maximum,
        }


@dataclass(frozen=True)
class ExplicitDistribution(Distribution):
    kind = "explicit"
    fields = frozenset({"values"})
    values: tuple[float, ...]

    @classmethod
    def from_config(cls, config, name, positive):
        values = config["values"]
        if not isinstance(values, list) or not values:
            raise ConfigurationError(f"{name}.values must be a nonempty list.")
        return cls(tuple(number(value, name, 0, strict_min=True) for value in values))

    def sample(self, count, rng):
        return np.array(self.values, dtype=np.float64)

    def to_config(self):
        return {"type": self.kind, "values": list(self.values)}


DISTRIBUTIONS = {
    distribution.kind: distribution
    for distribution in (
        ConstantDistribution,
        UniformDistribution,
        NormalDistribution,
        LognormalDistribution,
        ExplicitDistribution,
    )
}


def build_distribution(config, name, *, positive=False, allow_explicit=False):
    if not isinstance(config, dict):
        raise ConfigurationError(f"{name} must be a distribution mapping.")
    kind = config.get("type")
    distribution_type = DISTRIBUTIONS.get(kind) if isinstance(kind, str) else None
    if distribution_type is None or (distribution_type is ExplicitDistribution and not allow_explicit):
        raise ConfigurationError(f"Unsupported distribution for {name}: {kind!r}.")
    mapping(config, name, distribution_type.fields | {"type"}, distribution_type.fields | {"type"})
    return distribution_type.from_config(config, name, positive)
