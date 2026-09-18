"""Questions and configuration assembly for the packing stage."""

import math
import re
import secrets
from dataclasses import replace

from ..packing.application import PackingApplication
from ..packing.exporters import build_packing_exporters
from ..packing.generator import PackingGenerator
from ..packing.persistence import Hdf5PackingStore
from .questions import MenuChoice, Question
from .units import (
    ANGULAR_SPEED_FACTORS,
    LENGTH_FACTORS,
    SPEED_FACTORS,
    display_number,
    from_si,
    to_si,
    unit_choices,
)

SIZING_CHOICES = (
    MenuChoice("Fixed count — keep the requested particle count and box dimensions", "fixed_count"),
    MenuChoice("Fixed box fraction — infer the particle count for a fixed box", "fixed_box_fraction"),
    MenuChoice("Variable box fraction — scale a reference box for a fixed count", "variable_box_fraction"),
)

PLACEMENT_CHOICES = (
    MenuChoice("Random sequential — fast insertion, best for loose packings", "random_sequential"),
    MenuChoice("Overlap relaxation — iteratively removes excessive overlap", "overlap_relaxation"),
    MenuChoice("Progressive growth — grows particles in stages for dense packings", "progressive_growth"),
)

DISTRIBUTION_CHOICES = (
    MenuChoice("Constant — every particle receives the same magnitude", "constant"),
    MenuChoice("Uniform — sample evenly between minimum and maximum", "uniform"),
    MenuChoice("Normal — bounded Gaussian distribution", "normal"),
    MenuChoice("Lognormal — bounded lognormal distribution", "lognormal"),
)

VECTOR_MODE_CHOICES = (
    MenuChoice("One line — enter X, Y and Z together", "vector"),
    MenuChoice("Components — answer separate X, Y and Z questions", "components"),
)

PACKING_INPUT_CHOICES = (
    MenuChoice("Generate a new packing", "generate"),
    MenuChoice("Reuse an existing packing.h5", "source"),
)

EXPORT_CHOICES = (
    MenuChoice("VTK — particles.vtp for visualization", "vtk"),
    MenuChoice("Kratos — particlesDEM.mdpa", "kratos"),
)


