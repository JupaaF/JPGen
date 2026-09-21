"""Engine-independent DEM wizard, composed from registered descriptions."""
from ..dem.backends import DEM_BACKENDS
from ..dem.contacts import CONTACT_MODELS
from ..dem.configuration import build_dem_plan
from ..errors import ConfigurationError
from .questions import MenuChoice, Question
from .protocol import protocol_questions, build_protocol
from .timestep import time_step_questions, build_time_step


class DemStageWizard:
    name = "dem"

    def __init__(self, backends=None):
        self.backends = DEM_BACKENDS if backends is None else backends

    def questions(self, answers, terminal):
        questions = [Question(
            key="dem.enabled", message="Run DEM after packing?", kind="select", default=False,
            explanation="Continue with particle motion and contact forces using an available DEM engine.",
            example="Choose packing only to generate geometry without a solver.",
            choices=(MenuChoice("Packing only", False), MenuChoice("Packing and DEM", True)),
        )]
        if not answers.get("dem.enabled", False):
            return questions
        boundary = "periodic" if _packing_is_periodic(answers) else "open"
        available = {name: item for name, item in self.backends.items() if boundary in item.capabilities.boundaries}
        if not available:
            raise ConfigurationError(f"No registered DEM engine supports {boundary} boundaries.")
        questions.append(Question(
            key="dem.engine", message="DEM engine", kind="select", default=next(iter(available)),
            explanation="Choose the engine used to execute the portable physical case.", example="Select an installed engine.",
            choices=tuple(MenuChoice(item.label, name) for name, item in available.items()),
        ))
        if "dem.engine" not in answers:
            return questions
        definition = self.backends[answers["dem.engine"]]
        capabilities = definition.capabilities
        for key, label, default, explanation in (
            ("density", "Particle density (kg/m³)", 2500.0, "Positive material density; sets particle mass and rotational inertia."),
            ("young_modulus", "Young's modulus (Pa)", 1e7, "Positive elastic stiffness; stiffer particles generally require smaller steps."),
            ("poisson_ratio", "Poisson ratio", 0.25, "Elastic material property strictly between -1 and 0.5."),
        ):
            questions.append(Question(key="dem." + key, message=label, default=default,
                                      explanation=explanation, example=str(default), parser=lambda value, _: float(value)))
        models = sorted(capabilities.contact_models & CONTACT_MODELS.keys())
        if not models or not capabilities.integration_schemes:
            raise ConfigurationError("The selected engine needs registered contact models and integration schemes.")
        questions.append(Question(
            key="dem.contact_model", message="Contact model", kind="select", default=models[0],
            explanation=definition.physics, example="Choose the requested contact physics.",
            choices=tuple(MenuChoice(CONTACT_MODELS[name].label, name) for name in models),
        ))
        if "dem.contact_model" not in answers:
            return questions
        model = CONTACT_MODELS[answers["dem.contact_model"]]
        for parameter in model.parameters:
            questions.append(Question(
                key="dem.contact." + parameter.name, message=parameter.label, default=parameter.default,
                explanation=parameter.explanation, example=str(parameter.default), parser=lambda value, _: float(value),
            ))
        schemes = sorted(capabilities.integration_schemes)
        questions.append(Question(
            key="dem.integration", message="Translation / rotation integration", kind="select", default=schemes[0],
            explanation="Choose an integration pair supported by this engine.", example=" / ".join(schemes[0]),
            choices=tuple(MenuChoice(" / ".join(pair), pair) for pair in schemes),
        ))
        questions.extend(time_step_questions(answers, adaptive_supported=capabilities.adaptive_time_step))
        questions.append(Question(
            key="dem.gravity", message="Gravity X Y Z (m/s²)", default="0 0 0",
            explanation="Constant acceleration applied to every particle in SI units.", example="0 0 -9.81", parser=_gravity,
        ))
        questions.extend(definition.wizard_provider().questions(answers))
        questions.extend(protocol_questions(answers, _packing_is_periodic(answers), capabilities))
        return questions

    def build(self, answers):
        if not answers.get("dem.enabled", False):
            return None
        engine = answers["dem.engine"]
        model = answers["dem.contact_model"]
        translation, rotation = answers["dem.integration"]
        return {
            "engine": engine,
            "backend_options": self.backends[engine].wizard_provider().build(answers),
            "material": {key: answers["dem." + key] for key in ("density", "young_modulus", "poisson_ratio")},
            "contact": {"model": model, **{p.name: answers["dem.contact." + p.name] for p in CONTACT_MODELS[model].parameters}},
            "integration": {"translation": translation, "rotation": rotation},
            "boundary": "periodic" if _packing_is_periodic(answers) else "open",
            "gravity": answers["dem.gravity"], "time_step": build_time_step(answers),
            **({"end_time": answers["dem.end_time"]} if answers.get("dem.execution", "time") == "time" else
               {"protocol": answers["dem.protocol_file"] if answers["dem.execution"] == "file" else build_protocol(answers)}),
        }

    def validate(self, configuration):
        return None if configuration is None else build_dem_plan(configuration, self.backends).to_config()


def _gravity(value, _answers):
    result = [float(component) for component in value.replace(",", " ").split()]
    if len(result) != 3:
        raise ValueError("Enter three acceleration components.")
    return result


def _packing_is_periodic(answers):
    if answers.get("packing.input") == "source":
        return answers["packing_source.plan"].packing.box.periodic
    return answers["box.periodic"]
