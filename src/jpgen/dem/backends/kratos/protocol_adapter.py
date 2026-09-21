"""Kratos cell actuation and observations for the standalone protocol worker."""
import math

import numpy as np
import KratosMultiphysics as KM
import KratosMultiphysics.DEMApplication as DEM

from commands import ActuatorCommand, NoActuation, CellStrainRate, SymmetricWallVelocity

from protocol import STRESS_OBSERVABLES


class KratosProtocolAdapter:
    def __init__(self, analysis, execution):
        self.analysis = analysis
        self.density = execution['density']
        self.physics = DEM.SphericElementGlobalPhysicsCalculator(analysis.spheres_model_part)
        # Current cases preserve particle population and radii throughout the run.
        self.solid_volume = self.physics.CalculateTotalVolume(analysis.spheres_model_part)
        self.execution = execution
        self.max_radius = execution['max_radius']
        self.variables = KM.VariableUtils()
        self.periodic = execution['boundary'] == 'periodic'

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
        if min(new_lengths) <= 4 * self.max_radius:
            raise ValueError('Periodic cell must remain larger than twice the largest particle diameter.')
        centers = [low + length / 2 for low, length in zip(box['origin'], lengths)]
        # Move both faces symmetrically, keeping one live C++ strategy and contact history.
        self.analysis.UpdateSearchStartegyAndCPlusPlusStrategy(velocities)
        self.analysis.procedures.UpdateBoundingBox(self.analysis.spheres_model_part,
                                                  self.analysis.creator_destructor, velocities)
        nodes = self.analysis.spheres_model_part.Nodes
        position_vector = self.variables.GetCurrentPositionsVector(nodes, 3)
        displacement_vector = self.variables.GetSolutionStepValuesVector(nodes, KM.DISPLACEMENT, 0, 3)
        positions = np.asarray(position_vector).reshape(-1, 3)
        displacements = np.asarray(displacement_vector).reshape(-1, 3)
        changes = (positions - centers) * (np.asarray(scales) - 1)
        positions += changes
        displacements += changes
        self.variables.SetCurrentPositionsVector(nodes, position_vector)
        self.variables.SetSolutionStepValuesVector(nodes, KM.DISPLACEMENT, displacement_vector, 0)

    def observe(self, observables):
        particles = self.analysis.spheres_model_part
        result = {}
        if 'kinetic_energy' in observables:
            result['kinetic_energy'] = (self.physics.CalculateTranslationalKinematicEnergy(particles)
                                       + self.physics.CalculateRotationalKinematicEnergy(particles))
        if self.periodic and observables & {'solid_fraction', 'bulk_density'}:
            fraction = self.solid_volume / math.prod(self.box()['lengths'])
            result.update(solid_fraction=fraction, bulk_density=self.density * fraction)
        if observables & STRESS_OBSERVABLES:
            self.analysis._GetSolver().PrepareContactElementsForPrinting()
            stress = self.analysis.MeasureSphereForGettingGlobalStressTensor()
            for i, j, suffix in ((0, 0, 'xx'), (1, 1, 'yy'), (2, 2, 'zz'), (0, 1, 'xy'), (0, 2, 'xz'), (1, 2, 'yz')):
                result['stress_' + suffix] = float(stress[i][j])
            result['pressure'] = sum(result['stress_' + axis] for axis in ('xx', 'yy', 'zz')) / 3
        if not all(math.isfinite(value) for value in result.values()):
            raise ValueError('Nonfinite DEM observable.')
        # Keep components obtained by the same reduction to avoid repeating it
        # when a sample or stage exit requests the rest of the stress tensor.
        return result