class PackingStageWizard:
    """Collect and validate every option owned by the packing stage."""

    name = "packing"

    def __init__(self, source_application=None):
        self.source_application = source_application or PackingApplication(
            generator=PackingGenerator(),
            store=Hdf5PackingStore(),
            exporters=build_packing_exporters(),
        )

    def section_name(self, answers):
        return "packing_source" if answers["packing.input"] == "source" else "packing"

    def questions(self, answers, terminal):
        return self._questions(answers, terminal)

    def build(self, answers):
        return self._build_configuration(answers)

    def validate(self, configuration):
        if "file" in configuration:
            return self.source_application.build_source_plan(configuration).to_config()
        return self.source_application.build_plan(configuration).to_config()

    def _questions(self, _answers, terminal):
        questions = [
            _select(
                "units.length",
                "Select the length unit",
                "Sets the unit used while entering box coordinates, dimensions and particle radii. Values are converted to metres in YAML.",
                "mm",
                unit_choices(LENGTH_FACTORS),
                default="m",
            ),
            _select(
                "units.velocity",
                "Select the linear velocity unit",
                "Sets the unit used for initial particle speed magnitudes. Values are converted to metres per second in YAML.",
                "cm/s",
                unit_choices(SPEED_FACTORS),
                default="m/s",
            ),
            _select(
                "units.angular_velocity",
                "Select the angular velocity unit",
                "Sets the unit used for initial angular speed magnitudes. Values are converted to radians per second in YAML.",
                "rpm",
                unit_choices(ANGULAR_SPEED_FACTORS),
                default="rad/s",
            ),
            _select(
                "sizing_method",
                "Select the packing sizing method",
                "Controls which quantities remain fixed when JPGen determines the particle population and final box.",
                "Choose fixed_count to generate exactly 8000 particles in the entered box.",
                SIZING_CHOICES,
            ),
            _integer_question(
                "max_particles",
                "Maximum particle count",
                "Safety limit that prevents sizing from producing an unexpectedly large population.",
                "1000000",
                default=1_000_000,
            ),
            _integer_question(
                "count",
                "Particle count",
                "Exact number of particles. Variable-box sizing keeps this count while scaling the reference box.",
                "8000",
                visible=lambda a: a.get("sizing_method") in {"fixed_count", "variable_box_fraction"},
                validator=lambda value, a: _require_at_most(value, a["max_particles"], "count", "max_particles"),
            ),
            _number_question(
                "solid_fraction_tolerance",
                "Solid-fraction tolerance",
                "Absolute allowed error when a sizing method targets a solid fraction.",
                "0.001",
                default=0.001,
                minimum=0,
            ),
            _number_question(
                "target_solid_fraction",
                "Target solid fraction",
                "Requested nominal sphere volume divided by box volume. It must be greater than the configured tolerance.",
                "0.62",
                minimum=0,
                strict_minimum=True,
                visible=lambda a: a.get("sizing_method") in {"fixed_box_fraction", "variable_box_fraction"},
                validator=lambda value, a: _require_greater(
                    value, a["solid_fraction_tolerance"], "target_solid_fraction", "solid_fraction_tolerance"
                ),
            ),
            _integer_question(
                "restarts",
                "Packing restarts",
                "Number of complete retries after the initial generation attempt fails.",
                "10",
                default=10,
                minimum=0,
            ),
            Question(
                key="seed",
                message="Random seed (leave empty to generate one now)",
                explanation="Makes sampling and placement reproducible. A blank answer creates a 128-bit seed using the same secure generator as JPGen.",
                example="20260916",
                parser=_optional_nonnegative_integer,
                after_answer=lambda value, _a: self._resolve_seed(value, terminal),
            ),
            _select(
                "box.origin.mode",
                "How would you like to enter the box origin?",
                "Chooses whether the three origin coordinates are entered together or one component at a time.",
                "One line: 0, 0, 0",
                VECTOR_MODE_CHOICES,
                default="vector",
            ),
            _vector_question(
                "box.origin",
                "Box origin (X, Y, Z)",
                "Coordinates of the minimum box corner in the selected length unit.",
                "0, 0, 0",
                "units.length",
                LENGTH_FACTORS,
                default="0, 0, 0",
                visible=lambda a: a.get("box.origin.mode") == "vector",
            ),
        ]
        questions.extend(
            _component_questions(
                "box.origin",
                "Box origin",
                "Coordinate of the minimum box corner",
                "units.length",
                LENGTH_FACTORS,
                default_si=0,
                visible=lambda a: a.get("box.origin.mode") == "components",
            )
        )
        questions.extend(
            [
                _select(
                    "box.lengths.mode",
                    "How would you like to enter the box lengths?",
                    "Chooses whether the three positive side lengths are entered together or one component at a time.",
                    "One line: 0.1, 0.1, 0.1",
                    VECTOR_MODE_CHOICES,
                    default="vector",
                ),
                _vector_question(
                    "box.lengths",
                    "Box lengths (X, Y, Z)",
                    "Positive box dimensions. For variable-box sizing these are reference proportions and are scaled uniformly.",
                    "0.1, 0.1, 0.1",
                    "units.length",
                    LENGTH_FACTORS,
                    positive=True,
                    visible=lambda a: a.get("box.lengths.mode") == "vector",
                ),
            ]
        )
        questions.extend(
            _component_questions(
                "box.lengths",
                "Box length",
                "Positive side length",
                "units.length",
                LENGTH_FACTORS,
                positive=True,
                visible=lambda a: a.get("box.lengths.mode") == "components",
            )
        )
        questions.append(
            _select(
                "box.periodic",
                "Should the box be periodic on all axes?",
                "Periodic boxes wrap particle interactions across every pair of opposite faces.",
                "false keeps complete spheres inside the box walls.",
                (MenuChoice("No", False), MenuChoice("Yes", True)),
                default=False,
            )
        )
        questions.extend(self._distribution_questions("radii", "Particle radius", "units.length", LENGTH_FACTORS, True))
        questions.extend(self._distribution_questions("velocity", "Initial linear speed", "units.velocity", SPEED_FACTORS, False))
        questions.extend(
            self._distribution_questions(
                "angular_velocity", "Initial angular speed", "units.angular_velocity", ANGULAR_SPEED_FACTORS, False
            )
        )
        questions.extend(self._placement_questions())
        generation_questions = [
            replace(
                question,
                visible=lambda answers, visible=question.visible: (
                    answers.get("packing.input") == "generate" and visible(answers)
                ),
            )
            for question in questions
        ]
        return [
            _select(
                "packing.input",
                "Select the packing input",
                "Generate a new particle packing or reuse a validated JPGen packing.h5 file.",
                "Choose reuse to start from particles stored by an earlier run.",
                PACKING_INPUT_CHOICES,
                default="generate",
            ),
            Question(
                key="packing_source.plan",
                message="Path to packing.h5",
                explanation="Existing JPGen packing file. The wizard resolves its absolute path, validates it and records its SHA-256.",
                example="runs/20260918T120000_000000Z_example/packing.h5",
                parser=lambda value, _answers: self._source_plan(value),
                visible=lambda answers: answers.get("packing.input") == "source",
            ),
            Question(
                key="packing.exports",
                message="Select additional packing export formats",
                explanation="packing.h5 is always saved. Leave every option unchecked to create no additional packing exports.",
                example="Select VTK for ParaView and/or Kratos for a standalone MDPA export.",
                kind="checkbox",
                default=[],
                choices=EXPORT_CHOICES,
            ),
            *generation_questions,
        ]

    def _distribution_questions(self, prefix, label, unit_key, factors, allow_explicit):
        choices = DISTRIBUTION_CHOICES
        if allow_explicit:
            choices += (MenuChoice("Explicit — provide every particle radius", "explicit"),)
        default_type = None if allow_explicit else "constant"
        result = [
            _select(
                f"{prefix}.type",
                f"Select the {label.lower()} distribution",
                f"Controls how the {label.lower()} magnitude is assigned to particles.",
                "uniform samples between a minimum and maximum.",
                choices,
                default=default_type,
            )
        ]
        for field in ("value", "mean", "std", "median", "sigma", "min", "max"):
            kinds = {
                "value": {"constant"},
                "mean": {"normal"},
                "std": {"normal"},
                "median": {"lognormal"},
                "sigma": {"lognormal"},
                "min": {"uniform", "normal", "lognormal"},
                "max": {"uniform", "normal", "lognormal"},
            }[field]
            dimensionless = field == "sigma"
            positive = field in {"std", "median", "sigma"} or (
                prefix == "radii" and field in {"value", "min", "max"}
            )
            minimum = 0 if positive or (prefix != "radii" and field in {"value", "min", "max"}) else None
            strict = positive
            explanation = _distribution_explanation(label, field)
            question = _number_question(
                f"{prefix}.{field}",
                f"{label} {field}",
                explanation,
                _distribution_example(prefix, field),
                default=lambda a, prefix=prefix, field=field, dimensionless=dimensionless: (
                    display_number(_distribution_default(prefix, a[f"{prefix}.type"], field))
                    if dimensionless
                    else display_number(
                        from_si(
                            _distribution_default(prefix, a[f"{prefix}.type"], field),
                            a[unit_key],
                            factors,
                        )
                    )
                ),
                minimum=minimum,
                strict_minimum=strict,
                converter=None if dimensionless else lambda value, a: to_si(value, a[unit_key], factors),
                visible=lambda a, kinds=kinds, prefix=prefix: a.get(f"{prefix}.type") in kinds,
                validator=_maximum_distribution_validator(prefix) if field == "max" else None,
            )
            result.append(question)
        if allow_explicit:
            result.append(
                Question(
                    key=f"{prefix}.values",
                    message=f"Explicit {label.lower()} values",
                    explanation="Complete nonempty radius list. Its length must match count when the selected sizing method fixes a count.",
                    example="0.001, 0.0015, 0.002",
                    parser=lambda text, a: _parse_explicit_radii(text, a, unit_key, factors),
                    visible=lambda a, prefix=prefix: a.get(f"{prefix}.type") == "explicit",
                )
            )
        return result

    def _placement_questions(self):
        relaxation = lambda a: a.get("placement.method") in {"overlap_relaxation", "progressive_growth"}
        growth = lambda a: a.get("placement.method") == "progressive_growth"
        return [
            _select(
                "placement.method",
                "Select the particle placement method",
                "Chooses the geometric algorithm used to position the generated spheres.",
                "random_sequential is suitable for relatively loose packings.",
                PLACEMENT_CHOICES,
                default="random_sequential",
            ),
            _number_question(
                "placement.max_overlap",
                "Maximum relative overlap",
                "Largest permitted normalized overlap between particles, from 0 (none) to 1.",
                "0.005",
                default=0,
                minimum=0,
                maximum=1,
            ),
            _integer_question(
                "placement.position_attempts",
                "Position attempts per particle",
                "Maximum random positions tried before sequential insertion declares an attempt unsuccessful.",
                "1000",
                default=1000,
                visible=lambda a: a.get("placement.method") == "random_sequential",
            ),
            _integer_question(
                "placement.max_iterations",
                "Maximum relaxation iterations",
                "Iteration limit for each overlap-relaxation operation.",
                "3000",
                default=3000,
                visible=relaxation,
            ),
            _number_question(
                "placement.step_size",
                "Relaxation step size",
                "Multiplier applied to each geometric overlap correction.",
                "1.0",
                default=1.0,
                minimum=0,
                maximum=1,
                strict_minimum=True,
                visible=relaxation,
            ),
            _number_question(
                "placement.max_displacement",
                "Maximum displacement",
                "Caps one relaxation displacement as a fraction of particle radius.",
                "0.2",
                default=0.2,
                minimum=0,
                maximum=1,
                strict_minimum=True,
                visible=relaxation,
            ),
            _select(
                "placement.relax_all_overlaps",
                "Should relaxation act on every overlap?",
                "Yes pushes every overlapping pair towards zero overlap while any pair exceeds the permitted limit. No corrects only the excess above max_overlap.",
                "true usually distributes particles more evenly before convergence.",
                (MenuChoice("Yes", True), MenuChoice("No", False)),
                default=True,
                visible=relaxation,
            ),
            _integer_question(
                "placement.stagnation_iterations",
                "Stagnation iteration limit",
                "Iterations without sufficient improvement before a perturbation is attempted.",
                "200",
                default=200,
                visible=relaxation,
            ),
            _number_question(
                "placement.improvement_tolerance",
                "Improvement tolerance",
                "Minimum relative energy improvement considered meaningful during relaxation.",
                "0.000001",
                default=1e-6,
                minimum=0,
                maximum=1,
                strict_minimum=True,
                visible=relaxation,
            ),
            _integer_question(
                "placement.max_perturbations",
                "Maximum perturbations",
                "Number of seeded random perturbations allowed when relaxation stagnates.",
                "3",
                default=3,
                minimum=0,
                visible=relaxation,
            ),
            _number_question(
                "placement.perturbation",
                "Perturbation magnitude",
                "Random perturbation magnitude as a fraction of each particle radius.",
                "0.01",
                default=0.01,
                minimum=0,
                maximum=1,
                strict_minimum=True,
                visible=relaxation,
            ),
            _number_question(
                "placement.overlap_tolerance",
                "Overlap convergence tolerance",
                "Maximum numerical overlap excess accepted as convergence.",
                "0.00000001",
                default=1e-8,
                minimum=0,
                maximum=1,
                strict_minimum=True,
                visible=relaxation,
            ),
            _number_question(
                "placement.initial_scale",
                "Initial particle scale",
                "Starting radius scale for progressive growth; it must be smaller than 1.",
                "0.25",
                default=0.25,
                minimum=0,
                maximum=1,
                strict_minimum=True,
                strict_maximum=True,
                visible=growth,
            ),
            _number_question(
                "placement.min_increment",
                "Minimum growth increment",
                "Smallest allowed increase in particle radius scale.",
                "0.0001",
                default=0.0001,
                minimum=0,
                maximum=1,
                strict_minimum=True,
                visible=growth,
            ),
            _number_question(
                "placement.initial_increment",
                "Initial growth increment",
                "First increase in radius scale; it cannot be smaller than the minimum increment.",
                "0.05",
                default=0.05,
                minimum=0,
                maximum=1,
                strict_minimum=True,
                visible=growth,
                validator=lambda value, a: _require_at_least(
                    value, a["placement.min_increment"], "initial_increment", "min_increment"
                ),
            ),
            _number_question(
                "placement.max_increment",
                "Maximum growth increment",
                "Largest adaptive increase in radius scale; it cannot be smaller than the initial increment.",
                "0.1",
                default=0.1,
                minimum=0,
                maximum=1,
                strict_minimum=True,
                visible=growth,
                validator=lambda value, a: _require_at_least(
                    value, a["placement.initial_increment"], "max_increment", "initial_increment"
                ),
            ),
            _integer_question(
                "placement.max_stages",
                "Maximum growth stages",
                "Limit on accepted and rejected progressive-growth stages.",
                "200",
                default=200,
                visible=growth,
            ),
        ]

    def _resolve_seed(self, value, terminal):
        if value is not None:
            return value
        value = secrets.randbits(128)
        terminal.print(f"Generated seed: {value}", style="bold")
        return value

    def _build_configuration(self, answers):
        exports = answers["packing.exports"]
        if answers["packing.input"] == "source":
            plan = answers["packing_source.plan"]
            return {
                "file": str(plan.path),
                "sha256": plan.sha256,
                "exports": exports,
            }
        packing = {
            "sizing_method": answers["sizing_method"],
            "seed": answers["seed"],
            "box": {
                "origin": _vector_from_answers(answers, "box.origin"),
                "lengths": _vector_from_answers(answers, "box.lengths"),
                "periodic": answers["box.periodic"],
            },
            "radii": _distribution_from_answers(answers, "radii"),
            "restarts": answers["restarts"],
            "max_particles": answers["max_particles"],
            "solid_fraction_tolerance": answers["solid_fraction_tolerance"],
            "velocity": _distribution_from_answers(answers, "velocity"),
            "angular_velocity": _distribution_from_answers(answers, "angular_velocity"),
            "exports": exports,
        }
        if answers["sizing_method"] in {"fixed_count", "variable_box_fraction"}:
            packing["count"] = answers["count"]
        if answers["sizing_method"] in {"fixed_box_fraction", "variable_box_fraction"}:
            packing["target_solid_fraction"] = answers["target_solid_fraction"]
        method = answers["placement.method"]
        placement = {
            "method": method,
            "max_overlap": answers["placement.max_overlap"],
        }
        if method == "random_sequential":
            placement["position_attempts"] = answers["placement.position_attempts"]
        else:
            for field in (
                "max_iterations", "step_size", "max_displacement", "stagnation_iterations",
                "improvement_tolerance", "max_perturbations", "perturbation", "overlap_tolerance",
                "relax_all_overlaps",
            ):
                placement[field] = answers[f"placement.{field}"]
            if method == "progressive_growth":
                for field in ("initial_scale", "initial_increment", "min_increment", "max_increment", "max_stages"):
                    placement[field] = answers[f"placement.{field}"]
        packing["placement"] = placement
        return packing

    def _source_plan(self, value):
        path = value.strip()
        if not path:
            raise ValueError("Enter a path to packing.h5.")
        try:
            return self.source_application.build_source_plan({"file": path})
        except (OSError, ValueError, KeyError) as error:
            raise ValueError(f"Cannot load packing source: {error}") from error


