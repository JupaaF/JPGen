"""Density control by live zero-friction cycles, without solver restart."""
from collections import deque

if __package__:
    from .protocol import Condition, stress_servo
    from .commands import NoActuation
else:
    from protocol import Condition, stress_servo
    from commands import NoActuation


ZERO_FRICTION_STEPS = 100


class DensityContinuation:
    def __init__(self, control, dt, port, path, start_step, start_time, limit):
        self.control, self.dt, self.port, self.path = control, dt, port, path
        self.start_step, self.start_time, self.limit = start_step, start_time, limit
        self.normal_friction = port.friction()
        self.phase = 'initial'
        self.cycles = 0
        self.done = False
        self.failure = None
        self.accepted = False
        self._reset_observation(start_time)

    def _reset_observation(self, time):
        self.phase_start_time = time
        self.density_history = deque()
        self.equilibrium_since = None
        condition = dict(self.control['relaxation']['condition'])
        self.hold_for = condition.pop('hold_for', 0)
        self.condition = Condition(condition)

    def act(self, values, context, step):
        confinement = self.control['confinement']
        if (step - self.start_step + 1) % confinement['update_every_steps']:
            return NoActuation()
        servo = {'type': 'stress_servo', 'mode': 'isotropic',
                 **{key: confinement[key] for key in
                    ('target_pressure', 'max_velocity', 'loading_factor')}}
        return stress_servo(servo, values, step * self.dt - self.start_time, context)

    def _equilibrated(self, values, time):
        stability = self.control['relaxation']['density_stability']
        window = stability['window']
        self.density_history.append((time, values['solid_fraction']))
        while len(self.density_history) > 2 and self.density_history[1][0] <= time - window:
            self.density_history.popleft()
        stable = (len(self.density_history) >= 2 and
                  self.density_history[0][0] <= time - window + self.dt * 1e-7 and
                  max(value for _, value in self.density_history) -
                  min(value for _, value in self.density_history) <= stability['max_range'])
        confinement = self.control['confinement']
        relaxed = self.condition.evaluate(values, time - self.phase_start_time, self.dt)
        matched = (stable and relaxed and
                   abs(values['pressure'] - confinement['target_pressure']) <=
                   confinement['pressure_rtol'] * confinement['target_pressure'])
        if not matched:
            self.equilibrium_since = None
            return False
        if self.equilibrium_since is None:
            self.equilibrium_since = time
        return time - self.equilibrium_since + self.dt * 1e-7 >= self.hold_for

    def _metadata(self, values, step, time):
        return {'stage': self.path, 'index': 1, 'target': self.control['target'],
                'density_atol': self.control['density_atol'],
                'observables': dict(values), 'time': time, 'step': step,
                'cycles': self.cycles, 'static_friction': self.normal_friction[0],
                'dynamic_friction': self.normal_friction[1],
                'confinement': self.control['confinement'],
                'relaxation': self.control['relaxation']}

    def advance(self, values, step, time):
        expired = step - self.start_step >= self.limit
        if self.phase == 'zero':
            if step - self.zero_start_step >= ZERO_FRICTION_STEPS:
                self.port.set_friction(*self.normal_friction)
                self.phase = 'normal'
                self._reset_observation(time)
        elif self._equilibrated(values, time):
            if values['solid_fraction'] + self.control['density_atol'] >= self.control['target']:
                self.port.publish_target(self._metadata(values, step, time))
                self.accepted = self.done = True
                return
            if not expired:
                # Commit the stable normal-friction state BEFORE changing physics.
                self.cycles += 1
                self.port.checkpoint(self._metadata(values, step, time))
                self.port.set_friction(0.0, 0.0)
                self.phase = 'zero'
                self.zero_start_step = step
        if expired:
            self.port.set_friction(*self.normal_friction)
            self.failure = 'max_duration'
            self.done = True
