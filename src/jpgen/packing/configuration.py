"""Validate packing inputs and resolve defaults before generation starts."""

import secrets
from copy import deepcopy
from dataclasses import dataclass

from ..configuration_values import integer, mapping, number, vector
from ..errors import ConfigurationError
from .distributions import ExplicitDistribution, build_distribution
from .domain import Box
from .placement import PLACEMENT_STRATEGIES, PlacementConstraints, PlacementStrategy
from .sizing import PACKING_SIZING_STRATEGIES, PackingSizingStrategy


@dataclass(frozen=True)
class PackingPlan:
    """Validated packing configuration and executable strategies."""

    config: dict
    sizing_strategy: PackingSizingStrategy
    placement_strategy: PlacementStrategy
    placement_constraints: PlacementConstraints

    def to_config(self):
        result = deepcopy(self.config)
        for field in ("radii", "velocity", "angular_velocity"):
            result[field] = self.config[field].to_config()
        result["box"] = {
            "origin": self.config["box"].origin.tolist(),
            "lengths": self.config["box"].lengths.tolist(),
            "periodic": self.config["box"].periodic,
        }
        placement = self.placement_strategy.to_config()
        method = placement.pop("method")
        result["placement"] = {
            "method": method,
            "max_overlap": self.placement_constraints.max_overlap,
            **placement,
        }
        return result


def build_packing_plan(raw):
    """Build one executable plan from the packing section."""
    cfg = deepcopy(raw)
    if not isinstance(cfg, dict):
        raise ConfigurationError("packing must be a mapping.")
    sizing_method = cfg.get("sizing_method")
    if not isinstance(sizing_method, str) or sizing_method not in PACKING_SIZING_STRATEGIES:
        raise ConfigurationError(
            f"packing.sizing_method must be one of: {', '.join(PACKING_SIZING_STRATEGIES)}."
        )
    sizing_strategy = PACKING_SIZING_STRATEGIES[sizing_method]()
    common_options = {
        "sizing_method", "placement", "solid_fraction_tolerance", "box", "radii", "velocity",
        "angular_velocity", "seed", "restarts", "max_particles",
    }
    mapping(
        cfg,
        "packing",
        common_options | sizing_strategy.config_options,
        {"sizing_method", "box", "radii"},
    )
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
    sizing_strategy.validate_config(cfg)
    placement = cfg.setdefault("placement", {"method": "random_sequential"})
    if not isinstance(placement, dict):
        raise ConfigurationError("packing.placement must be a mapping.")
    method = placement.setdefault("method", "random_sequential")
    if not isinstance(method, str) or method not in PLACEMENT_STRATEGIES:
        raise ConfigurationError(
            f"packing.placement.method must be one of: {', '.join(PLACEMENT_STRATEGIES)}."
        )
    constraints = PlacementConstraints(
        max_overlap=number(placement.get("max_overlap", 0), "placement.max_overlap", 0, 1)
    )
    strategy_config = {key: value for key, value in placement.items() if key != "max_overlap"}
    placement_strategy = PLACEMENT_STRATEGIES[method].from_config(strategy_config)
    del cfg["placement"]
    return PackingPlan(cfg, sizing_strategy, placement_strategy, constraints)
