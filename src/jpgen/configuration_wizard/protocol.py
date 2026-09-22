"""Dynamic, navigable Lego-style DEM protocol editor."""
from pathlib import Path

import yaml

from ..dem.protocol import OBSERVABLES, STRESS_OBSERVABLES, validate_protocol
from .questions import MenuChoice, Question
from .timestep import build_time_step
from ..dem.timestep import validate_time_step


TARGET_EXPLANATIONS = {
    'value': 'Constant mean normal contact stress that the servo will try to reach and maintain, in Pa. Compression is positive and the target must be nonnegative. Reaching it only ends the stage if the stopping condition requests that.',
    'start': 'Pressure target at the start of the linear ramp, in Pa. This is a commanded target, not a change to the initial measured pressure. Must be nonnegative.',
    'end': 'Pressure target reached at the end of the linear ramp, in Pa. It remains the commanded target afterward until the stage ends. Must be nonnegative.',
    'duration': 'Positive simulated time in seconds over which the pressure target changes linearly from start to end. After this interval the target stays at its end value; the stage still ends according to its stopping condition.',
    'mean': 'Center of the sinusoidal pressure target, in Pa. The target oscillates between mean minus amplitude and mean plus amplitude. Must be nonnegative and at least as large as the amplitude.',
    'amplitude': 'Maximum pressure deviation above and below the mean, in Pa; the peak-to-peak range is twice this value. Must be nonnegative and no greater than the mean so the target never becomes tensile.',
    'frequency': 'Number of target-pressure oscillations per simulated second, in Hz. The period is 1/frequency. Must be positive; the signal starts at its mean, initially increasing, on each stage entry.',
}

OBSERVABLE_EXPLANATIONS = {
    'time': 'Global simulated time since the DEM run began, in seconds. It does not restart between stages or repetitions.',
    'stage_time': 'Simulated time since entry into this stage, in seconds. It restarts at zero on each repetition.',
    'kinetic_energy': 'Total translational and rotational particle kinetic energy, in joules. A low value indicates little particle motion but does not by itself prove mechanical equilibrium.',
    'unbalanced_force': 'Dimensionless RMS particle-force imbalance divided by RMS contact force. Values approaching zero indicate mechanical equilibrium; use below with a small threshold.',
    'solid_fraction': 'Sum of particle sphere volumes divided by the current periodic cell volume. This is dimensionless and does not subtract overlap volumes; for example, 0.64 means a nominal solid fraction of 64%.',
    'bulk_density': 'Total particle mass divided by the current periodic cell volume, in kg/m³. This changes as the cell deforms and is different from the fixed particle material density.',
    'pressure': 'Mean normal contact stress (one third of the stress tensor trace), in Pa, with compression positive. It does not include a kinetic stress contribution.',
    'stress_xx': 'XX component of the contact stress tensor, in Pa. Normal compression is positive.',
    'stress_yy': 'YY component of the contact stress tensor, in Pa. Normal compression is positive.',
    'stress_zz': 'ZZ component of the contact stress tensor, in Pa. Normal compression is positive.',
    'stress_xy': 'XY component of the contact stress tensor, in Pa. This is a signed shear component, so its threshold may be positive or negative.',
    'stress_xz': 'XZ component of the contact stress tensor, in Pa. This is a signed shear component, so its threshold may be positive or negative.',
    'stress_yz': 'YZ component of the contact stress tensor, in Pa. This is a signed shear component, so its threshold may be positive or negative.',
}


def _positive_integer(value, _answers):
    result = int(value)
    if result < 1:
        raise ValueError('Enter a positive integer.')
    return result


def _float(value, _answers):
    import math
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Enter a finite number.')
    return result


def _vector(value, answers):
    result = [_float(v, answers) for v in value.replace(',', ' ').split()]
    if len(result) != 3:
        raise ValueError('Enter three numbers: X Y Z.')
    return result


def _question(key, message, default, parser=_float, choices=None, *, explanation):
    return Question(key=key, message=message, default=default, parser=parser,
                    kind='select' if choices else 'text',
                    choices=tuple(MenuChoice(label, value) for label, value in (choices or [])),
                    explanation=explanation, example=str(default))