def _select(key, message, explanation, example, choices, default=None, visible=lambda _a: True):
    return Question(key, message, explanation, example, "select", default, choices, visible=visible)


def _number_question(
    key,
    message,
    explanation,
    example,
    *,
    default=None,
    minimum=None,
    maximum=None,
    strict_minimum=False,
    strict_maximum=False,
    converter=None,
    visible=lambda _a: True,
    validator=None,
):
    def parse(text, answers):
        value = _finite_number(text)
        if minimum is not None and (value < minimum or (strict_minimum and value == minimum)):
            relation = "greater than" if strict_minimum else "at least"
            raise ValueError(f"Value must be {relation} {minimum}.")
        if maximum is not None and (value > maximum or (strict_maximum and value == maximum)):
            relation = "less than" if strict_maximum else "at most"
            raise ValueError(f"Value must be {relation} {maximum}.")
        converted = converter(value, answers) if converter else value
        if validator:
            validator(converted, answers)
        return converted

    return Question(key, message, explanation, example, default=default, parser=parse, visible=visible)


def _integer_question(
    key,
    message,
    explanation,
    example,
    *,
    default=None,
    minimum=1,
    visible=lambda _a: True,
    validator=None,
):
    def parse(text, answers):
        value = _integer(text)
        if value < minimum:
            raise ValueError(f"Value must be an integer greater than or equal to {minimum}.")
        if validator:
            validator(value, answers)
        return value

    return Question(key, message, explanation, example, default=default, parser=parse, visible=visible)


