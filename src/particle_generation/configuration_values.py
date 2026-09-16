"""Shared input checks; independent of configuration orchestration and strategies."""

import math


class ConfigurationError(ValueError):
    pass


def mapping(value, name, allowed, required=()):
    if not isinstance(value, dict):
        raise ConfigurationError(f"{name} must be a mapping.")
    unknown = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unknown or missing:
        raise ConfigurationError(f"{name}: unknown keys {sorted(unknown, key=str)}; missing keys {sorted(missing)}.")


def number(value, name, minimum=None, maximum=None, strict_min=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigurationError(f"{name} must be a finite number.")
    if minimum is not None and (value < minimum or (strict_min and value == minimum)):
        raise ConfigurationError(f"{name} must be {'greater than' if strict_min else 'at least'} {minimum}.")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be at most {maximum}.")
    return float(value)


def integer(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigurationError(f"{name} must be an integer >= {minimum}.")
    return value


def vector(value, name, positive=False):
    if not isinstance(value, list) or len(value) != 3:
        raise ConfigurationError(f"{name} must contain three numbers.")
    return [number(v, name, 0 if positive else None, strict_min=positive) for v in value]


