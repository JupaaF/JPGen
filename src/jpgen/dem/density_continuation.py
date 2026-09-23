"""Stateful friction continuation for a periodic DEM cell.

The port owns solver checkpoints and publication. All decisions use observations
from completed steps; rejected branches consume work but restore physical time.
"""
from collections import deque
import math

if __package__:
    from .protocol import Condition, stress_servo
    from .commands import NoActuation
else:
    from protocol import Condition, stress_servo
    from commands import NoActuation


class DensityContinuation:
    def __init__(self, control, dt, port, path, start_step, start_time, work_limit,
                 start_accepted_targets, start_published_targets):
        self.control = control
        self.dt = dt
        self.port = port
        self.path = path
        self.start_step = start_step
        self.start_time = start_time
        self.work_limit = work_limit
        self.work_steps = 0
        self.start_accepted_targets = start_accepted_targets
        self.start_published_targets = start_published_targets
        self.discarded_attempts = 0
        self.target_discarded_attempts = 0
        self.factor = 1.0
        self.static_entry, self.dynamic_entry = port.friction()
        if not self.static_entry and not self.dynamic_entry:
            raise ValueError('Density continuation requires nonzero entry friction.')
        self.target_index = 0
        self.attempts = 0
        self.retries = 0
        self.attempt_id = None
        self.mode = 'initial'
        self.attempt_start_step = start_step
        self.attempt_start_time = start_time
        self.increment = control['friction']['initial_decrement']
        self.last_successful_decrement = None
        self.previous_point = None
        self.base_point = None
        self.base_checkpoint = None
        self.density_history = deque()
        self.equilibrium_since = None
        self.target_since = None
        condition = dict(control['relaxation']['condition'])
        self.hold_for = condition.pop('hold_for', 0)
        self.condition = Condition(condition)
        self.done = False
        self.failure = None
        self.last_interval = None
        self.transient_crossings = 0

    def state(self):
        """Portable continuation state recorded beside each native checkpoint."""
        def condition_state(condition):
            return {'since': condition.since,
                    'children': [condition_state(child) for child in condition.children]}

        return {
            'stage': self.path, 'mode': self.mode, 'target_index': self.target_index,
            'factor': self.factor, 'entry_friction': [self.static_entry, self.dynamic_entry],
            'attempts': self.attempts, 'retries': self.retries, 'attempt_id': self.attempt_id,
            'discarded_attempts': self.discarded_attempts,
            'target_discarded_attempts': self.target_discarded_attempts,
            'start_accepted_targets': self.start_accepted_targets,
            'start_published_targets': self.start_published_targets,
            'increment': self.increment,
            'last_successful_decrement': self.last_successful_decrement,
            'previous_point': self.previous_point, 'base_point': self.base_point,
            'attempt_start_step': self.attempt_start_step,
            'attempt_start_time': self.attempt_start_time,
            'work_steps': self.work_steps, 'equilibrium_since': self.equilibrium_since,
            'target_since': self.target_since,
            'density_history': list(self.density_history),
            'condition': condition_state(self.condition),
            'transient_crossings': self.transient_crossings,
            'last_interval': self.last_interval,
        }

    @property
    def attempted_duration(self):
        return self.work_steps * self.dt

    def _reset_observation(self):
        self.density_history.clear()
        self.equilibrium_since = None
        self.target_since = None
        condition = dict(self.control['relaxation']['condition'])
        condition.pop('hold_for', None)
        self.condition = Condition(condition)

    def act(self, values, context, physical_step):
        confinement = self.control['confinement']
        if (physical_step - self.attempt_start_step + 1) % confinement['update_every_steps']:
            return NoActuation()
        servo = {'type': 'stress_servo', 'mode': 'isotropic',
                 'target_pressure': confinement['target_pressure'],
                 'max_velocity': confinement['max_velocity'],
                 'loading_factor': confinement['loading_factor']}
        return stress_servo(servo, values, physical_step * self.dt - self.start_time, context)

    def _stable(self, time, phi):
        window = self.control['relaxation']['density_stability']['window']
        self.density_history.append((time, phi))
        while len(self.density_history) > 2 and self.density_history[1][0] <= time - window:
            self.density_history.popleft()
        if len(self.density_history) < 2 or self.density_history[0][0] > time - window + self.dt * 1e-7:
            return False
        values = [value for _, value in self.density_history]
        return max(values) - min(values) <= self.control['relaxation']['density_stability']['max_range']

    def _equilibrated(self, values, time):
        phi = values['solid_fraction']
        pressure = self.control['confinement']
        stable = self._stable(time, phi)
        elapsed = time - self.attempt_start_time
        relaxed = self.condition.evaluate(values, elapsed, self.dt)
        matched = (stable and relaxed and
                   abs(values['pressure'] - pressure['target_pressure']) <=
                   pressure['pressure_rtol'] * pressure['target_pressure'])
        self.equilibrium_since = time if matched and self.equilibrium_since is None else self.equilibrium_since if matched else None
        return matched and time - self.equilibrium_since + self.dt * 1e-7 >= self.hold_for

    def _target_ready(self, values, time):
        target = self.control['targets'][self.target_index]
        matched = (self.equilibrium_since is not None and
                   abs(values['solid_fraction'] - target) <= self.control['density_atol'])
        self.target_since = time if matched and self.target_since is None else self.target_since if matched else None
        return matched and time - self.target_since + self.dt * 1e-7 >= self.hold_for

    def _fail(self, reason):
        self.done = True
        self.failure = reason
        return {'failure': reason}

    def _checkpoint(self, physical_step, time, values):
        self.base_point = (self.factor, values['solid_fraction'], physical_step, time)
        self.base_checkpoint = self.port.checkpoint(self.path, physical_step, time, values)

    def _next_increment(self, phi):
        friction = self.control['friction']
        proposed = self.last_successful_decrement or friction['initial_decrement']
        if self.previous_point is not None:
            old_factor, old_phi = self.previous_point
            difference = old_factor - self.factor
            slope = (phi - old_phi) / difference if difference > 1e-15 else 0.0
            if math.isfinite(slope) and slope > 1e-12:
                proposed = friction['safety_factor'] * (self.control['targets'][self.target_index] - phi) / slope
                proposed = max(friction['min_decrement'], min(proposed, friction['max_decrement']))
                if self.last_successful_decrement is not None:
                    proposed = min(proposed, friction['growth_factor'] * self.last_successful_decrement)
            elif math.isfinite(slope) and slope < 0:
                self.port.log_attempt({'stage': self.path, 'event': 'non_monotone_response',
                                       'target_index': self.target_index + 1, 'slope': slope,
                                       'attempted_duration': self.attempted_duration})
        return max(friction['min_decrement'], min(proposed, friction['max_decrement']))

    def _begin_attempt(self, physical_step, time, decrement=None):
        friction = self.control['friction']
        remaining = self.factor - friction['min_factor']
        if remaining <= 0:
            return self._fail('friction_limit')
        if self.attempts >= self.control['limits']['max_attempts']:
            return self._fail('attempt_limit')
        proposed = self._next_increment(self.base_point[1]) if decrement is None else decrement
        if proposed < friction['min_decrement'] and remaining > proposed:
            return self._fail('resolution_limit')
        self.increment = min(proposed, remaining)
        self.factor -= self.increment
        self.port.set_friction(self.static_entry * self.factor, self.dynamic_entry * self.factor)
        self.attempts += 1
        self.attempt_id = self.attempts
        self.mode = 'attempt'
        self.attempt_start_step = physical_step
        self.attempt_start_time = time
        self._reset_observation()
        self.port.log_attempt({'stage': self.path, 'event': 'start', 'attempt': self.attempt_id,
                               'target_index': self.target_index + 1, 'factor': self.factor,
                               'decrement': self.increment, 'time': time,
                               'attempted_duration': self.attempted_duration})
        return {}

    def _accept_attempt(self, values, physical_step, time):
        phi = values['solid_fraction']
        old_factor, old_phi, _, _ = self.base_point
        self.port.log_attempt({'stage': self.path, 'event': 'accepted', 'attempt': self.attempt_id,
                               'target_index': self.target_index + 1, 'factor': self.factor,
                               'solid_fraction': phi, 'time': time,
                               'attempted_duration': self.attempted_duration})
        self.previous_point = (old_factor, old_phi)
        self.last_successful_decrement = self.increment
        self.retries = 0
        self.mode = 'ready'
        self._checkpoint(physical_step, time, values)

    def _accept_target(self, values, physical_step, time):
        target = self.control['targets'][self.target_index]
        prior_point = self.base_point[:2] if self.base_point is not None else None
        was_attempt = self.mode == 'attempt'
        self.target_index += 1
        target_retries = self.target_discarded_attempts
        self.retries = 0
        self.target_discarded_attempts = 0
        if was_attempt:
            self.previous_point = prior_point
            self.last_successful_decrement = self.increment
        self.mode = 'ready'
        self._reset_observation()
        self._checkpoint(physical_step, time, values)
        metadata = {'stage': self.path, 'index': self.target_index, 'target': target,
                    'observables': dict(values), 'factor': self.factor,
                    'static_friction': self.static_entry * self.factor,
                    'dynamic_friction': self.dynamic_entry * self.factor,
                    'time': time, 'step': physical_step,
                    'attempted_duration': self.attempted_duration, 'attempts': self.attempts,
                    'retries': target_retries, 'discarded_attempts': self.discarded_attempts, 'density_atol': self.control['density_atol'],
                    'pressure_rtol': self.control['confinement']['pressure_rtol'],
                    'relaxation': self.control['relaxation'],
                    'limits': self.control['limits'],
                    'target_count': len(self.control['targets']),
                    'overlap_metrics': 'unavailable'}
        self.port.publish_target(self.base_checkpoint, metadata)
        self.port.log_attempt({'stage': self.path, 'event': 'accepted_target',
                               'attempt': self.attempt_id, 'target_index': self.target_index,
                               'factor': self.factor, 'solid_fraction': values['solid_fraction'],
                               'time': time, 'attempted_duration': self.attempted_duration})
        if self.target_index == len(self.control['targets']):
            self.done = True
            return {'accepted_target': metadata, 'complete': True}
        return {'accepted_target': metadata}

    def _discard(self, reason):
        self.port.log_attempt({'stage': self.path, 'event': 'discarded', 'attempt': self.attempt_id,
                               'reason': reason, 'target_index': self.target_index + 1,
                               'factor': self.factor, 'attempted_duration': self.attempted_duration})
        attempted = self.increment
        self.retries += 1
        self.discarded_attempts += 1
        self.target_discarded_attempts += 1
        if self.retries > self.control['limits']['max_retries_per_increment']:
            return self._fail('relaxation_failed' if reason == 'relaxation_failed' else 'resolution_limit')
        decrement = attempted * self.control['friction']['retry_factor']
        if decrement < self.control['friction']['min_decrement']:
            return self._fail('resolution_limit')
        physical_step, time = self.base_point[2:]
        self.factor = self.base_point[0]
        self.mode = 'ready'
        self._reset_observation()
        self.port.restore(self.base_checkpoint)
        # The port may replace its solver after this step; the checkpoint already
        # contains the preceding contact parameters.
        outcome = self._begin_attempt(physical_step, time, decrement)
        return outcome | {'restore': (physical_step, time)}

    def advance(self, values, physical_step, time):
        self.work_steps += 1
        phi = values['solid_fraction']
        target = self.control['targets'][self.target_index]
        atol = self.control['density_atol']
        if self.mode == 'attempt' and self.base_point is not None:
            previous_phi = self.density_history[-1][1] if self.density_history else self.base_point[1]
            if (previous_phi - target) * (phi - target) <= 0 and previous_phi != phi:
                self.transient_crossings += 1
                self.port.log_attempt({'stage': self.path, 'event': 'transient_crossing',
                                       'attempt': self.attempt_id, 'target_index': self.target_index + 1,
                                       'solid_fraction': phi, 'time': time,
                                       'attempted_duration': self.attempted_duration})
        equilibrated = self._equilibrated(values, time)
        target_ready = self._target_ready(values, time)
        if self.mode == 'initial':
            if equilibrated:
                if phi > target + atol:
                    outcome = self._fail('target_below_initial_density')
                elif abs(phi - target) <= atol:
                    outcome = self._accept_target(values, physical_step, time) if target_ready else {}
                    if target_ready and not self.done:
                        outcome |= self._begin_attempt(physical_step, time)
                else:
                    self.mode = 'ready'
                    self._checkpoint(physical_step, time, values)
                    outcome = self._begin_attempt(physical_step, time)
            elif physical_step - self.attempt_start_step >= self.control['relaxation']['max_duration'] / self.dt - 1e-8:
                outcome = self._fail('relaxation_failed')
            else:
                outcome = {}
        elif self.mode == 'attempt':
            if equilibrated:
                if phi > target + atol:
                    self.last_interval = [self.base_point[1], phi]
                    outcome = self._discard('overshoot')
                elif target_ready:
                    outcome = self._accept_target(values, physical_step, time)
                    if not self.done:
                        outcome |= self._begin_attempt(physical_step, time)
                elif phi < target - atol:
                    self._accept_attempt(values, physical_step, time)
                    outcome = self._begin_attempt(physical_step, time)
                else:
                    outcome = {}
            elif physical_step - self.attempt_start_step >= self.control['relaxation']['max_duration'] / self.dt - 1e-8:
                outcome = self._discard('relaxation_failed')
            else:
                outcome = {}
        else:
            outcome = self._begin_attempt(physical_step, time)
        if not self.done and self.work_steps >= self.work_limit:
            outcome = self._fail('max_duration')
        if self.failure:
            outcome['failure'] = self.failure
            outcome['last_interval'] = self.last_interval
        return outcome
