"""Manual and adaptive DEM time-step questions."""
from ..dem.timestep import validate_time_step
from .questions import MenuChoice, Question


def time_step_questions(answers, *, adaptive_supported=True):
    questions = [Question(
        key='dem.time_step_mode', message='Time step selection', kind='select', default='manual',
        choices=(MenuChoice('Manual fixed step', 'manual'),) + ((MenuChoice('Adaptive conservative step', 'adaptive'),) if adaptive_supported else ()),
        explanation='A manual step stays fixed. Adaptive stepping recalculates limits from particle size, material stiffness, contacts, motion and imposed cell deformation. It controls stability estimates, not numerical error.',
        example='Choose adaptive to let the step change during loading and unloading.',
    )]
    if answers.get('dem.time_step_mode', 'manual') == 'manual':
        fields = [('dem.time_step', 'Fixed time step (s)', 1e-6,
                   'Physical time advanced by each DEM step. Choose a positive value small enough to resolve contacts; smaller or stiffer particles generally need smaller steps.')]
    else:
        fields = [
            ('dem.adaptive.initial', 'Initial time step (s)', 1e-6,
             'Upper bound for the first step. The first estimate may reduce it immediately; later steps can grow gradually. Must lie between the minimum and maximum.'),
            ('dem.adaptive.min', 'Minimum permitted stability step (s)', 1e-8,
             'If stability or motion estimates require a smaller step, the run stops with diagnostics rather than ignoring the limit. Short steps used only to land on an exact time boundary are allowed below this value.'),
            ('dem.adaptive.max', 'Maximum time step (s)', 4e-5,
             'Upper limit for every adaptive step, even when the current estimates allow a larger value. This is a cap, not a guarantee that this step is accurate or will be reached.'),
            ('dem.adaptive.safety_factor', 'Stability safety factor', 0.1,
             'Fraction of the estimated Rayleigh and contact-network time limits to use. Smaller values provide more resolution and require more steps. Enter a positive value no greater than 0.5.'),
            ('dem.adaptive.growth_factor', 'Maximum step growth factor', 1.05,
             'Maximum multiplier when increasing the next step: 1.05 permits a 5% increase. Reductions apply immediately. Enter a value from 1 to 2; 1 disables increases.'),
            ('dem.adaptive.max_displacement_fraction', 'Maximum particle motion / radius per step', 0.05,
             'Bounds estimated particle motion during a step as a fraction of its radius, including translation, surface rotation, acceleration and imposed cell motion. Enter a positive value no greater than 0.1.'),
            ('dem.adaptive.max_cell_strain', 'Maximum absolute cell strain per step', 0.001,
             'Limits each imposed logarithmic cell strain increment. For example, 0.001 corresponds to about 0.1% length change per step. Enter a positive value no greater than 0.01.'),
        ]
    for key, message, default, explanation in fields:
        questions.append(Question(key=key, message=message, default=default, explanation=explanation,
                                  example=str(default), parser=lambda value, _: float(value)))
    return questions


def build_time_step(answers):
    if answers.get('dem.time_step_mode', 'manual') == 'manual':
        return answers['dem.time_step']
    raw = {'mode': 'adaptive', **{name: answers['dem.adaptive.' + name] for name in (
        'initial', 'min', 'max', 'safety_factor', 'growth_factor', 'max_displacement_fraction', 'max_cell_strain')}}
    return validate_time_step(raw)[1]