def protocol_questions(answers, periodic, capabilities=None):
    choices = [('Fixed final time', 'time'), ('Build stages and repeat blocks', 'builder'), ('Load protocol from YAML file', 'file')]
    questions = [_question('dem.execution', 'DEM execution', 'time', choices=choices,
                                   explanation='Choose how the simulation ends: free evolution up to a fixed time, a sequence of configurable stages and repeat blocks, or a protocol imported from a YAML file.')]
    mode = answers.get('dem.execution', 'time')
    if mode == 'time':
        questions.append(_question('dem.end_time', 'Final time (s)', .001,
                                   explanation='Total simulated duration of free evolution, in seconds. It must be an integer multiple of the fixed time step.'))
    elif mode == 'file':
        def read(value, current):
            try:
                data = yaml.safe_load(Path(value).expanduser().read_text())
            except (OSError, yaml.YAMLError) as error:
                raise ValueError(str(error)) from error
            if isinstance(data, dict):
                data = data.get('dem', data)
                data = data.get('protocol', data) if isinstance(data, dict) else data
            dt = validate_time_step(build_time_step(current))
            protocol, _ = validate_protocol(data, dt, 'periodic' if periodic else 'open')
            return protocol
        questions.append(_question('dem.protocol_file', 'Protocol YAML path', '', parser=read,
                                   explanation='Read a protocol mapping, protocol: section, or a full JPGen YAML. The protocol is embedded into the generated file.'))
    else:
        questions.append(_question('dem.protocol.sample_every', 'Record observables every N steps', 100, _positive_integer,
                                   explanation='Save measured observables and cell geometry every N integration steps. Larger values produce fewer output records. Stopping conditions are still checked every step, and stage exits are always recorded.'))
        questions.extend(_stage_questions(answers, 'dem.protocol', periodic, capabilities=capabilities))
    return questions


