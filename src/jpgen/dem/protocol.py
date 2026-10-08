"""Declarative protocol validation and execution, using only the standard library.

This module is also copied into standalone solver cases. Compression is positive;
controllers return explicit actuator commands. Prescribed strain rates use
logarithmic cell strain (expansion positive); stress servos use symmetric wall
velocities (compression positive), matching Kratos' servo convention.
"""
import copy
import math

if __package__:
    from .commands import ActuatorCommand, NoActuation, CellStrainRate, SymmetricWallVelocity
else:
    from commands import ActuatorCommand, NoActuation, CellStrainRate, SymmetricWallVelocity

OBSERVABLES = {'time', 'stage_time', 'kinetic_energy', 'normalized_kinetic_energy',
               'unbalanced_force', 'solid_fraction', 'bulk_density',
               'pressure', 'stress_xx', 'stress_yy', 'stress_zz', 'stress_xy', 'stress_xz', 'stress_yz',
               'density_targets_completed'}
STRESS_OBSERVABLES = {name for name in OBSERVABLES if name.startswith('stress_')} | {'pressure'}

DEFAULT_SERVO_MAX_VELOCITY = 0.05
DEFAULT_SERVO_LOADING_FACTOR = 0.8
DEFAULT_SERVO_UPDATE_EVERY_STEPS = 1


