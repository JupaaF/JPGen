"""Unit choices and SI conversion for wizard input."""

import math

from .questions import MenuChoice


LENGTH_FACTORS = {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "µm": 1e-6}
SPEED_FACTORS = {"m/s": 1.0, "cm/s": 1e-2, "mm/s": 1e-3}
ANGULAR_SPEED_FACTORS = {
    "rad/s": 1.0,
    "deg/s": math.pi / 180.0,
    "rpm": 2.0 * math.pi / 60.0,
}


def unit_choices(factors):
    return tuple(MenuChoice(unit, unit) for unit in factors)


def to_si(value, unit, factors):
    return float(value) * factors[unit]


def from_si(value, unit, factors):
    return float(value) / factors[unit]


def display_number(value):
    return f"{float(value):.17g}"