def _stage_questions(answers, prefix, periodic, depth=0, capabilities=None):
    if depth > 20:
        raise ValueError('Maximum repeat nesting depth is 20.')
    def count(value, current):
        result = _positive_integer(value, current)
        if result > 100:
            raise ValueError('Use at most 100 pieces per block; use repeat for cycles.')
        return result
    questions = [_question(prefix + '.count', 'Number of pieces in this sequence', 1, count,
                                   explanation='Number of stages or repeat blocks to execute in order within this sequence. Enter an integer from 1 to 100; a repeat block counts as one piece here.')]
    for index in range(answers.get(prefix + '.count', 1)):
        key = f'{prefix}.{index}'
        questions.append(_question(key + '.kind', f'Piece {index + 1}', 'stage', choices=[('Simulation stage', 'stage'), ('Repeat a sequence', 'repeat')],
                                   explanation='A simulation stage combines a controller with a stopping condition. A repeat block runs a nested sequence several times, for example alternating loading and unloading stages.'))
        questions.append(_question(key + '.name', 'Piece name', f'stage_{index + 1}', parser=lambda v, _: v.strip(),
                                   explanation='Give this stage or repeat block a nonempty descriptive name. The name appears in the saved configuration and execution history so you can identify which part of the experiment ran.'))
        if answers.get(key + '.kind') == 'repeat':
            questions.append(_question(key + '.repeat', 'Number of repetitions', 10, _positive_integer,
                                   explanation='Number of times to execute the entire nested sequence, including the first pass. Each pass keeps the physical state from the previous one, while stage time and condition timers restart.'))
            questions.extend(_stage_questions(answers, key + '.children', periodic, depth + 1, capabilities))
            continue
        controllers = [('Free evolution (fixed current cell)', 'free_evolution')]
        if periodic:
            controllers += [('Stress servo', 'stress_servo'), ('Prescribed cell strain rate', 'strain_rate')]
        if capabilities is not None:
            controllers = [(label, kind) for label, kind in controllers if kind in capabilities.controls]
        if not controllers:
            raise ValueError('This engine has no supported controller for the selected boundary.')
        questions.append(_question(key + '.control', 'Controller', controllers[0][1], choices=controllers,
                                   explanation='Choose how to drive the particles during this stage. Free evolution applies no cell deformation. In a periodic domain, the stress servo adjusts cell dimensions to track a stress target, while prescribed strain rate deforms the cell at a fixed rate.'))
        control = answers.get(key + '.control', controllers[0][1])
        if control == 'stress_servo':
            questions.append(_question(key + '.mode', 'Stress control mode', 'isotropic', choices=[('Isotropic pressure', 'isotropic'), ('Normal stresses X Y Z', 'anisotropic')],
                                   explanation='Isotropic control tracks mean normal contact stress using the same symmetric face velocity on all axes. Anisotropic control tracks separate normal stress targets along X, Y and Z by adjusting each cell dimension independently.'))
            if answers.get(key + '.mode', 'isotropic') == 'anisotropic':
                questions.append(_question(key + '.target_stress', 'Target normal stresses X Y Z (Pa, compression positive)', '100000 100000 100000', _vector,
                                   explanation='Enter the target normal contact stresses along X, Y and Z in Pa. Compression is positive; all three targets must be nonnegative. These are controller targets; the stopping condition is configured separately.'))
            else:
                questions.append(_question(key + '.signal', 'Pressure target', 'constant', choices=[('Constant', 'constant'), ('Linear ramp', 'ramp'), ('Sinusoidal', 'sine')],
                                   explanation='Choose whether the pressure target stays constant, changes linearly from a start value to an end value, or oscillates sinusoidally. Ramps and oscillations use elapsed time within this stage and restart on each repetition.'))
                signal = answers.get(key + '.signal', 'constant')
                fields = {'constant': [('value', 'Target pressure (Pa)', 100000.0)],
                          'ramp': [('start', 'Start pressure (Pa)', 50000.0), ('end', 'End pressure (Pa)', 100000.0), ('duration', 'Ramp duration (s)', 1.0)],
                          'sine': [('mean', 'Mean pressure (Pa)', 75000.0), ('amplitude', 'Pressure amplitude (Pa)', 25000.0), ('frequency', 'Frequency (Hz)', 1.0)]}[signal]
                for field, label, default in fields:
                    questions.append(_question(key + '.target.' + field, label, default,
                                   explanation=TARGET_EXPLANATIONS[field]))
            questions.append(_question(key + '.max_velocity', 'Maximum wall velocity (m/s)', 0.05,
                                   explanation='Positive limit on the absolute velocity of each opposing cell face. The servo otherwise uses error × D50 / (time step × particle Young modulus), using the portable JPGen servo definition.'))
        elif control == 'strain_rate':
            questions.append(_question(key + '.rate', 'Cell strain rates X Y Z (1/s; compression negative)', '-0.1 -0.1 -0.1', _vector,
                                   explanation='Enter the imposed logarithmic strain rates along X, Y and Z in 1/s. Negative values compress, positive values expand, and zero keeps that dimension fixed. Cell dimensions and particle positions deform together; each fixed step must keep the strain increment at most 0.01.'))
        questions.append(_question(key + '.condition_mode', 'Finish this stage when', 'single', choices=[('One condition is met', 'single'), ('All conditions are met', 'all'), ('Any condition is met', 'any')],
                                   explanation='Choose one stopping condition, require all configured conditions to hold at the same observation, or accept any one of them. Conditions are checked after every integration step.'))
        group = answers.get(key + '.condition_mode', 'single')
        if group != 'single':
            questions.append(_question(key + '.conditions', 'Number of conditions', 2, count,
                                   explanation='Number of stopping conditions to combine with the all/any choice above. Each condition has its own observable, comparison and threshold. Enter an integer from 1 to 100.'))
        available = OBSERVABLES if periodic else OBSERVABLES - STRESS_OBSERVABLES - {'solid_fraction', 'bulk_density'}
        if capabilities is not None:
            available = available & (capabilities.observables | {'time', 'stage_time'})
        for c in range(1 if group == 'single' else answers.get(key + '.conditions', 2)):
            ck = f'{key}.condition.{c}'
            questions.append(_question(ck + '.observable', f'Condition {c + 1}: observable', 'stage_time', choices=[(v, v) for v in sorted(available)],
                                   explanation='Choose the measured quantity used to end this stage. time is global simulation time; stage_time restarts at each stage entry. Other choices measure kinetic energy or, for periodic cells, contact stress and packing density. The threshold question explains the selected quantity and its units.'))
            questions.append(_question(ck + '.op', 'Comparison', 'above', choices=[('At least (>=)', 'above'), ('At most (<=)', 'below'), ('Within tolerance', 'near')],
                                   explanation='At least accepts values greater than or equal to the threshold; at most accepts values less than or equal to it. Within tolerance accepts an absolute difference from the target no larger than the absolute tolerance plus the relative tolerance times the target magnitude.'))
            questions.append(_question(ck + '.value', 'Threshold or target (SI)', .001,
                                   explanation=OBSERVABLE_EXPLANATIONS[answers.get(ck + '.observable', 'stage_time')] + ' Enter the threshold or target for the selected comparison.'))
            if answers.get(ck + '.op') == 'near':
                questions.append(_question(ck + '.atol', 'Absolute tolerance (SI)', 1e-6,
                                   explanation='Nonnegative allowable absolute error, in the same units as the selected observable. With relative tolerance, acceptance requires |measured - target| <= absolute tolerance + relative tolerance × |target|.'))
                questions.append(_question(ck + '.rtol', 'Relative tolerance', 0.0,
                                   explanation='Nonnegative dimensionless tolerance relative to the target magnitude: 0.01 adds an allowance of 1% of |target|. It is added to the absolute tolerance; for a zero target, only the absolute tolerance contributes.'))
        questions.extend([_question(key + '.hold_for', 'Keep condition satisfied for (s)', 0.0,
                                   explanation='Require the combined stopping condition to stay true for this many simulated seconds. The timer starts at the first matching observation and resets whenever the combined condition becomes false. Zero allows completion at the first match.'),
                          _question(key + '.min_duration', 'Minimum stage duration (s)', 0.0,
                                   explanation='Minimum simulated time this stage must run before it may finish, even if its stopping condition is already satisfied. Zero adds no minimum. This does not delay the start of the hold timer.'),
                          _question(key + '.max_duration', 'Maximum stage duration (s)', 1.0,
                                    explanation='Maximum simulated time allowed for this stage, in seconds, measured from its entry. If the stopping condition is not met by the last allowed step, the run fails and saves diagnostics. Nonintegral step counts are rounded up. The duration must be at least one fixed time step.')])
    return questions


