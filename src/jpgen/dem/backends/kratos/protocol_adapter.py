"""Kratos cell actuation and observations for the standalone protocol worker."""
import json
import math
import shutil
from pathlib import Path

import numpy as np
import KratosMultiphysics as KM
import KratosMultiphysics.DEMApplication as DEM

from commands import ActuatorCommand, NoActuation, CellStrainRate, SymmetricWallVelocity

from protocol import STRESS_OBSERVABLES
from state_exchange import write_state


class KratosProtocolAdapter:
    def __init__(self, analysis, execution):
        self.analysis = analysis
        self.density = execution['density']
        self.physics = DEM.SphericElementGlobalPhysicsCalculator(analysis.spheres_model_part)
        self.contact_physics = None
        # Current cases preserve particle population and radii throughout the run.
        self.solid_volume = self.physics.CalculateTotalVolume(analysis.spheres_model_part)
        self.execution = execution
        self.max_radius = execution['max_radius']
        self.variables = KM.VariableUtils()
        self.periodic = execution['boundary'] == 'periodic'
        self.output = Path.cwd()

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
        if observables & {'kinetic_energy', 'normalized_kinetic_energy'}:
            result['kinetic_energy'] = (self.physics.CalculateTranslationalKinematicEnergy(particles)
                                       + self.physics.CalculateRotationalKinematicEnergy(particles))
        if self.periodic and observables & {'solid_fraction', 'bulk_density'}:
            fraction = self.solid_volume / math.prod(self.box()['lengths'])
            result.update(solid_fraction=fraction, bulk_density=self.density * fraction)
        if 'unbalanced_force' in observables or observables & (STRESS_OBSERVABLES | {'normalized_kinetic_energy'}):
            self.analysis._GetSolver().PrepareContactElementsForPrinting()
        if 'unbalanced_force' in observables:
            if self.contact_physics is None:
                self.contact_physics = DEM.ContactElementGlobalPhysicsCalculator()
            result['unbalanced_force'] = self.contact_physics.CalculateUnbalancedForceWithinSphere(
                particles, self.analysis.contact_model_part, 1e300, [0.0, 0.0, 0.0])
        if observables & (STRESS_OBSERVABLES | {'normalized_kinetic_energy'}):
            stress = self.analysis.MeasureSphereForGettingGlobalStressTensor()
            for i, j, suffix in ((0, 0, 'xx'), (1, 1, 'yy'), (2, 2, 'zz'), (0, 1, 'xy'), (0, 2, 'xz'), (1, 2, 'yz')):
                result['stress_' + suffix] = float(stress[i][j])
            result['pressure'] = sum(result['stress_' + axis] for axis in ('xx', 'yy', 'zz')) / 3
        if 'normalized_kinetic_energy' in observables and result['pressure'] > 0:
            result['normalized_kinetic_energy'] = (result['kinetic_energy'] /
                                                   (result['pressure'] * math.prod(self.box()['lengths'])))
        if not all(math.isfinite(value) for value in result.values()):
            raise ValueError('Nonfinite DEM observable.')
        # Keep components obtained by the same reduction to avoid repeating it
        # when a sample or stage exit requests the rest of the stress tensor.
        return result

    def _contact_properties(self):
        properties = [sub for parent in self.analysis.spheres_model_part.Properties
                      for sub in parent.GetSubProperties()]
        if not properties:
            raise ValueError('Kratos has no contact subproperties for density continuation.')
        return properties

    def friction(self):
        pairs = {(float(prop[DEM.STATIC_FRICTION]), float(prop[DEM.DYNAMIC_FRICTION]))
                 for prop in self._contact_properties()}
        if len(pairs) != 1:
            raise ValueError('Density continuation requires one active friction pair.')
        return pairs.pop()

    def set_friction(self, static, dynamic):
        if not all(math.isfinite(value) and value >= 0 for value in (static, dynamic)):
            raise ValueError('Invalid friction update.')
        for prop in self._contact_properties():
            prop[DEM.STATIC_FRICTION] = static
            prop[DEM.DYNAMIC_FRICTION] = dynamic

    def checkpoint(self, stage, physical_step, time, observables):
        """Save every DEM model part at a completed step for a fresh solver load."""
        runner = self.analysis.protocol
        runner.checkpoint_serial += 1
        stem = f'checkpoint_{runner.checkpoint_serial:08d}'
        directory = self.output / 'checkpoints' / stem
        temporary = directory.with_name(directory.name + '.tmp')
        temporary.mkdir(parents=True, exist_ok=False)
        try:
            parts = (self.analysis.spheres_model_part, self.analysis.contact_model_part,
                     self.analysis.cluster_model_part, self.analysis.dem_inlet_model_part,
                     self.analysis.rigid_face_model_part, self.analysis.mapping_model_part)
            for part in parts:
                serializer = KM.FileSerializer(str(temporary / part.Name),
                                               KM.SerializerTraceType.SERIALIZER_NO_TRACE)
                serializer.Set(KM.Serializer.SHALLOW_GLOBAL_POINTERS_SERIALIZATION)
                serializer.Save(part.Name, part)
                del serializer
            box = self.box()
            write_state(temporary, self.analysis._particle_arrays(), time=time, box=box, stem='state')
            metadata = {'schema': 'JPGen.dem.kratos_checkpoint', 'schema_version': '1.0',
                        'kratos_version': KM.Kernel.Version(), 'stage': stage,
                        'step': physical_step, 'time': time, 'box': box,
                        'friction': self.friction(), 'observables': dict(observables),
                        'protocol_state': runner.state(),
                        'model_parts': [part.Name for part in parts]}
            (temporary / 'checkpoint.json').write_text(json.dumps(metadata, allow_nan=False) + '\n', encoding='utf-8')
            temporary.replace(directory)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return {'directory': str(directory), 'metadata': metadata}

    def restore(self, checkpoint):
        # The current Kratos strategy owns pointers into its model parts. A new
        # analysis loads the checkpoint after this completed step; in-place load
        # would invalidate those pointers and erase contact history.
        self.analysis.rollback_checkpoint = checkpoint

    def log_attempt(self, record):
        with (self.output / 'density_attempts.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, allow_nan=False) + '\n')

    def publish_target(self, checkpoint, metadata):
        number = self.analysis.protocol.density_published_targets + 1
        relative = f'density_targets/target_{number:04d}'
        destination = self.output.parent / relative
        temporary = destination.with_name(destination.name + '.tmp')
        destination.parent.mkdir(exist_ok=True)
        if destination.exists() or temporary.exists():
            raise ValueError('Density target publication path already exists.')
        shutil.copytree(checkpoint['directory'], temporary)
        metadata = dict(metadata, checkpoint=checkpoint['metadata'],
                        kratos_version=KM.Kernel.Version(),
                        provenance={'backend': 'kratos', 'seed': self.execution.get('seed'),
                                    'contact_model': self.execution.get('contact_model')})
        (temporary / 'target.json').write_text(json.dumps(metadata, allow_nan=False) + '\n', encoding='utf-8')
        temporary.replace(destination)
        record = {'kind': 'density_target', 'phase': 'end', 'accepted': True,
                  'path': metadata['stage'], 'target': {'observable': 'solid_fraction',
                  'index': metadata['index'], 'value': metadata['target']},
                  'step': metadata['step'], 'time': metadata['time'],
                  'attempted_duration': metadata['attempted_duration'],
                  'state': relative + '/state', 'restart': relative + '/SpheresPart.rest',
                  'metadata': relative + '/target.json'}
        with (self.output / 'accepted_states.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, allow_nan=False) + '\n')