def _vector_question(
    key,
    message,
    explanation,
    example,
    unit_key,
    factors,
    *,
    default=None,
    positive=False,
    visible=lambda _a: True,
):
    def parse(text, answers):
        values = _number_list(text)
        if len(values) != 3:
            raise ValueError("Enter exactly three numbers separated by spaces or commas.")
        if positive and any(value <= 0 for value in values):
            raise ValueError("All three values must be greater than zero.")
        return [to_si(value, answers[unit_key], factors) for value in values]

    return Question(key, message, explanation, example, default=default, parser=parse, visible=visible)


def _component_questions(
    prefix,
    label,
    explanation,
    unit_key,
    factors,
    *,
    default_si=None,
    positive=False,
    visible=lambda _a: True,
):
    result = []
    for axis in "xyz":
        default = None
        if default_si is not None:
            default = lambda a, value=default_si: display_number(from_si(value, a[unit_key], factors))
        result.append(
            _number_question(
                f"{prefix}.{axis}",
                f"{label} {axis.upper()}",
                f"{explanation} on the {axis.upper()} axis, in the selected unit.",
                "0.1" if positive else "0",
                default=default,
                minimum=0 if positive else None,
                strict_minimum=positive,
                converter=lambda value, a: to_si(value, a[unit_key], factors),
                visible=visible,
            )
        )
    return result