def build_protocol(answers, prefix='dem.protocol'):
    stages = []
    for index in range(answers[prefix + '.count']):
        key = f'{prefix}.{index}'
        stage = {'name': answers[key + '.name']}
        if answers[key + '.kind'] == 'repeat':
            stage.update(repeat=answers[key + '.repeat'], stages=build_protocol(answers, key + '.children')['stages'])
        else:
            control = {'type': answers[key + '.control']}
            if control['type'] == 'strain_rate':
                control['rate'] = answers[key + '.rate']
            elif control['type'] == 'stress_servo':
                control.update({field: answers[key + '.' + field] for field in ('mode', 'max_velocity')})
                if control['mode'] == 'anisotropic':
                    control['target_stress'] = answers[key + '.target_stress']
                else:
                    signal = answers[key + '.signal']
                    if signal == 'constant':
                        target = answers[key + '.target.value']
                    else:
                        fields = ('start', 'end', 'duration') if signal == 'ramp' else ('mean', 'amplitude', 'frequency')
                        target = {'type': signal, **{f: answers[key + '.target.' + f] for f in fields}}
                    control['target_pressure'] = target
            group = answers[key + '.condition_mode']
            leaves = []
            for c in range(1 if group == 'single' else answers[key + '.conditions']):
                ck = f'{key}.condition.{c}'
                condition = {f: answers[ck + '.' + f] for f in ('observable', 'op', 'value')}
                if condition['op'] == 'near':
                    condition.update({f: answers[ck + '.' + f] for f in ('atol', 'rtol')})
                leaves.append(condition)
            until = leaves[0] if group == 'single' else {group: leaves}
            until.update({f: answers[key + '.' + f] for f in ('hold_for', 'min_duration')})
            stage.update(control=control, until=until, max_duration=answers[key + '.max_duration'])
        stages.append(stage)
    return {'stages': stages, 'sample_every': answers.get(prefix + '.sample_every', 100)}
