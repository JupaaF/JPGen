"""Dynamic, navigable Lego-style DEM protocol editor."""
import math
from pathlib import Path

import yaml

from ..dem.protocol import (
    OBSERVABLES, STRESS_OBSERVABLES, validate_protocol,
    DEFAULT_SERVO_MAX_VELOCITY, DEFAULT_SERVO_LOADING_FACTOR,
    DEFAULT_SERVO_UPDATE_EVERY_STEPS, path_targets,
)
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


def _nonnegative_integer(value, _answers):
    result = int(value)
    if result < 0 or str(result) != str(value).strip():
        raise ValueError('Enter a nonnegative integer.')
    return result


def _float(value, _answers):
    import math
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Enter a finite number.')
    return result


def _positive_float(value, answers):
    result = _float(value, answers)
    if result <= 0:
        raise ValueError('Enter a positive number.')
    return result


def _density_targets(value, answers):
    values = [_positive_float(part, answers) for part in value.replace(',', ' ').split()]
    if not values:
        raise ValueError('Enter at least one density target.')
    return values


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
        path_available = (periodic and capabilities is not None
                          and 'stress_servo' in capabilities.controls
                          and {'pressure', 'kinetic_energy', 'unbalanced_force'} <= capabilities.observables
                          and 'symmetric_wall_velocity' in capabilities.actuator_commands
                          and capabilities.particle_snapshots)
        kinds = [('Simulation stage', 'stage'), ('Repeat a sequence', 'repeat')]
        if path_available:
            kinds.append(('Equilibrated pressure path', 'path'))
        density_available = (path_available and 'density_continuation' in capabilities.controls
                             and all(getattr(capabilities, flag) for flag in
                                     ('state_restore', 'contact_parameter_updates',
                                      'contact_history_checkpoint', 'rollback',
                                      'target_publication', 'native_restart_export')))
        if density_available:
            kinds.append(('Friction driven density continuation', 'density'))
        questions.append(_question(key + '.kind', f'Piece {index + 1}', 'stage', choices=kinds,
                                   explanation='Choose one stage, a repeated sequence, or a pressure path that saves each equilibrated target before moving to the next.'))
        questions.append(_question(key + '.name', 'Piece name', f'stage_{index + 1}', parser=lambda v, _: v.strip(),
                                   explanation='Give this stage or repeat block a nonempty descriptive name. The name appears in the saved configuration and in the failed-stage diagnostic when applicable.'))
        if answers.get(key + '.kind') == 'repeat':
            questions.append(_question(key + '.repeat', 'Number of repetitions', 10, _positive_integer,
                                   explanation='Number of times to execute the entire nested sequence, including the first pass. Each pass keeps the physical state from the previous one, while stage time and condition timers restart.'))
            questions.extend(_stage_questions(answers, key + '.children', periodic, depth + 1, capabilities))
            continue
        if answers.get(key + '.kind') == 'path':
            questions.extend(_pressure_path_questions(
                key, answers, {'stress_xx', 'stress_yy', 'stress_zz'} <= capabilities.observables))
            continue
        if answers.get(key + '.kind') == 'density':
            questions.extend(_density_questions(key))
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
            questions.append(_question(key + '.max_velocity', 'Maximum wall velocity (m/s)', DEFAULT_SERVO_MAX_VELOCITY, _positive_float,
                                   explanation='Positive limit on the absolute velocity of each opposing cell face. The servo otherwise uses error × loading factor × D50 / (time step × particle Young modulus).'))
            questions.append(_question(key + '.loading_factor', 'Servo loading factor', DEFAULT_SERVO_LOADING_FACTOR, _positive_float,
                                   explanation='Positive dimensionless multiplier on the pressure-error response. Kratos uses 0.8 by default. The commanded wall velocity is error × loading factor × D50 / (time step × particle Young modulus), clipped by the maximum wall velocity.'))
            questions.append(_question(key + '.update_every_steps', 'Move cell every N steps', DEFAULT_SERVO_UPDATE_EVERY_STEPS, _positive_integer,
                                   explanation='Positive number of integration steps between cell updates in this stage. 1 moves the cell every step; 50 matches the default frequency of Kratos native servo. The first move is on step N, and the cell remains fixed between moves.'))
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