def _distribution_defaults(prefix):
    if prefix == "radii":
        return {
            "constant": {"value": 0.001},
            "uniform": {"min": 0.0005, "max": 0.001},
            "normal": {"mean": 0.001, "std": 0.0002, "min": 0.0005, "max": 0.0015},
            "lognormal": {"median": 0.001, "sigma": 0.2, "min": 0.0005, "max": 0.002},
        }
    if prefix == "velocity":
        return {
            "constant": {"value": 0},
            "uniform": {"min": 0, "max": 0.02},
            "normal": {"mean": 0.01, "std": 0.003, "min": 0, "max": 0.02},
            "lognormal": {"median": 0.01, "sigma": 0.2, "min": 0, "max": 0.02},
        }
    return {
        "constant": {"value": 0},
        "uniform": {"min": 0, "max": 1},
        "normal": {"mean": 0.5, "std": 0.15, "min": 0, "max": 1},
        "lognormal": {"median": 0.5, "sigma": 0.2, "min": 0, "max": 1},
    }


def _distribution_default(prefix, kind, field):
    return _distribution_defaults(prefix)[kind][field]


def _distribution_explanation(label, field):
    descriptions = {
        "value": "Constant magnitude assigned to every particle.",
        "mean": "Centre of the bounded normal distribution before rejected samples are redrawn.",
        "std": "Positive standard deviation of the normal distribution.",
        "median": "Positive median of the lognormal distribution.",
        "sigma": "Positive dimensionless shape parameter of the lognormal distribution.",
        "min": "Inclusive lower sampling bound.",
        "max": "Inclusive upper sampling bound; it must be greater than the minimum.",
    }
    return f"{label}: {descriptions[field]}"


