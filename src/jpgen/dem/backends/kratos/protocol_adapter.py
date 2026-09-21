"""Kratos cell actuation and observations for the standalone protocol worker."""
import math

import numpy as np
import KratosMultiphysics as KM
import KratosMultiphysics.DEMApplication as DEM

from timestep import rayleigh_time
from commands import ActuatorCommand, NoActuation, CellStrainRate, SymmetricWallVelocity

from protocol import STRESS_OBSERVABLES, required_observables


class KratosProtocolAdapter:
    def __init__(self, analysis, execution):
        self.analysis = analysis
        self.density = execution['density']
        self.physics = DEM.SphericElementGlobalPhysicsCalculator(analysis.spheres_model_part)
        # Current cases preserve particle population and radii throughout the run.
        self.solid_volume = self.physics.CalculateTotalVolume(analysis.spheres_model_part)
        self.execution = execution
        self.needs_contacts = bool(execution.get('adaptive'))
        self.periodic = execution['boundary'] == 'periodic'
        self.needs_stress = bool(required_observables((execution.get('protocol') or {'stages': []})['stages']) & STRESS_OBSERVABLES)

    def box(self):
        origin = [getattr(self.analysis, f'BoundingBoxMin{axis}_update') for axis in 'XYZ']
        lengths = [getattr(self.analysis, f'BoundingBoxMax{axis}_update') - low for axis, low in zip('XYZ', origin)]
        return {'origin': origin, 'lengths': lengths, 'periodic': self.periodic}

    def control_context(self, dt):
        return {'dt': dt, 'particle_diameter_d50': self.execution['particle_diameter_d50'],
                'young_modulus': self.execution['young_modulus']}

    def _cell_kinematics(self, command: ActuatorCommand, dt: float):
        if isinstance(command, NoActuation):
            return [0.0] * 3, [1.0] * 3, [0.0] * 3
        if not isinstance(command, (CellStrainRate, SymmetricWallVelocity)):
            raise ValueError(f'Unsupported actuator command: {command!r}')
        values = command.values
        lengths = self.box()['lengths']
        if isinstance(command, CellStrainRate):
            scales = [math.exp(rate * dt) for rate in values]
            velocities = [(length - length * scale) / (2 * dt)
                          for length, scale in zip(lengths, scales)]
        elif isinstance(command, SymmetricWallVelocity):
            velocities = values
            scales = [(length - 2 * velocity * dt) / length
                      for length, velocity in zip(lengths, velocities)]
        if any(scale <= 0 or not math.isfinite(scale) for scale in scales):
            raise ValueError('Cell actuator command collapses or inverts the periodic cell.')
        rates = [math.log(scale) / dt for scale in scales]
        return velocities, scales, rates

    def apply(self, command: ActuatorCommand, dt: float) -> None:
        velocities, scales, rates = self._cell_kinematics(command, dt)
        if isinstance(command, NoActuation) or not any(command.values):
            return
        if not self.periodic:
            raise ValueError('Cell deformation requires periodic boundaries.')
        if any(abs(rate * dt) > 0.01 for rate in rates):
            raise ValueError('Cell strain per step exceeds 1%; reduce time_step or the controller limit.')
        box = self.box()
        lengths = box['lengths']
        new_lengths = [length * scale for length, scale in zip(lengths, scales)]
        max_radius = max(node.GetSolutionStepValue(KM.RADIUS) for node in self.analysis.spheres_model_part.Nodes)
        if min(new_lengths) <= 4 * max_radius:
            raise ValueError('Periodic cell must remain larger than twice the largest particle diameter.')
        centers = [low + length / 2 for low, length in zip(box['origin'], lengths)]
        # Move both faces symmetrically, keeping one live C++ strategy and contact history.
        self.analysis.UpdateSearchStartegyAndCPlusPlusStrategy(velocities)
        self.analysis.procedures.UpdateBoundingBox(self.analysis.spheres_model_part,
                                                  self.analysis.creator_destructor, velocities)
        for node in self.analysis.spheres_model_part.Nodes:
            coordinates = [node.X, node.Y, node.Z]
            displacement = node.GetSolutionStepValue(KM.DISPLACEMENT)
            for i in range(3):
                change = (coordinates[i] - centers[i]) * (scales[i] - 1)
                coordinates[i] += change
                displacement[i] += change
            node.X, node.Y, node.Z = coordinates
            node.SetSolutionStepValue(KM.DISPLACEMENT, displacement)

    def observe(self):
        particles = self.analysis.spheres_model_part
        energy = (self.physics.CalculateTranslationalKinematicEnergy(particles)
                  + self.physics.CalculateRotationalKinematicEnergy(particles))
        result = {'kinetic_energy': energy}
        if self.periodic:
            fraction = self.solid_volume / math.prod(self.box()['lengths'])
            result.update(solid_fraction=fraction, bulk_density=self.density * fraction)
        if self.needs_stress:
            self.analysis._GetSolver().PrepareContactElementsForPrinting()
            stress = self.analysis.MeasureSphereForGettingGlobalStressTensor()
            for i, j, suffix in ((0, 0, 'xx'), (1, 1, 'yy'), (2, 2, 'zz'), (0, 1, 'xy'), (0, 2, 'xz'), (1, 2, 'yz')):
                result['stress_' + suffix] = float(stress[i][j])
            result['pressure'] = sum(result['stress_' + axis] for axis in ('xx', 'yy', 'zz')) / 3
        if not all(math.isfinite(value) for value in result.values()):
            raise ValueError('Nonfinite DEM observable.')
        return result


    def timestep_limits(self, command: ActuatorCommand, control: dict, dt: float) -> dict:
        """Re-evaluate Rayleigh, Hertz network, motion and imposed-strain estimates.

        Contact geometry comes from Kratos' most recent neighbour search. The
        Rayleigh and displacement bounds also protect contact formation between
        searches. Hertz stiffness uses a conservative predicted overlap increment.
        This is an estimator, not a mathematical error/stability guarantee.
        """
        settings = self.execution['adaptive']
        _, _, rates = self._cell_kinematics(command, dt)
        safety = settings['safety_factor']
        nodes = list(self.analysis.spheres_model_part.Nodes)
        indices = {node.Id: index for index, node in enumerate(nodes)}
        radius = np.array([node.GetSolutionStepValue(KM.RADIUS) for node in nodes])
        mass = 4 * math.pi / 3 * self.density * radius**3
        positions = np.array([[node.X, node.Y, node.Z] for node in nodes])
        velocity = np.array([list(node.GetSolutionStepValue(KM.VELOCITY)) for node in nodes])
        spin = np.array([list(node.GetSolutionStepValue(KM.ANGULAR_VELOCITY)) for node in nodes])
        force = np.array([list(node.GetSolutionStepValue(KM.TOTAL_FORCES)) for node in nodes])
        moment = np.array([list(node.GetSolutionStepValue(DEM.PARTICLE_MOMENT)) for node in nodes])
        young, poisson = self.execution['young_modulus'], self.execution['poisson_ratio']
        limits = {'rayleigh': safety * rayleigh_time(float(radius.min()), self.density, young, poisson)}
        speed = np.linalg.norm(velocity, axis=1) + radius * np.linalg.norm(spin, axis=1)
        if self.periodic:
            box = self.box()
            center = np.array(box['origin']) + np.array(box['lengths']) / 2
            speed += np.linalg.norm((positions - center) * rates, axis=1)
        acceleration = np.linalg.norm(force, axis=1) / mass + 2.5 * np.linalg.norm(moment, axis=1) / (mass * radius)
        acceleration += math.sqrt(sum(g*g for g in self.execution['gravity']))
        displacement = settings['max_displacement_fraction'] * radius
        denominator = speed + np.sqrt(speed**2 + 2 * acceleration * displacement)
        with np.errstate(divide='ignore', invalid='ignore'):
            motion_limits = np.where(denominator > 0, 2 * displacement / denominator, np.inf)
        limits['particle_motion'] = float(motion_limits.min())
        max_rate = max(abs(rate) for rate in rates)
        limits['cell_strain'] = settings['max_cell_strain'] / max_rate if max_rate else math.inf
        pairs = []
        for element in self.analysis.contact_model_part.Elements:
            geometry = element.GetGeometry()
            pairs.append((indices[geometry[0].Id], indices[geometry[1].Id]))
        limits['hertz_contacts'] = math.inf
        if pairs:
            pairs = np.array(pairs, dtype=np.int64)
            a, b = pairs[:, 0], pairs[:, 1]
            branch = positions[a] - positions[b]
            if self.periodic:
                lengths = np.array(self.box()['lengths'])
                branch -= lengths * np.rint(branch / lengths)
            distances = np.linalg.norm(branch, axis=1)
            # Include a worst-case approach over a motion-limited next step.
            approach = settings['max_displacement_fraction'] * (radius[a] + radius[b])
            approach += settings['max_cell_strain'] * distances if max_rate else 0
            overlap = np.maximum(0, radius[a] + radius[b] - distances + approach)
            equivalent_radius = radius[a] * radius[b] / (radius[a] + radius[b])
            equivalent_young = young / (2 * (1 - poisson**2))
            shear = young / (2 * (1 + poisson))
            equivalent_shear = shear / (2 * (2 - poisson))
            normal = 2 * equivalent_young * np.sqrt(equivalent_radius * overlap)
            tangential = 4 * equivalent_shear * normal / equivalent_young
            # Conservative translational/rotational coupling allowance for spheres.
            stiffness = normal + 7 * tangential
            total = np.bincount(a, weights=stiffness, minlength=len(nodes))
            total += np.bincount(b, weights=stiffness, minlength=len(nodes))
            frequency_squared = float(np.max(2 * total / mass))
            if frequency_squared > 0:
                log_e = math.log(max(self.execution['restitution'], 1e-6))
                damping_ratio = -log_e / math.sqrt(math.pi**2 + log_e**2)
                damping_margin = 1 / (math.sqrt(1 + damping_ratio**2) + damping_ratio)
                limits['hertz_contacts'] = safety * damping_margin / math.sqrt(frequency_squared)
        signals = [control.get('target_pressure')] + control.get('target_stress', [])
        signal_limits = [signal['duration'] / 100 if signal['type'] == 'ramp' else 1 / (100 * signal['frequency'])
                         for signal in signals if isinstance(signal, dict)]
        if signal_limits:
            limits['target_signal'] = min(signal_limits)
        if not np.all(np.isfinite(positions)) or not np.all(np.isfinite(speed)) or not np.all(np.isfinite(acceleration)):
            raise ValueError('Nonfinite particle state in adaptive time-step estimator.')
        return limits
