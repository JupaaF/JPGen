"""Optional DEM configuration using the same declarative wizard questions."""

from ..dem.configuration import build_dem_plan
from .questions import MenuChoice, Question


class DemStageWizard:
    """Collect the supported single-material Kratos case in SI units."""

    name = "dem"

    def questions(self, answers, terminal):
        questions = [Question(
            key="dem.enabled", message="Run DEM after packing?", kind="select", default=False,
            explanation="Kratos must be installed in the active Python environment or in the installation directory entered below.",
            example="Choose packing only to generate geometry without a solver.",
            choices=(MenuChoice("Packing only", False), MenuChoice("Packing and Kratos DEM", True)),
        )]
        values = (
            ("density", "Particle density (kg/m³)", 2500.0),
            ("young_modulus", "Young's modulus (Pa)", 1e7),
            ("poisson_ratio", "Poisson ratio", 0.25),
            ("static_friction", "Static friction coefficient", 0.5),
            ("dynamic_friction", "Dynamic friction coefficient", 0.4),
            ("friction_decay", "Friction decay coefficient (s/m)", 500.0),
            ("restitution", "Coefficient of restitution", 0.8),
            ("time_step", "Fixed time step (s)", 1e-6),
            ("end_time", "Final time (s)", 0.001),
        )
        for key, message, default in values:
            questions.append(Question(
                key="dem." + key, message=message, default=default,
                explanation="SI units. The final time must be an integer multiple of the time step. The step must resolve the contact dynamics; it is not selected automatically.",
                example=str(default), parser=lambda value, _: float(value),
                visible=lambda current: current.get("dem.enabled", False),
            ))
        questions.append(Question(
            key="dem.gravity", message="Gravity X Y Z (m/s²)", default="0 0 0",
            explanation="Constant acceleration. Nonperiodic packing uses open boundaries; no physical walls are created.",
            example="0 0 -9.81", parser=_gravity,
            visible=lambda current: current.get("dem.enabled", False),
        ))
        questions.append(Question(
            key="dem.installation", message="Kratos installation directory (optional)", default="",
            explanation="Directory containing KratosMultiphysics and libs, for example Kratos/bin/Release. Leave empty to use the active environment.",
            example="Kratos/bin/Release", parser=lambda value, _: value.strip() or None,
            visible=lambda current: current.get("dem.enabled", False),
        ))
        return questions

    def build(self, answers):
        if not answers.get("dem.enabled", False):
            return None
        return {
            "engine": "kratos",
            "backend_options": {"installation": answers["dem.installation"]},
            "material": {key: answers["dem." + key] for key in ("density", "young_modulus", "poisson_ratio")},
            "contact": {"model": "hertz_viscous_coulomb", **{
                key: answers["dem." + key] for key in ("static_friction", "dynamic_friction", "friction_decay", "restitution")}},
            "boundary": "periodic" if _packing_is_periodic(answers) else "open",
            "gravity": answers["dem.gravity"],
            "time_step": answers["dem.time_step"], "end_time": answers["dem.end_time"],
        }

    def validate(self, configuration):
        return None if configuration is None else build_dem_plan(configuration).to_config()


def _gravity(value, _answers):
    result = [float(component) for component in value.replace(",", " ").split()]
    if len(result) != 3:
        raise ValueError("Enter three acceleration components.")
    return result


def _packing_is_periodic(answers):
    if answers.get("packing.input") == "source":
        return answers["packing_source.plan"].packing.box.periodic
    return answers["box.periodic"]