def _distribution_example(prefix, field):
    for defaults in _distribution_defaults(prefix).values():
        if field in defaults:
            return display_number(defaults[field])
    raise KeyError(field)


def _distribution_from_answers(answers, prefix):
    kind = answers[f"{prefix}.type"]
    fields = {
        "constant": ("value",),
        "uniform": ("min", "max"),
        "normal": ("mean", "std", "min", "max"),
        "lognormal": ("median", "sigma", "min", "max"),
        "explicit": ("values",),
    }[kind]
    return {"type": kind, **{field: answers[f"{prefix}.{field}"] for field in fields}}


def _maximum_distribution_validator(prefix):
    return lambda value, answers: _require_greater(
        value,
        answers[f"{prefix}.min"],
        f"{prefix}.max",
        f"{prefix}.min",
    )


def _vector_from_answers(answers, prefix):
    if answers[f"{prefix}.mode"] == "vector":
        return answers[prefix]
    return [answers[f"{prefix}.{axis}"] for axis in "xyz"]


def _optional_nonnegative_integer(text, _answers):
    if not text.strip():
        return None
    value = _integer(text)
    if value < 0:
        raise ValueError("Seed must be a nonnegative integer.")
    return value


def _integer(text):
    stripped = text.strip()
    if not re.fullmatch(r"[+-]?\d+", stripped):
        raise ValueError("Enter a whole number.")
    return int(stripped)


