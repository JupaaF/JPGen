"""Kratos cell actuation and observations for the standalone protocol worker."""
import math

import KratosMultiphysics as KM

from protocol import STRESS_OBSERVABLES, required_observables


class KratosProtocolAdapter:
    def __init__(self, analysis, execution):
        self.analysis = analysis
        self.density = execution['density']
        self.periodic = execution['boundary'] == 'periodic'
        self.needs_stress = bool(required_observables(execution['protocol']['stages']) & STRESS_OBSERVABLES)

    def box(self):
        origin = [getattr(self.analysis, f'BoundingBoxMin{axis}_update') for axis in 'XYZ']
        lengths = [getattr(self.analysis, f'BoundingBoxMax{axis}_update') - low for axis, low in zip('XYZ', origin)]
        return {'origin': origin, 'lengths': lengths, 'periodic': self.periodic}

    def apply(self, rates, dt):
        if not any(rates):
            return
        if not self.periodic:
            raise ValueError('Cell deformation requires periodic boundaries.')
        if any(not math.isfinite(rate) or abs(rate * dt) > 0.01 for rate in rates):
            raise ValueError('Cell strain per step exceeds 1%; reduce time_step or strain rate.')
        box = self.box()
        lengths = box['lengths']
        scales = [math.exp(rate * dt) for rate in rates]
        new_lengths = [length * scale for length, scale in zip(lengths, scales)]
        max_radius = max(node.GetSolutionStepValue(KM.RADIUS) for node in self.analysis.spheres_model_part.Nodes)
        if min(new_lengths) <= 4 * max_radius:
            raise ValueError('Periodic cell must remain larger than twice the largest particle diameter.')
        centers = [low + length / 2 for low, length in zip(box['origin'], lengths)]
        # Move both faces symmetrically, keeping one live C++ strategy and contact history.
        velocities = [(old - new) / (2 * dt) for old, new in zip(lengths, new_lengths)]
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
        energy = 0.0
        solid_volume = 0.0
        for node in self.analysis.spheres_model_part.Nodes:
            radius = node.GetSolutionStepValue(KM.RADIUS)
            volume = 4 * math.pi / 3 * radius**3
            mass = self.density * volume
            velocity = node.GetSolutionStepValue(KM.VELOCITY)
            spin = node.GetSolutionStepValue(KM.ANGULAR_VELOCITY)
            energy += .5 * mass * sum(v*v for v in velocity) + .2 * mass * radius**2 * sum(w*w for w in spin)
            solid_volume += volume
        result = {'kinetic_energy': energy}
        if self.periodic:
            fraction = solid_volume / math.prod(self.box()['lengths'])
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
