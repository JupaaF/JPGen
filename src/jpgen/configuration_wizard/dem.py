"""Optional DEM configuration using the same declarative wizard questions."""

from ..dem.configuration import build_dem_plan
from .questions import MenuChoice, Question
from .protocol import protocol_questions, build_protocol


class DemStageWizard:
    """Collect the supported single-material Kratos case in SI units."""

    name = "dem"

    def questions(self, answers, terminal):
        questions = [Question(
            key="dem.enabled", message="Run DEM after packing?", kind="select", default=False,
            explanation="Choose whether to stop after generating the packing or continue with particle motion and contact forces in a DEM simulation. DEM requires an available Kratos installation.",
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
        )
        explanations = {
            'density': 'Mass per unit volume of the particle material, not the bulk density of the packing. Together with each radius, this sets particle mass and rotational inertia. Must be positive.',
            'young_modulus': 'Elastic stiffness of the particle material. A larger value produces stronger contact forces for the same overlap and generally requires a smaller time step. Must be positive.',
            'poisson_ratio': "Dimensionless elastic material property used together with Young's modulus to calculate contact stiffness. Must be greater than -1 and less than 0.5.",
            'static_friction': 'Dimensionless friction coefficient at zero sliding speed. It sets the low-speed tangential friction limit relative to the normal contact force. Must be at least the dynamic friction coefficient.',
            'dynamic_friction': 'Dimensionless friction coefficient approached at high sliding speeds. Must be nonnegative and no greater than the static friction coefficient.',
            'friction_decay': 'Controls how quickly the friction coefficient decreases from its static value toward its dynamic value as sliding speed increases. Larger values give a faster transition; zero keeps the static coefficient. Must be nonnegative.',
            'restitution': 'Dimensionless coefficient controlling contact damping and rebound. Values closer to 1 represent more elastic collisions; values closer to 0 represent more dissipative collisions. Enter a value from 0 to 1.',
            'time_step': 'Physical time advanced by each DEM integration step, in seconds. Choose a positive value small enough to resolve particle contacts; smaller or stiffer particles generally require smaller steps. JPGen does not select it automatically.',
        }
        for key, message, default in values:
            questions.append(Question(
                key="dem." + key, message=message, default=default,
                explanation=explanations[key],
                example=str(default), parser=lambda value, _: float(value),
                visible=lambda current: current.get("dem.enabled", False),
            ))
        questions.append(Question(
            key="dem.gravity", message="Gravity X Y Z (m/s²)", default="0 0 0",
            explanation="Constant acceleration applied to every particle. Enter the X, Y and Z components in m/s²; the signs set the direction. Use 0 0 0 to disable gravity.",
            example="0 0 -9.81", parser=_gravity,
            visible=lambda current: current.get("dem.enabled", False),
        ))
        questions.append(Question(
            key="dem.installation", message="Kratos installation directory (optional)", default="",
            explanation="Directory containing KratosMultiphysics and libs, for example Kratos/bin/Release. Leave empty to use the active environment.",
            example="Kratos/bin/Release", parser=lambda value, _: value.strip() or None,
            visible=lambda current: current.get("dem.enabled", False),
        ))
        if answers.get("dem.enabled", False):
            questions.extend(protocol_questions(answers, _packing_is_periodic(answers)))
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
            "time_step": answers["dem.time_step"],
            **({"end_time": answers["dem.end_time"]} if answers.get("dem.execution", "time") == "time" else
               {"protocol": answers["dem.protocol_file"] if answers["dem.execution"] == "file" else build_protocol(answers)}),
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