def _stress_ratios(value, answers):
    ratios = _vector(value, answers)
    if any(ratio <= 0 for ratio in ratios) or not math.isclose(sum(ratios), 3.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError('Enter three positive ratios whose sum is 3 (mean 1).')
    return ratios


def _pressure_path_questions(key, answers, anisotropic_available):
    questions = [
        _question(key + '.path.start', 'Start pressure reference (Pa)', 5000.0, _positive_float,
                  explanation='Positive spacing reference. Prepare and equilibrate this initial state separately; the path does not verify or save it.'),
        _question(key + '.path.end', 'Final pressure (Pa)', 200000.0, _positive_float,
                  explanation='Positive final servo target, included among the saved states.'),
        _question(key + '.path.intermediate_states', 'Intermediate equilibrated states', 20, _nonnegative_integer,
                  explanation='Number of saved targets strictly between start and end. The final target adds one more state.'),
        _question(key + '.path.spacing', 'Target spacing', 'log',
                  choices=[('Logarithmic', 'log'), ('Linear', 'linear')],
                  explanation='Logarithmic spacing gives equal pressure ratios; linear spacing gives equal pressure differences.'),
        _question(key + '.path.mode', 'Stress control mode', 'isotropic',
                  choices=[('Isotropic pressure', 'isotropic')] +
                          ([('Normal stresses X Y Z', 'anisotropic')] if anisotropic_available else []),
                  explanation='Isotropic control adjusts all cell dimensions together to track mean pressure. Anisotropic control tracks a separate normal stress on each axis.'),
    ]
    if answers.get(key + '.path.mode', 'isotropic') == 'anisotropic':
        questions.append(_question(key + '.path.stress_ratios', 'Normal stress ratios X Y Z (mean 1)', '1 1 1', _stress_ratios,
                                   explanation='Multiply each path pressure by these positive ratios to obtain the X, Y and Z targets. Their sum must be 3, so the target mean pressure stays on the requested path.'))
    questions.extend([
        _question(key + '.path.max_velocity', 'Maximum wall velocity (m/s)', DEFAULT_SERVO_MAX_VELOCITY, _positive_float,
                  explanation='Positive velocity limit for the stress servo on each cell face.'),
        _question(key + '.path.loading_factor', 'Servo loading factor', DEFAULT_SERVO_LOADING_FACTOR, _positive_float,
                  explanation='Positive multiplier on the pressure-error response.'),
        _question(key + '.path.update_every_steps', 'Move cell every N steps', DEFAULT_SERVO_UPDATE_EVERY_STEPS, _positive_integer,
                  explanation='Each target starts its own update counter; the cell moves on step N.'),
        _question(key + '.path.target_rtol', 'Pressure relative tolerance', 0.01, _positive_float,
                  explanation='The measured pressure must remain within this fraction of the current target.'),
        _question(key + '.path.kinetic_energy_below', 'Kinetic energy threshold (J)', 1e-8, _positive_float,
                  explanation='Require total translational and rotational kinetic energy below this threshold.'),
        _question(key + '.path.unbalanced_force_below', 'Unbalanced force threshold', 1e-3, _positive_float,
                  explanation='Require dimensionless force imbalance below this threshold.'),
        _question(key + '.path.hold_for', 'Hold all conditions for (s)', 0.005, _positive_float,
                  explanation='The pressure, energy and force conditions must remain true together for this simulated duration.'),
        _question(key + '.path.max_duration_per_target', 'Maximum duration per target (s)', 1.0, _positive_float,
                  explanation='Stop the sequence with diagnostics if one target does not equilibrate in this time.'),
    ])
    return questions


def _density_questions(key):
    defaults = [
        ('targets', 'Increasing solid fraction targets', '0.620 0.625 0.630', _density_targets,
         'Space separated nominal solid fractions. Each is saved only after pressure, force, energy and density stability have held.'),
        ('density_atol', 'Absolute density tolerance', 0.0002, _positive_float,
         'Absolute tolerance around each requested solid fraction.'),
        ('target_pressure', 'Confining mean pressure (Pa)', 5000.0, _positive_float,
         'Positive mean pressure maintained during the whole continuation.'),
        ('pressure_rtol', 'Relative pressure tolerance', 0.01, _positive_float,
         'Acceptance requires measured pressure inside this relative tolerance.'),
        ('max_velocity', 'Maximum wall velocity (m/s)', 0.01, _positive_float,
         'Limit for the pressure servo on each face.'),
        ('min_factor', 'Minimum friction factor', 0.0, _float,
         'Both entry friction coefficients are multiplied by this factor at the limit.'),
        ('initial_decrement', 'Initial friction factor decrement', 0.05, _positive_float,
         'First reduction of the shared friction factor.'),
        ('min_decrement', 'Minimum decrement', 0.0001, _positive_float,
         'Smallest retry resolution before declaring a resolution limit.'),
        ('max_decrement', 'Maximum decrement', 0.10, _positive_float,
         'Largest allowed reduction in one accepted step.'),
        ('safety_factor', 'Prediction safety factor', 0.5, _positive_float,
         'Fraction of the predicted decrement when an accepted slope is available.'),
        ('growth_factor', 'Maximum decrement growth factor', 1.5, _positive_float,
         'Upper bound on growth relative to the last successful decrement.'),
        ('retry_factor', 'Retry reduction factor', 0.5, _positive_float,
         'Multiplier applied to a discarded decrement.'),
        ('kinetic_energy_below', 'Kinetic energy threshold (J)', 1e-8, _positive_float,
         'Translation plus rotation energy required for relaxation.'),
        ('unbalanced_force_below', 'Unbalanced force threshold', 1e-3, _positive_float,
         'Dimensionless force imbalance required for relaxation.'),
        ('hold_for', 'Hold all conditions for (s)', 0.005, _positive_float,
         'Consecutive time for the joint acceptance condition.'),
        ('stability_window', 'Density stability window (s)', 0.005, _positive_float,
         'Observation interval whose density range must stay small.'),
        ('stability_max_range', 'Maximum density range', 0.00005, _positive_float,
         'Largest nominal solid fraction range in the stability window.'),
        ('relaxation_max_duration', 'Maximum duration per attempt (s)', 0.1, _positive_float,
         'Failed attempts are rolled back after this simulated duration.'),
        ('max_attempts', 'Maximum friction reduction attempts', 200, _positive_integer,
         'Total attempts across all density targets.'),
        ('max_retries_per_increment', 'Maximum retries per decrement', 12, _positive_integer,
         'Maximum discarded attempts before a diagnosed failure.'),
        ('max_duration', 'Total attempted duration (s)', 10.0, _positive_float,
         'Integrated work budget including rolled back attempts.'),
    ]
    return [_question(key + '.density.' + field, label, default, parser, explanation=help_text)
            for field, label, default, parser, help_text in defaults]


def build_protocol(answers, prefix='dem.protocol'):
    stages = []
    for index in range(answers[prefix + '.count']):
        key = f'{prefix}.{index}'
        stage = {'name': answers[key + '.name']}
        if answers[key + '.kind'] == 'repeat':
            stage.update(repeat=answers[key + '.repeat'], stages=build_protocol(answers, key + '.children')['stages'])
        elif answers[key + '.kind'] == 'density':
            value = lambda field: answers[key + '.density.' + field]
            targets = value('targets')
            stage.update(
                control={
                    'type': 'density_continuation', 'targets': targets,
                    'density_atol': value('density_atol'),
                    'confinement': {field: value(field) for field in
                                    ('target_pressure', 'pressure_rtol', 'max_velocity')},
                    'friction': {field: value(field) for field in
                                 ('min_factor', 'initial_decrement', 'min_decrement',
                                  'max_decrement', 'safety_factor', 'growth_factor', 'retry_factor')},
                    'relaxation': {
                        'max_duration': value('relaxation_max_duration'),
                        'condition': {'all': [
                            {'observable': 'kinetic_energy', 'op': 'below',
                             'value': value('kinetic_energy_below')},
                            {'observable': 'unbalanced_force', 'op': 'below',
                             'value': value('unbalanced_force_below')}],
                            'hold_for': value('hold_for')},
                        'density_stability': {'window': value('stability_window'),
                                              'max_range': value('stability_max_range')}},
                    'limits': {field: value(field) for field in
                               ('max_attempts', 'max_retries_per_increment')},
                    'snapshots': {'mode': 'equilibrated', 'include_restart': True}},
                until={'observable': 'density_targets_completed', 'op': 'above',
                       'value': len(targets)}, max_duration=value('max_duration'))
        elif answers[key + '.kind'] == 'path':
            value = lambda field: answers[key + '.path.' + field]
            stage['path'] = {
                'observable': 'pressure',
                'targets': {'start': value('start'), 'end': value('end'),
                            'intermediate_states': value('intermediate_states'), 'spacing': value('spacing')},
                'control': {'type': 'stress_servo', 'mode': value('mode'),
                            **({'stress_ratios': value('stress_ratios')} if value('mode') == 'anisotropic' else {}),
                            **{field: value(field) for field in ('max_velocity', 'loading_factor', 'update_every_steps')}},
                'acceptance': {'target_rtol': value('target_rtol'),
                               'kinetic_energy_below': value('kinetic_energy_below'),
                               'unbalanced_force_below': value('unbalanced_force_below'),
                               'hold_for': value('hold_for')},
                'max_duration_per_target': value('max_duration_per_target'),
            }
        else:
            control = {'type': answers[key + '.control']}
            if control['type'] == 'strain_rate':
                control['rate'] = answers[key + '.rate']
            elif control['type'] == 'stress_servo':
                control.update({field: answers[key + '.' + field] for field in ('mode', 'max_velocity', 'loading_factor', 'update_every_steps')})
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


def pressure_path_previews(stages):
    """Render resolved targets for interactive review without expanding YAML."""
    lines = []

    def visit(pieces, prefix=''):
        for piece in pieces:
            label = prefix + piece.get('name', 'path')
            if 'stages' in piece:
                visit(piece['stages'], label + '/')
            elif piece.get('control', {}).get('type') == 'density_continuation':
                values = piece['control']['targets']
                lines.append(f"{label}: {len(values)} density targets (solid fraction)")
                for index, value in enumerate(values, 1):
                    lines.append(f"  {index}: {value:.9g}")
            elif 'path' in piece and piece['path']['observable'] == 'pressure':
                targets = piece['path']['targets']
                values = list(path_targets(targets))
                lines.append(f"{label}: {len(values)} pressure targets (Pa)")
                if len(values) <= 30:
                    shown = enumerate(values, 1)
                else:
                    shown = list(enumerate(values[:10], 1)) + [(len(values), values[-1])]
                for index, value in shown:
                    if len(values) > 30 and index == len(values):
                        lines.append('  ...')
                    lines.append(f"  {index}: {value:.9g}")
    visit(stages)
    return '\n'.join(lines)
