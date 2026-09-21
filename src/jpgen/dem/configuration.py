"""Validate DEM physics and retain the selected backend in an executable plan."""

import math
from dataclasses import asdict, dataclass

from ..configuration_values import mapping, number, vector
from ..errors import ConfigurationError
from .contacts import build_contact
from .domain import Contact, DemCase, Material, Integration
from .protocol import validate_protocol, maximum_servo_velocity
from .timestep import validate_time_step
from .backends.base import DemBackend


@dataclass(frozen=True)
class DemPlan:
    backend: DemBackend
    material: Material
    contact: Contact
    boundary: str
    gravity: tuple[float, float, float]
    time_step: float
    steps: int
    protocol: dict | None = None
    integration: Integration = Integration()

    def to_config(self):
        return {
            "engine": self.backend.name,
            "backend_options": self.backend.to_config(),
            "material": asdict(self.material), "contact": self.contact.to_config(),
            "integration": asdict(self.integration),
            "boundary": self.boundary, "gravity": list(self.gravity),
            "time_step": self.time_step,
            **({"end_time": self.time_step * self.steps} if self.protocol is None else {"protocol": self.protocol}),
        }

    def validate_box(self, box):
        if box.periodic != (self.boundary == "periodic"):
            raise ConfigurationError("DEM boundary must agree with packing.box.periodic.")
        if self.protocol:
            velocity = maximum_servo_velocity(self.protocol["stages"])
            if velocity and 2 * velocity * self.time_step / min(box.lengths) > 0.01:
                raise ConfigurationError("Stress servo permits more than 1% cell strain per step; "
                                         "reduce time_step or max_velocity.")

    def create_case(self, packing):
        packing.validate()
        self.validate_box(packing.box)
        return DemCase(packing, self.material, self.contact, self.boundary,
                       self.gravity, self.time_step, self.steps, self.protocol, self.integration)


def build_dem_plan(raw, backends=None):
    if backends is None:
        from .backends import DEM_BACKENDS
        backends = DEM_BACKENDS
    mapping(raw, "dem", {"engine", "backend_options", "material", "contact", "boundary",
                         "gravity", "time_step", "end_time", "protocol", "integration"},
            {"engine", "material", "contact", "boundary", "time_step"})
    engine = raw["engine"]
    if not isinstance(engine, str) or engine not in backends:
        raise ConfigurationError(f"dem.engine must be one of: {', '.join(backends)}.")
    material = raw["material"]
    mapping(material, "dem.material", {"density", "young_modulus", "poisson_ratio"},
            {"density", "young_modulus", "poisson_ratio"})
    material = Material(
        number(material["density"], "density", 0, strict_min=True),
        number(material["young_modulus"], "young_modulus", 0, strict_min=True),
        number(material["poisson_ratio"], "poisson_ratio", -1, strict_min=True),
    )
    if material.poisson_ratio >= 0.5:
        raise ConfigurationError("poisson_ratio must be less than 0.5.")
    contact = build_contact(raw["contact"])
    integration_raw = raw.get("integration", {})
    mapping(integration_raw, "dem.integration", {"translation", "rotation"})
    integration = Integration(**integration_raw)
    if any(not isinstance(value, str) or not value for value in (integration.translation, integration.rotation)):
        raise ConfigurationError("Integration schemes must be nonempty strings.")
    boundary = raw["boundary"]
    if boundary not in ("open", "periodic"):
        raise ConfigurationError("dem.boundary must be open or periodic; walls are not yet supported.")
    try:
        dt = validate_time_step(raw["time_step"])
    except ValueError as error:
        raise ConfigurationError(str(error)) from error
    if ("end_time" in raw) == ("protocol" in raw):
        raise ConfigurationError("Specify exactly one of dem.end_time and dem.protocol.")
    protocol = None
    if "protocol" in raw:
        try:
            protocol, steps = validate_protocol(raw["protocol"], dt, boundary)
        except ValueError as error:
            raise ConfigurationError(f"dem.protocol: {error}") from error
    else:
        end = number(raw["end_time"], "dem.end_time", dt)
        ratio = end / dt
        if not math.isfinite(ratio) or ratio > 2**53:
            raise ConfigurationError("DEM step count is too large.")
        steps = round(ratio)
        if not math.isclose(ratio, steps, rel_tol=0, abs_tol=1e-8):
            raise ConfigurationError("dem.end_time must be an integer multiple of dem.time_step.")
    plan = DemPlan(backends[engine](raw.get("backend_options", {})), material, contact,
                   boundary, tuple(vector(raw.get("gravity", [0, 0, 0]), "dem.gravity")), dt, steps, protocol, integration)
    plan.backend.capabilities.validate(plan)
    return plan
