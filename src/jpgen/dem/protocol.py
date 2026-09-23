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

OBSERVABLES = {'time', 'stage_time', 'kinetic_energy', 'unbalanced_force', 'solid_fraction', 'bulk_density',
               'pressure', 'stress_xx', 'stress_yy', 'stress_zz', 'stress_xy', 'stress_xz', 'stress_yz'}
STRESS_OBSERVABLES = {name for name in OBSERVABLES if name.startswith('stress_')} | {'pressure'}
CONTACT_OBSERVABLES = STRESS_OBSERVABLES | {'unbalanced_force'}

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
        for stage in stages:
            if not isinstance(stage, dict):
                raise ValueError('Each stage must be a mapping.')
            if 'name' in stage and (not isinstance(stage['name'], str) or not stage['name'].strip()):
                raise ValueError('Stage name must be nonempty text.')
            if 'stages' in stage:
                _mapping(stage, {'name', 'repeat', 'stages'}, {'stages'})
                budget += _count(stage.get('repeat', 1)) * visit(stage['stages'], depth + 1)
                continue
            _mapping(stage, {'name', 'control', 'until', 'max_duration'}, {'control', 'until', 'max_duration'})
            validate_control(stage['control'])
            control = stage['control']
            rates = control.get('rate', [])
            if any(abs(rate * dt) > 0.01 for rate in rates):
                raise ValueError('Controller permits more than 1% cell strain per step; reduce time_step or rate.')
            validate_condition(stage['until'])
            duration = _number(stage['max_duration'], dt)
            if stage['until'].get('min_duration', 0) > duration or stage['until'].get('hold_for', 0) > duration:
                raise ValueError('Condition duration exceeds stage max_duration.')
            required = condition_observables(stage['until'])
            if boundary != 'periodic' and (stage['control']['type'] != 'free_evolution' or required & (STRESS_OBSERVABLES | {'solid_fraction', 'bulk_density'})):
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


def stage_count(stages):
    """Count leaf executions without expanding repeated blocks."""
    return sum((stage.get('repeat', 1) * stage_count(stage['stages'])
                if 'stages' in stage else 1) for stage in stages)


def iter_stages(stages, prefix=''):
    for index, stage in enumerate(stages):
        path = f'{prefix}{index + 1}:{stage.get("name", "stage")}'
        if 'stages' in stage:
            for cycle in range(stage.get('repeat', 1)):
                yield from iter_stages(stage['stages'], f'{path}[{cycle + 1}]/')
        else:
            yield path, stage


def iter_stage_boundaries(stages, prefix=''):
    """Yield block boundaries and leaf stages in execution order."""
    for index, stage in enumerate(stages):
        path = f'{prefix}{index + 1}:{stage.get("name", "stage")}'
        if 'stages' in stage:
            for cycle in range(stage.get('repeat', 1)):
                cycle_path = f'{path}[{cycle + 1}]'
                yield 'block_start', cycle_path, None
                yield from iter_stage_boundaries(stage['stages'], cycle_path + '/')
                yield 'block_end', cycle_path, None
        else:
            yield 'stage', path, stage


def required_observables(stages):
    result = set()
    for stage in stages:
        if 'stages' in stage:
            result |= required_observables(stage['stages'])
        else:
            result |= condition_observables(stage['until'])
            if stage['control']['type'] == 'stress_servo':
                result |= ({'pressure'} if stage['control']['mode'] == 'isotropic'
                           else {'stress_xx', 'stress_yy', 'stress_zz'})
    return result


def control_types(stages):
    result = set()
    for stage in stages:
        if 'stages' in stage:
            result |= control_types(stage['stages'])
        else:
            result.add(stage['control']['type'])
    return result


def required_actuator_commands(stages):
    commands = {'stress_servo': 'symmetric_wall_velocity',
                'strain_rate': 'cell_strain_rate'}
    return {commands[kind] for kind in control_types(stages) if kind != 'free_evolution'}


def maximum_servo_velocity(stages):
    """Largest configured symmetric face velocity in a nested protocol."""
    result = 0.0
    for stage in stages:
        if 'stages' in stage:
            result = max(result, maximum_servo_velocity(stage['stages']))
        elif stage['control']['type'] == 'stress_servo':
            result = max(result, stage['control']['max_velocity'])
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
        self.failed_stage = None
        self.stage_exited = False
        self.steps = 0
        self.done = False
        self.failed = False
        self._enter()

    def _enter(self):
        while True:
            item = next(self.iterator, None)
            if item is None:
                self.done = True
                return
            kind, path, stage = item
            if kind == 'stage':
                self.path, self.stage = path, stage
                self._record_boundary('stage', 'start', path)
                break
            self._record_boundary('block', 'start' if kind == 'block_start' else 'end', path)
        self.start_step = self.steps
        self.start_time = self.time
        self.observables = required_observables([self.stage]) - {'time', 'stage_time'}
        self.condition = Condition(self.stage['until'])
        self.limit = duration_steps(self.stage['max_duration'], self.dt)

    def _record_boundary(self, kind, phase, path):
        self.pending_boundaries.append({
            'kind': kind, 'phase': phase, 'path': path,
            'step': self.steps, 'time': self.time,
        })

    def take_boundaries(self):
        boundaries = self.pending_boundaries
        self.pending_boundaries = []
        return boundaries

    def act(self, values, context=None) -> ActuatorCommand:
        control = self.stage['control']
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
        reached = self.condition.evaluate(values, elapsed, self.dt)
        expired = self.steps - self.start_step >= self.limit
        if reached or expired:
            self.stage_exited = True
            self.completed_stages += 1
            self._record_boundary('stage', 'end', self.path)
            if not reached:
                self.failed = self.done = True
                self.failed_stage = self.path
            else:
                self._enter()
        return values
