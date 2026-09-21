"""Bounded adaptive stepping; standard-library code copied into solver cases.

Estimates constrain stability and motion, not local truncation error. No rejected
step is replayed. Physical-time boundaries may require a step below min_step.
"""
import math


def validate_time_step(raw):
    if not isinstance(raw, dict):
        return _positive(raw, 'time_step'), None
    allowed = {'mode', 'initial', 'min', 'max', 'safety_factor', 'growth_factor',
               'max_displacement_fraction', 'max_cell_strain'}
    if set(raw) - allowed or raw.get('mode') != 'adaptive' or 'max' not in raw:
        raise ValueError('time_step requires mode: adaptive, max, and only supported adaptive options.')
    result = dict(raw)
    maximum = _positive(result['max'], 'time_step.max')
    defaults = {'min': min(1e-8, maximum), 'initial': min(1e-6, maximum),
                'safety_factor': 0.1, 'growth_factor': 1.05,
                'max_displacement_fraction': 0.05, 'max_cell_strain': 0.001}
    for name, default in defaults.items():
        result[name] = _positive(result.get(name, default), 'time_step.' + name)
    if not result['min'] <= result['initial'] <= maximum:
        raise ValueError('Require time_step.min <= initial <= max.')
    if result['safety_factor'] > 0.5 or not 1 <= result['growth_factor'] <= 2:
        raise ValueError('safety_factor must be <= 0.5; growth_factor must be between 1 and 2.')
    if result['max_displacement_fraction'] > 0.1 or result['max_cell_strain'] > 0.01:
        raise ValueError('max_displacement_fraction must be <= 0.1; max_cell_strain must be <= 0.01.')
    return result['initial'], result


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be finite and positive.')
    return float(value)


def rayleigh_time(radius, density, young, poisson):
    shear = young / (2 * (1 + poisson))
    return math.pi * radius * math.sqrt(density / shear) / (0.1631 * poisson + 0.8766)


def motion_time(distance, speed, acceleration):
    """Bound speed*dt + 0.5*acceleration*dt**2 by distance."""
    if acceleration > 0:
        return 2 * distance / (speed + math.sqrt(speed * speed + 2 * acceleration * distance))
    return distance / speed if speed > 0 else math.inf


class AdaptiveTimeStep:
    def __init__(self, settings):
        self.settings = settings
        self.previous = settings['initial']
        self.count = 0
        self.minimum = math.inf
        self.maximum = 0.0
        self.reductions = 0
        self.increases = 0
        self.boundary_steps = 0
        self.reasons = {}
        self.last_dt = None

    def choose(self, estimates, remaining):
        """Estimates are already safety-scaled positive times from the adapter."""
        limits = dict(estimates, maximum=self.settings['max'])
        for name, value in limits.items():
            if math.isnan(value) or value <= 0:
                raise ValueError(f'Invalid adaptive time-step estimate {name}: {value}')
        reason = min(limits, key=limits.get)
        safe = limits[reason]
        if safe < self.settings['min']:
            raise ValueError(f'Adaptive time step {safe:.9g} s required by {reason} is below min '
                             f'{self.settings["min"]:.9g} s; refusing an unsafe step.')
        growth = self.previous * self.settings['growth_factor'] if self.count else self.previous
        nominal = min(safe, growth)
        if nominal < safe:
            reason = 'growth_limit' if self.count else 'initial'
        self.previous = nominal  # Boundary clipping must not cause spurious slow regrowth.
        if not math.isfinite(remaining) or remaining <= 0:
            raise ValueError('Adaptive stepping requires a positive remaining physical duration.')
        dt = min(nominal, remaining)
        if dt < nominal:
            reason = 'time_boundary'
            self.boundary_steps += 1
        if self.last_dt is not None:
            self.reductions += dt < self.last_dt
            self.increases += dt > self.last_dt
        self.last_dt = dt
        self.minimum = min(self.minimum, dt)
        self.maximum = max(self.maximum, dt)
        self.count += 1
        self.reasons[reason] = self.reasons.get(reason, 0) + 1
        return dt, {'dt': dt, 'limiter': reason,
                    'limits': {key: value for key, value in limits.items() if math.isfinite(value)}}

    def summary(self):
        return {'mode': 'adaptive', 'steps': self.count, 'min_used': self.minimum if self.count else None,
                'max_used': self.maximum, 'reductions': self.reductions, 'increases': self.increases,
                'boundary_steps': self.boundary_steps, 'limiter_counts': self.reasons,
                'settings': self.settings}