def _finite_number(text):
    try:
        value = float(text.strip())
    except ValueError as error:
        raise ValueError("Enter a number using a decimal point when needed.") from error
    if not math.isfinite(value):
        raise ValueError("Value must be finite.")
    return value


def _number_list(text):
    stripped = text.strip().removeprefix("[").removesuffix("]").strip()
    if not stripped:
        raise ValueError("Enter at least one number.")
    return [_finite_number(item) for item in re.split(r"[\s,]+", stripped) if item]


def _parse_explicit_radii(text, answers, unit_key, factors):
    values = _number_list(text)
    if any(value <= 0 for value in values):
        raise ValueError("Every explicit radius must be greater than zero.")
    count = answers.get("count")
    if count is not None and len(values) != count:
        raise ValueError(f"Enter exactly {count} radii to match count.")
    if len(values) > answers["max_particles"]:
        raise ValueError("The radius list exceeds max_particles.")
    return [to_si(value, answers[unit_key], factors) for value in values]


def _require_greater(value, boundary, value_name, boundary_name):
    if value <= boundary:
        raise ValueError(f"{value_name} must be greater than {boundary_name} ({boundary:g}).")


def _require_at_least(value, boundary, value_name, boundary_name):
    if value < boundary:
        raise ValueError(f"{value_name} must be at least {boundary_name} ({boundary:g}).")


def _require_at_most(value, boundary, value_name, boundary_name):
    if value > boundary:
        raise ValueError(f"{value_name} must not exceed {boundary_name} ({boundary}).")