def _mapping(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError(f'Expected mapping with keys {sorted(allowed)}; required {sorted(required)}: {value!r}')


def _number(value, minimum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f'Expected finite number: {value!r}')
    if minimum is not None and (value < minimum or (positive and value == minimum)):
        raise ValueError(f'Number must be {">" if positive else ">="} {minimum}: {value}')
    return value


def _count(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError('Repeat must be a positive integer.')
    return value



def _density_control(control, dt):
    _mapping(control, {'type', 'target', 'density_atol', 'confinement', 'relaxation'},
             {'type', 'target', 'density_atol', 'confinement', 'relaxation'})
    _number(control['target'], 0, True)
    _number(control['density_atol'], 0, True)
    if control['density_atol'] >= control['target']:
        raise ValueError('density_atol must be smaller than the density target.')
    confinement = control['confinement']
    _mapping(confinement, {'target_pressure', 'pressure_rtol', 'max_velocity',
                           'loading_factor', 'update_every_steps'},
             {'target_pressure', 'pressure_rtol', 'max_velocity'})
    _number(confinement['target_pressure'], 0, True)
    _number(confinement['pressure_rtol'], 0, True)
    servo = {'type': 'stress_servo', 'mode': 'isotropic',
             **{key: confinement[key] for key in ('target_pressure', 'max_velocity')},
             'loading_factor': confinement.get('loading_factor', DEFAULT_SERVO_LOADING_FACTOR),
             'update_every_steps': confinement.get('update_every_steps', DEFAULT_SERVO_UPDATE_EVERY_STEPS)}
    validate_control(servo)
    confinement['loading_factor'] = servo['loading_factor']
    confinement['update_every_steps'] = servo['update_every_steps']
    relaxation = control['relaxation']
    _mapping(relaxation, {'condition', 'density_stability'}, {'condition', 'density_stability'})
    validate_condition(relaxation['condition'])
    leaves = relaxation['condition'].get('all', [relaxation['condition']])
    if not any(leaf.get('observable') == 'unbalanced_force' and leaf.get('op') == 'below'
               for leaf in leaves):
        raise ValueError('Density relaxation must require unbalanced_force below its threshold.')
    if condition_observables(relaxation['condition']) - {'unbalanced_force'}:
        raise ValueError('Density relaxation conditions support unbalanced_force only.')
    stability = relaxation['density_stability']
    _mapping(stability, {'window', 'max_range'}, {'window', 'max_range'})
    _number(stability['window'], dt if dt else 0, not bool(dt))
    _number(stability['max_range'], 0, True)


def _nonnegative_count(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('intermediate_states must be a nonnegative integer.')
    return value


def path_targets(specification):
    """Yield the starting target, intermediate targets, and the exact final target."""
    start, end = specification['start'], specification['end']
    intervals = specification['intermediate_states'] + 1
    yield start
    for index in range(1, intervals + 1):
        if index == intervals:
            yield end
        elif specification['spacing'] == 'log':
            yield math.exp(math.log(start) + (math.log(end) - math.log(start)) * index / intervals)
        else:
            yield start + (end - start) * index / intervals


def pressure_path_stage(path, target, index):
    """Build one ordinary leaf stage; future path drivers can reuse the schedule."""
    control = dict(path['control'])
    ratios = control.pop('stress_ratios', None)
    if control.get('mode', 'isotropic') == 'anisotropic':
        control['target_stress'] = [target * ratio for ratio in ratios]
        stress_targets = [('stress_' + axis, value)
                          for axis, value in zip(('xx', 'yy', 'zz'), control['target_stress'])]
    else:
        control['mode'] = 'isotropic'
        control['target_pressure'] = target
        stress_targets = []
    acceptance = path['acceptance']
    energy_observable = ('normalized_kinetic_energy' if 'normalized_kinetic_energy_below' in acceptance
                         else 'kinetic_energy')
    def near(observable, value):
        return {
            'observable': observable, 'op': 'near', 'value': value,
            **({'atol': acceptance['target_atol']} if 'target_atol' in acceptance else {}),
            **({'rtol': acceptance['target_rtol']} if 'target_rtol' in acceptance else {}),
        }
    condition = {
        'all': [
            near('pressure', target),
            *(near(observable, value) for observable, value in stress_targets),
            {'observable': energy_observable, 'op': 'below',
             'value': acceptance[energy_observable + '_below']},
            {'observable': 'unbalanced_force', 'op': 'below', 'value': acceptance['unbalanced_force_below']},
        ],
        'hold_for': acceptance['hold_for'],
    }
    return {
        'control': control, 'until': condition,
        'max_duration': path['max_duration_per_target'],
        '_path_target': {'observable': 'pressure', 'index': index,
                         'total': path['targets']['intermediate_states'] + 2,
                         'value': target},
    }


def validate_path(path, dt, boundary):
    _mapping(path, {'observable', 'targets', 'control', 'acceptance', 'max_duration_per_target'},
             {'observable', 'targets', 'control', 'acceptance', 'max_duration_per_target'})
    if path['observable'] != 'pressure':
        raise ValueError('Only pressure paths are supported; use density_continuation for density control.')
    if boundary != 'periodic':
        raise ValueError('Pressure paths require periodic boundaries.')
    targets = path['targets']
    _mapping(targets, {'start', 'end', 'intermediate_states', 'spacing'},
             {'start', 'end', 'intermediate_states', 'spacing'})
    _number(targets['start'], 0, True)
    _number(targets['end'], 0, True)
    if targets['start'] == targets['end']:
        raise ValueError('Path start and end must differ.')
    _nonnegative_count(targets['intermediate_states'])
    if targets['spacing'] not in ('linear', 'log'):
        raise ValueError('Path spacing must be linear or log.')
    if targets['intermediate_states'] > 100000:
        raise ValueError('Path contains too many intermediate states.')
    control = path['control']
    _mapping(control, {'type', 'mode', 'stress_ratios', 'max_velocity', 'loading_factor', 'update_every_steps'}, {'type'})
    if control['type'] != 'stress_servo':
        raise ValueError('Pressure paths require stress_servo control.')
    mode = control.setdefault('mode', 'isotropic')
    if mode == 'isotropic':
        if 'stress_ratios' in control:
            raise ValueError('stress_ratios requires anisotropic pressure path control.')
        validate_control(control | {'target_pressure': targets['end']})
    elif mode == 'anisotropic':
        ratios = control.get('stress_ratios')
        if not isinstance(ratios, list) or len(ratios) != 3:
            raise ValueError('Anisotropic pressure paths require three stress_ratios.')
        for ratio in ratios:
            _number(ratio, 0, True)
        if not math.isclose(sum(ratios), 3.0, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError('Pressure path stress_ratios must sum to 3 (mean 1).')
        validate_control({key: value for key, value in control.items() if key != 'stress_ratios'}
                         | {'target_stress': [targets['end'] * ratio for ratio in ratios]})
    else:
        raise ValueError('Pressure path mode must be isotropic or anisotropic.')
    for field, default in (('max_velocity', DEFAULT_SERVO_MAX_VELOCITY),
                           ('loading_factor', DEFAULT_SERVO_LOADING_FACTOR),
                           ('update_every_steps', DEFAULT_SERVO_UPDATE_EVERY_STEPS)):
        control.setdefault(field, default)
    acceptance = path['acceptance']
    _mapping(acceptance, {'target_atol', 'target_rtol', 'kinetic_energy_below',
                          'normalized_kinetic_energy_below', 'unbalanced_force_below', 'hold_for'},
             {'unbalanced_force_below', 'hold_for'})
    if ('kinetic_energy_below' in acceptance) == ('normalized_kinetic_energy_below' in acceptance):
        raise ValueError('Path acceptance requires exactly one kinetic energy threshold.')
    if not ({'target_atol', 'target_rtol'} & set(acceptance)):
        raise ValueError('Path acceptance requires target_atol and/or target_rtol.')
    for field in ('target_atol', 'target_rtol', 'kinetic_energy_below',
                  'normalized_kinetic_energy_below', 'unbalanced_force_below', 'hold_for'):
        if field in acceptance:
            _number(acceptance[field], 0)
    if acceptance.get('target_atol', 0) == acceptance.get('target_rtol', 0) == 0:
        raise ValueError('Path target tolerance must be positive.')
    duration = _number(path['max_duration_per_target'], dt)
    if acceptance['hold_for'] > duration:
        raise ValueError('Path hold_for exceeds max_duration_per_target.')
    for target in path_targets(targets):
        if not math.isfinite(target) or target <= 0:
            raise ValueError('Path contains an unrepresentable pressure target.')
    return (targets['intermediate_states'] + 2) * duration_steps(duration, dt)


def validate_condition(condition, depth=0):
    if depth > 20:
        raise ValueError('Conditions may nest at most 20 levels.')
    _mapping(condition, {'all', 'any', 'observable', 'op', 'value', 'atol', 'rtol', 'hold_for', 'min_duration'})
    for key in ('hold_for', 'min_duration'):
        _number(condition.get(key, 0), 0)
    groups = set(condition) & {'all', 'any'}
    if groups:
        if len(groups) != 1 or set(condition) - groups - {'hold_for', 'min_duration'}:
            raise ValueError('Use exactly one of all/any, without leaf condition keys.')
        children = condition[next(iter(groups))]
        if not isinstance(children, list) or not children:
            raise ValueError('all/any requires a nonempty condition list.')
        for child in children:
            validate_condition(child, depth + 1)
    else:
        if not isinstance(condition.get('observable'), str) or condition['observable'] not in OBSERVABLES or condition.get('op') not in ('above', 'below', 'near'):
            raise ValueError('Unknown observable or comparison operator.')
        _number(condition.get('value'))
        if condition['op'] == 'near':
            if not ({'atol', 'rtol'} & set(condition)):
                raise ValueError('near requires atol and/or rtol.')
            for key in ('atol', 'rtol'):
                _number(condition.get(key, 0), 0)
        elif {'atol', 'rtol'} & set(condition):
            raise ValueError('Tolerances are only supported by near.')


def condition_observables(condition):
    if 'observable' in condition:
        return {condition['observable']}
    return set().union(*(condition_observables(c) for c in condition.get('all', condition.get('any', []))))


def _target(value):
    if not isinstance(value, dict):
        _number(value, 0)
        return
    kind = value.get('type')
    if kind == 'ramp':
        _mapping(value, {'type', 'start', 'end', 'duration'}, {'type', 'start', 'end', 'duration'})
        _number(value['start'], 0)
        _number(value['end'], 0)
        _number(value['duration'], 0, True)
    elif kind == 'sine':
        _mapping(value, {'type', 'mean', 'amplitude', 'frequency', 'phase'}, {'type', 'mean', 'amplitude', 'frequency'})
        _number(value['mean'], 0)
        _number(value['amplitude'], 0)
        _number(value['frequency'], 0, True)
        _number(value.get('phase', 0))
        if value['amplitude'] > value['mean']:
            raise ValueError('Pressure sine must remain nonnegative.')
    else:
        raise ValueError('Target must be a number, ramp or sine.')


def validate_control(control):
    kind = control.get('type') if isinstance(control, dict) else None
    if kind == 'free_evolution':
        _mapping(control, {'type'}, {'type'})
    elif kind == 'strain_rate':
        _mapping(control, {'type', 'rate'}, {'type', 'rate'})
        if not isinstance(control['rate'], list) or len(control['rate']) != 3:
            raise ValueError('rate requires three strain rates in 1/s.')
        for value in control['rate']:
            _number(value)
    elif kind == 'density_continuation':
        # The time-step-dependent checks are performed by validate_protocol.
        _density_control(control, 0.0)
    elif kind == 'stress_servo':
        legacy = set(control) & {'gain', 'max_strain_rate'}
        if legacy:
            raise ValueError('stress_servo now uses max_velocity (m/s); remove gain and max_strain_rate.')
        _mapping(control, {'type', 'mode', 'target_pressure', 'target_stress', 'max_velocity', 'loading_factor', 'update_every_steps'}, {'type', 'mode'})
        mode = control['mode']
        if mode == 'isotropic' and 'target_pressure' in control and 'target_stress' not in control:
            _target(control['target_pressure'])
        elif mode == 'anisotropic' and 'target_stress' in control and 'target_pressure' not in control:
            values = control['target_stress']
            if not isinstance(values, list) or len(values) != 3:
                raise ValueError('target_stress requires normal stresses [xx, yy, zz].')
            for value in values:
                _target(value)
        else:
            raise ValueError('Use isotropic/target_pressure or anisotropic/target_stress.')
        _number(control.setdefault('max_velocity', DEFAULT_SERVO_MAX_VELOCITY), 0, True)
        _number(control.setdefault('loading_factor', DEFAULT_SERVO_LOADING_FACTOR), 0, True)
        _count(control.setdefault('update_every_steps', DEFAULT_SERVO_UPDATE_EVERY_STEPS))
    else:
        raise ValueError(f'Unknown controller: {kind!r}')


def validate_protocol(raw, dt, boundary):
    protocol = copy.deepcopy(raw)
    _mapping(protocol, {'stages', 'sample_every'}, {'stages'})
    _count(protocol.setdefault('sample_every', 100))

    def visit(stages, depth=0):
        if depth > 20 or not isinstance(stages, list) or not stages:
            raise ValueError('stages must be nonempty; maximum nesting depth is 20.')
        budget = 0
        for kind, _, stage in _pieces(stages):
            if 'name' in stage and (not isinstance(stage['name'], str) or not stage['name'].strip()):
                raise ValueError('Stage name must be nonempty text.')
            if 'friction' in stage and not isinstance(stage['friction'], bool):
                raise ValueError('Protocol friction must be true or false.')
            if kind == 'block':
                _mapping(stage, {'name', 'repeat', 'stages', 'friction'}, {'stages'})
                budget += _count(stage.get('repeat', 1)) * visit(stage['stages'], depth + 1)
                continue
            if kind == 'path':
                _mapping(stage, {'name', 'path', 'friction'}, {'path'})
                budget += validate_path(stage['path'], dt, boundary)
                continue
            _mapping(stage, {'name', 'control', 'until', 'max_duration', 'friction'}, {'control', 'until', 'max_duration'})
            control = stage['control']
            if isinstance(control, dict) and control.get('type') == 'density_continuation':
                _density_control(control, dt)
            else:
                validate_control(control)
            rates = control.get('rate', [])
            if any(abs(rate * dt) > 0.01 for rate in rates):
                raise ValueError('Controller permits more than 1% cell strain per step; reduce time_step or rate.')
            validate_condition(stage['until'])
            duration = _number(stage['max_duration'], dt)
            if stage['until'].get('min_duration', 0) > duration or stage['until'].get('hold_for', 0) > duration:
                raise ValueError('Condition duration exceeds stage max_duration.')
            required = condition_observables(stage['until'])
            if control['type'] == 'density_continuation':
                if (stage['until'] != {'observable': 'density_targets_completed',
                                       'op': 'above', 'value': 1}):
                    raise ValueError('density_continuation until must require its single density target.')
                if boundary != 'periodic':
                    raise ValueError('density_continuation requires periodic boundaries.')
                if (control['relaxation']['density_stability']['window'] > duration or
                        control['relaxation']['condition'].get('hold_for', 0) > duration or
                        control['relaxation']['condition'].get('min_duration', 0) > duration):
                    raise ValueError('Density stabilization durations exceed stage max_duration.')
            elif 'density_targets_completed' in required:
                raise ValueError('density_targets_completed is local to density_continuation.')
            if boundary != 'periodic' and (stage['control']['type'] != 'free_evolution' or required & (STRESS_OBSERVABLES | {'solid_fraction', 'bulk_density', 'normalized_kinetic_energy'})):
                raise ValueError('Cell control, stress and density conditions require periodic boundaries.')
            budget += duration_steps(duration, dt)
        return budget

    steps = visit(protocol['stages'])
    if steps > 2**53 or not math.isfinite(steps * dt):
        raise ValueError('Protocol step budget is too large.')
    return protocol, steps


def duration_steps(duration, dt):
    ratio = duration / dt
    if not math.isfinite(ratio) or ratio > 2**53:
        raise ValueError('Duration requires too many steps.')
    nearest = round(ratio)
    return max(1, nearest if math.isclose(ratio, nearest, rel_tol=0, abs_tol=1e-8) else math.ceil(ratio))


def _pieces(stages, prefix=''):
    """Classify protocol pieces once, preserving their structural paths."""
    if not isinstance(stages, list) or not stages:
        raise ValueError('stages must be a nonempty list.')
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            raise ValueError('Each stage must be a mapping.')
        path = f'{prefix}{index + 1}:{stage.get("name", "stage")}'
        kind = 'block' if 'stages' in stage else 'path' if 'path' in stage else 'stage'
        yield kind, path, stage


def walk_protocol(stages, prefix='', repetitions=1):
    """Visit unrepeated leaves with multiplicities, avoiding schedule expansion."""
    for kind, path, stage in _pieces(stages, prefix):
        if kind == 'block':
            yield from walk_protocol(stage['stages'], path + '/',
                                     repetitions * stage.get('repeat', 1))
        else:
            yield kind, path, stage, repetitions


def stage_count(stages):
    """Count leaf executions without expanding repeated blocks or paths."""
    return sum(repetitions * (stage['path']['targets']['intermediate_states'] + 2
                              if kind == 'path' else 1)
               for kind, _, stage, repetitions in walk_protocol(stages))


def path_target_count(stages):
    """Count accepted targets expected from a successful protocol."""
    return sum(repetitions * (stage['path']['targets']['intermediate_states'] + 2
                              if kind == 'path' else 1
                              if stage['control']['type'] == 'density_continuation' else 0)
               for kind, _, stage, repetitions in walk_protocol(stages))


def iter_stages(stages, prefix=''):
    for kind, path, stage in iter_stage_boundaries(stages, prefix):
        if kind == 'stage':
            yield path, stage


def uses_protocol_friction(stages):
    """Whether a sequence explicitly requests live contact friction updates."""
    return any('friction' in stage or
               (kind == 'block' and uses_protocol_friction(stage['stages']))
               for kind, _, stage in _pieces(stages))


def iter_stage_boundaries(stages, prefix='', friction=None):
    """Yield block boundaries and leaf stages lazily in execution order."""
    for kind, path, stage in _pieces(stages, prefix):
        selected_friction = stage.get('friction', friction)
        if kind == 'block':
            for cycle in range(stage.get('repeat', 1)):
                cycle_path = f'{path}[{cycle + 1}]'
                yield 'block_start', cycle_path, None
                yield from iter_stage_boundaries(stage['stages'], cycle_path + '/', selected_friction)
                yield 'block_end', cycle_path, None
        elif kind == 'path':
            for index, target in enumerate(path_targets(stage['path']['targets']), 1):
                leaf = pressure_path_stage(stage['path'], target, index)
                if selected_friction is not None:
                    leaf['_friction'] = selected_friction
                yield 'stage', f'{path}/target_{index:04d}', leaf
        else:
            yield 'stage', path, stage if selected_friction is None else dict(stage, _friction=selected_friction)


def required_observables(stages):
    result = set()
    for kind, _, stage, _ in walk_protocol(stages):
        if kind == 'path':
            # Every target uses the same condition structure and controller mode.
            path = stage['path']
            stage = pressure_path_stage(path, path['targets']['end'], 1)
        result |= condition_observables(stage['until']) - {'density_targets_completed'}
        control = stage['control']
        if control['type'] == 'density_continuation':
            result |= {'solid_fraction', 'unbalanced_force'} | STRESS_OBSERVABLES
            result |= condition_observables(control['relaxation']['condition'])
        elif control['type'] == 'stress_servo':
            result |= ({'pressure'} if control['mode'] == 'isotropic'
                       else {'stress_xx', 'stress_yy', 'stress_zz'})
    if 'normalized_kinetic_energy' in result:
        result |= {'kinetic_energy', 'pressure'}
    return result


def control_types(stages):
    return {(stage['path'] if kind == 'path' else stage)['control']['type']
            for kind, _, stage, _ in walk_protocol(stages)}


def required_actuator_commands(stages):
    commands = {'stress_servo': 'symmetric_wall_velocity',
                'density_continuation': 'symmetric_wall_velocity',
                'strain_rate': 'cell_strain_rate'}
    return {commands[kind] for kind in control_types(stages) if kind != 'free_evolution'}


def maximum_servo_velocity(stages):
    """Largest configured symmetric face velocity in a nested protocol."""
    result = 0.0
    for kind, _, stage, _ in walk_protocol(stages):
        control = (stage['path'] if kind == 'path' else stage)['control']
        if control['type'] == 'density_continuation':
            control = control['confinement']
        result = max(result, control.get('max_velocity', 0.0))
    return result


class Condition:
    def __init__(self, specification):
        self.spec = specification
        self.since = None
        self.children = [Condition(c) for c in specification.get('all', specification.get('any', []))]

    def evaluate(self, values, elapsed, dt):
        spec = self.spec
        epsilon = dt * 1e-7
        if self.children:
            matches = [child.evaluate(values, elapsed, dt) for child in self.children]
            matched = all(matches) if 'all' in spec else any(matches)
        else:
            if spec['observable'] == 'normalized_kinetic_energy' and spec['observable'] not in values:
                self.since = None
                return False
            value, target = values[spec['observable']], spec['value']
            if not math.isfinite(value):
                raise ValueError(f'Nonfinite observable: {spec["observable"]}')
            # Inclusive thresholds; temporal comparisons tolerate floating point rounding.
            tolerance = epsilon if spec['observable'] in ('time', 'stage_time') else 0
            if spec['op'] == 'above':
                matched = value + tolerance >= target
            elif spec['op'] == 'below':
                matched = value - tolerance <= target
            else:
                matched = abs(value - target) <= spec.get('atol', 0) + spec.get('rtol', 0) * abs(target)
        if not matched:
            self.since = None
            return False
        if self.since is None:
            self.since = elapsed
        return elapsed + epsilon >= spec.get('min_duration', 0) and elapsed - self.since + epsilon >= spec.get('hold_for', 0)


def target_value(target, elapsed):
    if not isinstance(target, dict):
        return target
    if target['type'] == 'ramp':
        return target['start'] + (target['end'] - target['start']) * min(1, elapsed / target['duration'])
    return target['mean'] + target['amplitude'] * math.sin(2 * math.pi * target['frequency'] * elapsed + target.get('phase', 0))


def free_evolution(control, values, elapsed, context):
    return NoActuation()


def strain_rate(control, values, elapsed, context):
    return CellStrainRate(tuple(control['rate']))


def stress_servo(control, values, elapsed, context):
    if not isinstance(context, dict):
        raise ValueError('Stress servo requires actuator context.')
    dt = _number(context.get('dt'), 0, True)
    diameter = _number(context.get('particle_diameter_d50'), 0, True)
    young = _number(context.get('young_modulus'), 0, True)
    if control['mode'] == 'isotropic':
        errors = [target_value(control['target_pressure'], elapsed) - values['pressure']] * 3
    else:
        errors = [target_value(target, elapsed) - values['stress_' + axis]
                  for axis, target in zip(('xx', 'yy', 'zz'), control['target_stress'])]
    coefficient = control['loading_factor'] * diameter / (dt * young)
    limit = control['max_velocity']
    velocities = [max(-limit, min(limit, coefficient * error)) for error in errors]
    return SymmetricWallVelocity(tuple(velocities))


CONTROLLERS = {'free_evolution': free_evolution, 'strain_rate': strain_rate, 'stress_servo': stress_servo}


class ProtocolRunner:
    """Lazy stage traversal; conditions sampled after every completed solver step."""
    def __init__(self, protocol, dt):
        self.dt = dt
        self.time = 0.0
        self.iterator = iter_stage_boundaries(protocol['stages'])
        self.pending_boundaries = []
        self.completed_stages = 0
        self.accepted_targets = 0
        self.failed_stage = None
        self.stage_exited = False
        self.steps = 0
        self.done = False
        self.failed = False
        self.stop_reason = None
        self.diagnostics = {}
        self.port = None
        self.manage_friction = uses_protocol_friction(protocol['stages'])
        self.original_friction = None
        self.density = None
        self._enter()

    def attach(self, port):
        """Attach a live solver after its own initialization has completed."""
        self.port = port
        if self.manage_friction:
            self.original_friction = port.friction()
            self._apply_friction()
        self._start_density()

    def _apply_friction(self):
        if self.original_friction is None:
            return
        pair = self.original_friction if self.stage.get('_friction', True) else (0.0, 0.0)
        if self.port.friction() != pair:
            self.port.set_friction(*pair)

    def _start_density(self):
        if self.port is None or self.stage['control']['type'] != 'density_continuation':
            return
        if __package__:
            from .density_continuation import DensityContinuation
        else:
            from density_continuation import DensityContinuation
        self.density = DensityContinuation(self.stage['control'], self.dt, self.port,
                                           self.path, self.start_step, self.start_time, self.limit)

    def _enter(self):
        while True:
            item = next(self.iterator, None)
            if item is None:
                self.done = True
                if self.original_friction is not None and self.port.friction() != self.original_friction:
                    self.port.set_friction(*self.original_friction)
                return
            kind, path, stage = item
            if kind == 'stage':
                self.path, self.stage = path, stage
                self._apply_friction()
                self._record_boundary('stage', 'start', path)
                break
            self._record_boundary('block', 'start' if kind == 'block_start' else 'end', path)
        self.start_step = self.steps
        self.start_time = self.time
        self.observables = required_observables([self.stage]) - {'time', 'stage_time', 'density_targets_completed'}
        self.condition = Condition(self.stage['until'])
        self.limit = duration_steps(self.stage['max_duration'], self.dt)
        self.density = None
        self._start_density()

    def _record_boundary(self, kind, phase, path, *, accepted=None, values=None):
        event = {'kind': kind, 'phase': phase, 'path': path,
                 'step': self.steps, 'time': self.time}
        if kind == 'stage' and self.manage_friction:
            event['friction'] = self.stage.get('_friction', True)
        if kind == 'stage' and ('_path_target' in self.stage or
                                self.stage['control']['type'] == 'density_continuation'):
            if '_path_target' in self.stage:
                event['target'] = self.stage['_path_target']
            if phase == 'end':
                event['accepted'] = accepted
                event['observables'] = values
                if self.density is not None:
                    event['cycles'] = self.density.cycles
                    event['failure'] = self.density.failure
        self.pending_boundaries.append(event)

    def take_boundaries(self):
        boundaries = self.pending_boundaries
        self.pending_boundaries = []
        return boundaries

    def act(self, values, context=None) -> ActuatorCommand:
        control = self.stage['control']
        if self.density is not None:
            return self.density.act(values, context, self.steps)
        if (control['type'] == 'stress_servo' and
                (self.steps - self.start_step + 1) % control['update_every_steps'] != 0):
            return NoActuation()
        return CONTROLLERS[control['type']](control, values, self.time - self.start_time, context)

    def advance(self, values):
        self.stage_exited = False
        self.steps += 1
        self.time = self.steps * self.dt
        elapsed = self.time - self.start_time
        values = dict(values, time=self.time, stage_time=elapsed)
        if self.density is not None:
            self.density.advance(values, self.steps, self.time)
            if self.density.accepted:
                self.accepted_targets += 1
            values['density_targets_completed'] = int(self.density.accepted)
            if self.density.done:
                self.stage_exited = True
                self.completed_stages += 1
                self._record_boundary('stage', 'end', self.path,
                                      accepted=self.density.failure is None, values=values)
                if self.density.failure is not None:
                    self.failed = self.done = True
                    self.failed_stage = self.path
                    self.stop_reason = self.density.failure
                    self.diagnostics = {
                        'target': self.density.control['target'],
                        'cycles': self.density.cycles,
                        'phase': self.density.phase,
                        'solid_fraction': values['solid_fraction'],
                    }
                else:
                    self._enter()
            return values
        reached = self.condition.evaluate(values, elapsed, self.dt)
        expired = self.steps - self.start_step >= self.limit
        if reached or expired:
            self.stage_exited = True
            self.completed_stages += 1
            self._record_boundary('stage', 'end', self.path, accepted=reached, values=values)
            if not reached:
                self.failed = self.done = True
                self.failed_stage = self.path
                self.stop_reason = 'max_duration'
            else:
                if '_path_target' in self.stage:
                    self.accepted_targets += 1
                self._enter()
        return values
