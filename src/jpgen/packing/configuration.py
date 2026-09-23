"""Validate packing inputs and resolve defaults before generation starts."""

import secrets
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from ..configuration_values import integer, mapping, number, vector
from ..errors import ConfigurationError
from .distributions import ExplicitDistribution, build_distribution
from .domain import Box, ParticlePacking
from .exporters import PACKING_EXPORTER_TYPES
from .placement import PLACEMENT_STRATEGIES, PlacementConstraints, PlacementStrategy
from .sizing import PACKING_SIZING_STRATEGIES, PackingSizingStrategy


@dataclass(frozen=True)
class PackingPlan:
    """Validated packing configuration and executable strategies."""

    config: dict
    sizing_strategy: PackingSizingStrategy
    placement_strategy: PlacementStrategy
    placement_constraints: PlacementConstraints
    exports: tuple[str, ...]

    @property
    def seed(self) -> int:
        return self.config["seed"]

    @property
    def box(self) -> Box:
        return self.config["box"]

    def to_pipeline_config(self) -> dict:
        return {"packing": self.to_config()}

    def to_config(self):
        result = deepcopy(self.config)
        for field in ("radii", "velocity", "angular_velocity"):
            result[field] = self.config[field].to_config()
        origin_mode = result.pop("origin_mode", None)
        result["box"] = {
            **({"origin_mode": origin_mode} if origin_mode else {"origin": self.config["box"].origin.tolist()}),
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
        result["exports"] = list(self.exports)
        return result

    def to_packing_config(self):
        """Return only the inputs that define the persisted packing."""
        result = self.to_config()
        del result["exports"]
        return result


@dataclass(frozen=True)
class PackingSourcePlan:
    packing: ParticlePacking
    configuration: dict
    path: Path
    sha256: str
    exports: tuple[str, ...]

    @property
    def seed(self) -> int:
        return self.packing.metadata.seed

    @property
    def box(self) -> Box:
        return self.packing.box

    def to_pipeline_config(self) -> dict:
        return {"packing_source": self.to_config()}

    def to_config(self):
        return {"file": str(self.path), "sha256": self.sha256, "exports": list(self.exports)}


def normalized_exports(raw, available):
    """Validate, normalize and de-duplicate requested export formats."""
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ConfigurationError("exports must be a list of format names.")
    available = tuple(available)
    available_set = set(available)
    result = []
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(
                f"exports entries must be format names; available formats: {', '.join(available)}."
            )
        name = value.strip().lower()
        if name not in available_set:
            raise ConfigurationError(
                f"Unknown packing export format {value!r}; available formats: {', '.join(available)}."
            )
        if name not in result:
            result.append(name)
    return tuple(result)


def build_packing_plan(raw, available_exports=PACKING_EXPORTER_TYPES):
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
        "angular_velocity", "seed", "restarts", "max_particles", "exports",
    }
    mapping(
        cfg,
        "packing",
        common_options | sizing_strategy.config_options,
        {"sizing_method", "box", "radii"},
    )
    exports = normalized_exports(cfg.pop("exports", []), available_exports)
    cfg["solid_fraction_tolerance"] = number(cfg.get("solid_fraction_tolerance", 0.001), "solid_fraction_tolerance", 0)
    cfg["restarts"] = integer(cfg.get("restarts", 10), "restarts", 0)
    cfg["max_particles"] = integer(cfg.get("max_particles", 1_000_000), "max_particles")
    if "seed" not in cfg:
        cfg["seed"] = secrets.randbits(128)
    cfg["seed"] = integer(cfg["seed"], "seed", 0)
    box = cfg["box"]
    mapping(box, "box", {"origin", "origin_mode", "lengths", "periodic"}, {"lengths"})
    if "origin_mode" in box:
        if "origin" in box:
            raise ConfigurationError("box.origin and box.origin_mode cannot be used together.")
        if not isinstance(box["origin_mode"], str) or box["origin_mode"] not in {"center", "minimum_corner"}:
            raise ConfigurationError("box.origin_mode must be center or minimum_corner.")
        cfg["origin_mode"] = box["origin_mode"]
    box["lengths"] = vector(box["lengths"], "box.lengths", positive=True)
    if box.get("origin_mode") == "center":
        box["origin"] = [-length / 2 for length in box["lengths"]]
    elif box.get("origin_mode") == "minimum_corner":
        box["origin"] = [0, 0, 0]
    else:
        box["origin"] = vector(box.get("origin", [0, 0, 0]), "box.origin")
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
    return PackingPlan(cfg, sizing_strategy, placement_strategy, constraints, exports)
