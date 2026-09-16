"""Validate YAML values and resolve defaults before generation starts."""

import math
import secrets
from copy import deepcopy

from .configuration_values import ConfigurationError, integer, mapping, number, vector
from .strategies import GEOMETRY_STRATEGIES


def distribution(value, name, radius=False):
    if not isinstance(value, dict):
        raise ConfigurationError(f"{name} must be a distribution mapping.")
    kind = value.get("type")
    fields = {
        "constant": {"value"}, "uniform": {"min", "max"},
        "normal": {"mean", "std", "min", "max"},
        "lognormal": {"median", "sigma", "min", "max"},
        "explicit": {"values"},
    }
    if not isinstance(kind, str) or kind not in fields or (kind == "explicit" and not radius):
        raise ConfigurationError(f"Unsupported distribution for {name}: {kind!r}.")
    mapping(value, name, fields[kind] | {"type"}, fields[kind] | {"type"})
    result = {"type": kind}
    if kind == "explicit":
        values = value["values"]
        if not isinstance(values, list) or not values:
            raise ConfigurationError(f"{name}.values must be a nonempty list.")
        result["values"] = [number(v, name, 0, strict_min=True) for v in values]
        return result
    for key in fields[kind]:
        # A normal mean may lie outside its truncation interval, including below zero.
        result[key] = number(value[key], f"{name}.{key}", None if key == "mean" else 0,
                             strict_min=(key in {"std", "sigma", "median"} or radius and key in {"value", "min", "max"}))
    if "min" in result and result["min"] >= result["max"]:
        raise ConfigurationError(f"{name}.min must be less than max.")
    return result


def validate_config(raw):
    """Validate only the particle-generation section, not the full YAML document."""
    cfg = deepcopy(raw)
    if not isinstance(cfg, dict):
        raise ConfigurationError("particle_generation must be a mapping.")
    mode = cfg.get("mode")
    if not isinstance(mode, str) or mode not in GEOMETRY_STRATEGIES:
        raise ConfigurationError(f"mode must be one of: {', '.join(GEOMETRY_STRATEGIES)}.")
    strategy = GEOMETRY_STRATEGIES[mode]()
    common_options = {
        "mode", "solid_fraction_tolerance", "box", "radii", "velocity",
        "angular_velocity", "seed", "max_overlap", "position_attempts", "restarts", "max_particles",
    }
    mapping(cfg, "particle_generation", common_options | strategy.config_options, {"mode", "box", "radii"})
    cfg["solid_fraction_tolerance"] = number(cfg.get("solid_fraction_tolerance", 0.001), "solid_fraction_tolerance", 0)
    cfg["max_overlap"] = number(cfg.get("max_overlap", 0), "max_overlap", 0, 1)
    cfg["position_attempts"] = integer(cfg.get("position_attempts", 1000), "position_attempts")
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
    volume = math.prod(box["lengths"])
    if not math.isfinite(volume) or volume <= 0:
        raise ConfigurationError("Box volume must be finite and positive in float64.")
    if any(not math.isfinite(o + l) or o + l == o for o, l in zip(box["origin"], box["lengths"])):
        raise ConfigurationError("Box bounds cannot be represented accurately in float64.")
    cfg["radii"] = distribution(cfg["radii"], "radii", radius=True)
    if cfg["radii"]["type"] == "explicit":
        size = len(cfg["radii"]["values"])
        if size > cfg["max_particles"]:
            raise ConfigurationError("Explicit radii must not exceed max_particles.")
    for field in ("velocity", "angular_velocity"):
        cfg[field] = distribution(cfg.get(field, {"type": "constant", "value": 0}), field)
    strategy.validate_config(cfg)
    return cfg
