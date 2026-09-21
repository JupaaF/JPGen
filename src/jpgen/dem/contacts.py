"""Portable contact specifications and their model-specific configuration."""
from dataclasses import asdict, dataclass
from typing import Callable

from .domain import Contact

from ..configuration_values import mapping, number
from ..errors import ConfigurationError


@dataclass(frozen=True)
class HertzViscousCoulomb:
    static_friction: float
    dynamic_friction: float
    friction_decay: float
    restitution: float
    model: str = "hertz_viscous_coulomb"

    def to_config(self):
        return asdict(self)

    @classmethod
    def from_config(cls, raw):
        mapping(raw, "dem.contact", {"model", "static_friction", "dynamic_friction", "friction_decay", "restitution"},
                {"model", "static_friction", "dynamic_friction", "restitution"})
        result = cls(number(raw["static_friction"], "static_friction", 0),
                     number(raw["dynamic_friction"], "dynamic_friction", 0),
                     number(raw.get("friction_decay", 500.0), "friction_decay", 0),
                     number(raw["restitution"], "restitution", 0, 1))
        if result.dynamic_friction > result.static_friction:
            raise ConfigurationError("dynamic_friction must not exceed static_friction.")
        return result


@dataclass(frozen=True)
class ContactParameter:
    name: str
    label: str
    default: float
    explanation: str


@dataclass(frozen=True)
class ContactModel:
    label: str
    factory: Callable[[dict], Contact]
    parameters: tuple[ContactParameter, ...]
    semantics: str


CONTACT_MODELS = {
    "hertz_viscous_coulomb": ContactModel(
        "Hertz viscous Coulomb", HertzViscousCoulomb.from_config,
        (
            ContactParameter("static_friction", "Static friction coefficient", 0.5, "Friction at zero slip speed; must be at least dynamic friction."),
            ContactParameter("dynamic_friction", "Dynamic friction coefficient", 0.4, "Nonnegative friction approached at high slip speed."),
            ContactParameter("friction_decay", "Friction decay (s/m)", 500.0, "Exponential transition from static to dynamic friction with slip speed; zero keeps static friction."),
            ContactParameter("restitution", "Coefficient of restitution", 0.8, "Restitution in [0, 1], used to derive viscous contact damping."),
        ),
        "Hertz normal elasticity, restitution-derived viscous damping and tangential elasticity "
        "limited by Coulomb friction; friction transitions exponentially with slip speed. "
        "No rolling resistance or global damping.",
    ),
}


def build_contact(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("model"), str) or raw["model"] not in CONTACT_MODELS:
        raise ConfigurationError(f"dem.contact.model must be one of: {', '.join(CONTACT_MODELS)}.")
    return CONTACT_MODELS[raw["model"]].factory(raw)
