"""Validate YAML values and resolve defaults before generation starts."""

import secrets
from copy import deepcopy
from dataclasses import dataclass

from .configuration_values import ConfigurationError, integer, mapping, number, vector
from .distributions import ExplicitDistribution, build_distribution
from .domain import Box
from .packing import PACKING_STRATEGIES, PackingConstraints, PackingStrategy
from .strategies import GEOMETRY_STRATEGIES, GeometryStrategy


@dataclass(frozen=True)
class GenerationPlan:
    """Validated configuration, packing constraints and executable strategies."""

    config: dict
    geometry_strategy: GeometryStrategy
    packing_strategy: PackingStrategy
    packing_constraints: PackingConstraints

    def to_config(self):
        result = deepcopy(self.config)
        for field in ("radii", "velocity", "angular_velocity"):
            result[field] = self.config[field].to_config()
        result["box"] = {
            "origin": self.config["box"].origin.tolist(),
            "lengths": self.config["box"].lengths.tolist(),
            "periodic": self.config["box"].periodic,
        }
        packing = self.packing_strategy.to_config()
        method = packing.pop("method")
        result["packing"] = {
            "method": method,
            "max_overlap": self.packing_constraints.max_overlap,
            **packing,
        }
        return result


def build_generation_plan(raw):
    """Build one executable plan from the particle-generation section."""
    cfg = deepcopy(raw)
    if not isinstance(cfg, dict):
        raise ConfigurationError("particle_generation must be a mapping.")
    mode = cfg.get("mode")
    if not isinstance(mode, str) or mode not in GEOMETRY_STRATEGIES:
        raise ConfigurationError(f"mode must be one of: {', '.join(GEOMETRY_STRATEGIES)}.")
    strategy = GEOMETRY_STRATEGIES[mode]()
    common_options = {
        "mode", "packing", "solid_fraction_tolerance", "box", "radii", "velocity",
        "angular_velocity", "seed", "restarts", "max_particles",
    }
    mapping(cfg, "particle_generation", common_options | strategy.config_options, {"mode", "box", "radii"})
    cfg["solid_fraction_tolerance"] = number(cfg.get("solid_fraction_tolerance", 0.001), "solid_fraction_tolerance", 0)
    cfg["restarts"] = integer(cfg.get("restarts", 10), "restarts", 0)
    cfg["max_particles"] = integer(cfg.get("max_particles", 1_000_000), "max_particles")
    if "seed" not in cfg:
        cfg["seed"] = secrets.randbits(128)
    cfg["seed"] = integer(cfg["seed"], "seed", 0)
    box = cfg["box"]
    mapping(box, "box", {"origin", "lengths", "periodic"}, {"lengths"})
    box["origin"] = vector(box.get("origin", [0, 0, 0]), "box.origin")
    box["lengths"] = vector(box["lengths"], "box.lengths", positive=True)
    if not isinstance(box.get("periodic", False), bool):
        raise ConfigurationError("box.periodic must be true or false for all three axes.")
    box["periodic"] = box.get("periodic", False)
    cfg["box"] = Box(box["origin"], box["lengths"], box["periodic"])
    cfg["radii"] = build_distribution(cfg["radii"], "radii", positive=True, allow_explicit=True)
    if isinstance(cfg["radii"], ExplicitDistribution):
        size = len(cfg["radii"].values)
        if size > cfg["max_particles"]:
            raise ConfigurationError("Explicit radii must not exceed max_particles.")
    for field in ("velocity", "angular_velocity"):
        cfg[field] = build_distribution(cfg.get(field, {"type": "constant", "value": 0}), field)
    strategy.validate_config(cfg)
    packing = cfg.setdefault("packing", {"method": "random_sequential"})
    if not isinstance(packing, dict):
        raise ConfigurationError("packing must be a mapping.")
    method = packing.setdefault("method", "random_sequential")
    if not isinstance(method, str) or method not in PACKING_STRATEGIES:
        raise ConfigurationError(f"packing.method must be one of: {', '.join(PACKING_STRATEGIES)}.")
    constraints = PackingConstraints(
        max_overlap=number(packing.get("max_overlap", 0), "packing.max_overlap", 0, 1)
    )
    strategy_config = {key: value for key, value in packing.items() if key != "max_overlap"}
    packing_strategy = PACKING_STRATEGIES[method].from_config(strategy_config)
    del cfg["packing"]
    return GenerationPlan(cfg, strategy, packing_strategy, constraints)
