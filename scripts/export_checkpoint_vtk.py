#!/usr/bin/env python3
"""Export a periodic DEM checkpoint to legacy VTK with particle diagnostics."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
import yaml


def export(run, state_id, output):
    stem = run / 'stages/dem/results/states' / state_id
    metadata = json.loads(stem.with_suffix('.json').read_text())
    box = metadata['box']
    if not box['periodic']:
        raise ValueError('Expected periodic cell')
    lengths, origin = np.asarray(box['lengths']), np.asarray(box['origin'])
    with np.load(stem.with_suffix('.npz'), allow_pickle=False) as state:
        ids, radii = state['ids'], state['radii']
        positions = (state['positions'] - origin) % lengths
        velocity, angular = state['velocities'], state['angular_velocities']
    pairs = cKDTree(positions, boxsize=lengths).query_pairs(
        2 * float(radii.max()), output_type='ndarray')
    branch = positions[pairs[:, 0]] - positions[pairs[:, 1]]
    branch -= lengths * np.rint(branch / lengths)
    distance = np.linalg.norm(branch, axis=1)
    gap = distance - radii[pairs[:, 0]] - radii[pairs[:, 1]]
    contacts = pairs[gap < 0]
    degree = np.bincount(contacts.ravel(), minlength=len(radii))
    rattler = degree == 0
    config = yaml.safe_load((run / 'config/effective.yaml').read_text())
    density = config['dem']['material']['density']
    mass = density * 4 * np.pi / 3 * radii**3
    translational = .5 * mass * np.sum(velocity**2, axis=1)
    rotational = .2 * mass * radii**2 * np.sum(angular**2, axis=1)
    scalars = dict(particle_id=ids, radius=radii, diameter=2*radii,
                   contact_count=degree, is_rattler=rattler.astype(int),
                   speed=np.linalg.norm(velocity, axis=1),
                   angular_speed=np.linalg.norm(angular, axis=1),
                   kinetic_energy_translation=translational,
                   kinetic_energy_rotation=rotational,
                   kinetic_energy=translational+rotational)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = len(radii)
    with output.open('w') as stream:
        stream.write('# vtk DataFile Version 3.0\n')
        stream.write(f'{state_id}; time={metadata["time"]:.17g} s; coordinates/radii in m\n')
        stream.write(f'ASCII\nDATASET POLYDATA\nPOINTS {count} double\n')
        np.savetxt(stream, positions + origin, fmt='%.17g')
        stream.write(f'VERTICES {count} {2*count}\n')
        np.savetxt(stream, np.column_stack((np.ones(count, dtype=int), np.arange(count))), fmt='%d')
        stream.write(f'POINT_DATA {count}\n')
        for name, values in scalars.items():
            integer = np.issubdtype(values.dtype, np.integer)
            stream.write(f'SCALARS {name} {"int" if integer else "double"} 1\nLOOKUP_TABLE default\n')
            np.savetxt(stream, values, fmt='%d' if integer else '%.17g')
        for name, values in [('velocity', velocity), ('angular_velocity', angular)]:
            stream.write(f'VECTORS {name} double\n')
            np.savetxt(stream, values, fmt='%.17g')
    # A companion outline shows the actual periodic cell, not particle bounds.
    corners = np.array([[x,y,z] for z in [0,1] for y in [0,1] for x in [0,1]])
    edges = [(0,1),(0,2),(1,3),(2,3),(4,5),(4,6),(5,7),(6,7),(0,4),(1,5),(2,6),(3,7)]
    box_output = output.with_name(output.stem + '_box.vtk')
    with box_output.open('w') as stream:
        stream.write('# vtk DataFile Version 3.0\nPeriodic cell outline\nASCII\nDATASET POLYDATA\nPOINTS 8 double\n')
        np.savetxt(stream, origin + corners * lengths, fmt='%.17g')
        stream.write('LINES 12 36\n')
        np.savetxt(stream, [[2,a,b] for a,b in edges], fmt='%d')
    bins = []
    for low, high in [(3,4),(4,5),(5,6),(6,7)]:
        selected = (radii >= low/1000) & (radii < high/1000)
        bins.append(dict(radius_mm=[low,high], count=int(selected.sum()),
                         rattlers=int(np.sum(rattler & selected)),
                         rattler_fraction=float(np.mean(rattler[selected]))))
    # Check whether tiny positive surface gaps explain the isolation count.
    tiny = (gap >= 0) & (gap <= 1e-8)
    near_contact = np.zeros(count, dtype=bool)
    near_contact[pairs[tiny].ravel()] = True
    summary = dict(state_id=state_id, time=metadata['time'], box=box,
                   vtk=str(output), box_vtk=str(box_output), particles=count,
                   contacts=len(contacts), rattlers=int(rattler.sum()),
                   rattler_fraction=float(rattler.mean()),
                   mean_radius_rattlers_mm=float(1000*radii[rattler].mean()),
                   mean_radius_contacting_mm=float(1000*radii[~rattler].mean()),
                   rattler_volume_fraction_of_solid=float(np.sum(radii[rattler]**3)/np.sum(radii**3)),
                   isolated_particles_with_gap_at_most_1e_minus_8_m=int(np.sum(rattler & near_contact)),
                   radius_bins=bins,
                   definition='is_rattler=1 iff zero positive-overlap contacts, including periodic neighbors.')
    output.with_suffix('.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--state-id', help='Default: last saved state')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    state_id = args.state_id or sorted((args.run/'stages/dem/results/states').glob('*.npz'))[-1].stem
    export(args.run.resolve(), state_id, args.output.resolve())


if __name__ == '__main__':
    main()
