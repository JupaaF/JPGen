#!/usr/bin/env python3
"""Compare saved accepted checkpoints with and without zero-contact particles.

This is postprocessing: no particles are removed from the simulation. Contacts
are reconstructed using positive overlap and the periodic minimum image.
Pressure/stress are retained from the saved record (forces are not saved).
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BATCH = ROOT / 'runs/mcn_overlap_density_characterization/2026-10-03_06-54-07Z'


def compare(run, record, density):
    stem = run / record['state']
    metadata = json.loads(stem.with_suffix('.json').read_text())
    box = metadata['box']
    if not box['periodic']:
        raise ValueError('This analysis requires a periodic cell')
    lengths = np.asarray(box['lengths'])
    cell_volume = float(np.prod(lengths))
    with np.load(stem.with_suffix('.npz'), allow_pickle=False) as state:
        radii = state['radii']
        positions = (state['positions'] - box['origin']) % lengths
        velocities = state['velocities']
        angular = state['angular_velocities']
    pairs = cKDTree(positions, boxsize=lengths).query_pairs(
        2 * float(radii.max()), output_type='ndarray')
    branch = positions[pairs[:, 0]] - positions[pairs[:, 1]]
    branch -= lengths * np.rint(branch / lengths)
    distances = np.linalg.norm(branch, axis=1)
    touching = distances < radii[pairs[:, 0]] + radii[pairs[:, 1]]
    pairs, branch, distances = pairs[touching], branch[touching], distances[touching]
    degree = np.bincount(pairs.ravel(), minlength=len(radii))
    active = degree > 0
    count, active_count = len(radii), int(active.sum())
    if not len(pairs) or np.any(distances == 0):
        raise ValueError('Expected nonzero distances and at least one contact')
    particle_volume = 4 * np.pi / 3 * radii**3
    mass = density * particle_volume
    translation = .5 * mass * np.sum(velocities**2, axis=1)
    rotation = .2 * mass * radii**2 * np.sum(angular**2, axis=1)
    first, second = radii[pairs[:, 0]], radii[pairs[:, 1]]
    depth = first + second - distances
    if np.any(distances <= np.abs(first - second)):
        raise ValueError('Contained spheres require a different intersection formula')
    h1 = np.clip(depth * (2 * second - depth) / (2 * distances), 0, 2 * first)
    h2 = np.clip(depth * (2 * first - depth) / (2 * distances), 0, 2 * second)
    area = np.pi * np.maximum(h1 * (2 * first - h1), 0)
    overlap_volume = np.pi / 3 * (h1**2 * (3 * first - h1) + h2**2 * (3 * second - h2))
    directions = branch / distances[:, None]
    fabric = directions.T @ directions / len(pairs)
    deviator = 7.5 * (fabric - np.eye(3) / 3)
    thermal = (directions.T * (area * distances)) @ directions / cell_volume
    logged = record['observables']
    shared = {
        'pressure': logged['pressure'],
        'solid_fraction_total_packing': float(particle_volume.sum() / cell_volume),
        'bulk_density_total_packing': float(mass.sum() / cell_volume),
        'contact_count': len(pairs),
        'overlap_length': float(depth.sum()),
        'overlap_area': float(area.sum()),
        'overlap_volume': float(overlap_volume.sum()),
        'normalized_overlap_length': float(depth.sum() / cell_volume**(1/3)),
        'normalized_overlap_area': float(area.sum() / cell_volume**(2/3)),
        'normalized_overlap_volume': float(overlap_volume.sum() / cell_volume),
        'mean_overlap_per_contact': float(depth.mean()),
        # Use the original population D50 in both columns.
        'relative_mean_overlap_per_contact': float(depth.mean() / (2 * np.median(radii))),
        'fabric_tensor': fabric.tolist(),
        'fabric_second_invariant': float(np.sqrt(.5 * np.sum(deviator**2))),
        'thermal_conductivity': thermal.tolist(),
        # Matches the backend field: one third of the mathematical trace.
        'thermal_conductivity_trace': float(np.trace(thermal) / 3),
    }
    shared.update({key: value for key, value in logged.items() if key.startswith('stress_')})
    populations = {}
    for name, mask in [('all', np.ones(count, dtype=bool)), ('without_rattlers', active)]:
        n = int(mask.sum())
        energy = float((translation[mask] + rotation[mask]).sum())
        populations[name] = dict(shared, particle_count=n,
            mean_coordination_number=2 * len(pairs) / n,
            kinetic_energy_translation=float(translation[mask].sum()),
            kinetic_energy_rotation=float(rotation[mask].sum()),
            kinetic_energy=energy,
            normalized_kinetic_energy=energy / (logged['pressure'] * cell_volume),
            solid_fraction_selected_particles=float(particle_volume[mask].sum() / cell_volume),
            bulk_density_selected_particles=float(mass[mask].sum() / cell_volume),
            # No gravity: isolated particles have zero resultant contact force.
            # The contact-force RMS denominator is unchanged. This is inferred
            # from the logged value, not reconstructed from unsaved forces.
            unbalanced_force=logged['unbalanced_force'] * np.sqrt(count / n))
    audit = {}
    for key in ['mean_coordination_number', 'kinetic_energy', 'normalized_kinetic_energy',
                'fabric_tensor', 'fabric_second_invariant', 'thermal_conductivity',
                'thermal_conductivity_trace']:
        calculated, saved = np.asarray(populations['all'][key]), np.asarray(logged[key])
        audit[key + '_max_absolute_error'] = float(np.max(np.abs(calculated - saved)))
        if not np.allclose(calculated, saved, rtol=1e-8, atol=1e-12):
            raise ValueError(f"Saved observable mismatch: {record['state_id']} {key}")
    for key, calculated in [('solid_fraction', shared['solid_fraction_total_packing']),
                            ('bulk_density', shared['bulk_density_total_packing'])]:
        audit[key + '_absolute_error'] = abs(calculated - logged[key])
        if not np.isclose(calculated, logged[key], rtol=1e-8, atol=1e-12):
            raise ValueError(f'Saved observable mismatch: {key}')
    return dict(state_id=record['state_id'], stage=record['path'], time=record['time'],
                target_pressure=record['target']['value'], rattler_count=count-active_count,
                rattler_fraction=(count-active_count)/count,
                rattler_kinetic_energy_fraction=float((translation[~active]+rotation[~active]).sum()
                                                      / populations['all']['kinetic_energy']),
                populations=populations, audit=audit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    run = args.run or next((DEFAULT_BATCH / 'mcn_overlap_density_rep_001').glob('*/run.json')).parent
    run = run.resolve()
    manifest = json.loads((run / 'run.json').read_text())
    if manifest['status'] != 'completed':
        raise ValueError('Choose a completed simulation')
    config = yaml.safe_load((run / 'config/effective.yaml').read_text())
    if config['dem']['engine'] != 'liggghts' or np.any(config['dem']['gravity']):
        raise ValueError('Unbalanced force inference requires LIGGGHTS with zero gravity')
    records = [json.loads(line) for line in (run / 'stages/dem/results/states.jsonl').open()]
    records = [r for r in records if r.get('accepted') is True and 'observables' in r]
    if not records:
        raise ValueError('No accepted checkpoints found')
    rows = [compare(run, r, config['dem']['material']['density']) for r in records]
    output = args.output or DEFAULT_BATCH / 'correlation_study/rattler_comparison_rep_001'
    output.mkdir(parents=True, exist_ok=True)
    result = dict(run=str(run), run_id=manifest['run_id'],
        definition='Rattler = zero positive-overlap contacts at this checkpoint; not a mechanical stability classification.',
        method='Postprocessing at fixed cell and state; positive overlap, periodic minimum image. Original D50 retained.',
        limitations='Pressure/stress copied from saved observables: no force history saved. Unbalanced force inferred by sqrt(N/Nactive) for zero gravity. No simulation rerun.',
        rows=rows,
        audit_max_errors={key: max(r['audit'][key] for r in rows) for key in rows[0]['audit']})
    (output / 'comparison.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    flat = []
    for row in rows:
        values = {k: row[k] for k in ['state_id', 'stage', 'time', 'target_pressure',
                                     'rattler_count', 'rattler_fraction', 'rattler_kinetic_energy_fraction']}
        for population, observables in row['populations'].items():
            values.update({population+'_'+key: value for key, value in observables.items()
                           if not isinstance(value, list)})
        flat.append(values)
    with (output / 'comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)
    lines = ['# Comparación de observables con y sin rattlers', '',
        f"Run: `{run.relative_to(ROOT)}`. {len(rows)} checkpoints aceptados.", '',
        'Rattler = partícula con cero contactos geométricos de overlap positivo. '
        'Se filtran las contribuciones de esas partículas sin evolucionar ni cambiar la caja. '
        'Este criterio no clasifica partículas con pocos contactos ni verifica estabilidad mecánica.', '',
        'MCN y energías se calculan para cada población. La densidad total del packing se conserva; '
        'la densidad seleccionada suma únicamente masa/volumen de las partículas incluidas, sobre la misma caja. '
        'Los overlaps, fabric y tensor térmico se reconstruyen de los contactos. '
        'Presión y tensiones se conservan del registro: sus fuerzas no están guardadas. '
        'Unbalanced force se infiere como U × √(N/Nactivo), válido aquí por gravedad cero '
        'y fuerza de contacto nula en las partículas aisladas. D50 conserva la población original.', '',
        '| Estado | Rattlers | MCN total → sin | Ek total → sin (J) | Ek de rattlers (%) | Densidad total → seleccionada (kg/m³) |',
        '|---|---:|---:|---:|---:|---:|']
    for row in rows:
        a, b = row['populations']['all'], row['populations']['without_rattlers']
        lines.append(f"| {row['stage']} | {row['rattler_count']} | "
                     f"{a['mean_coordination_number']:.6f} → {b['mean_coordination_number']:.6f} | "
                     f"{a['kinetic_energy']:.8g} → {b['kinetic_energy']:.8g} | "
                     f"{100*row['rattler_kinetic_energy_fraction']:.4f} | "
                     f"{a['bulk_density_selected_particles']:.6f} → {b['bulk_density_selected_particles']:.6f} |")
    lines += ['', 'Auditoría contra los observables guardados (máximo error absoluto):', '',
              '```json', json.dumps(result['audit_max_errors'], indent=2), '```', '',
              'Datos completos, incluidos tensores y ambas poblaciones: [JSON](comparison.json). '
              'Todos los observables escalares: [CSV](comparison.csv).', '',
              'No se escribieron tests ni se modificaron los datos de simulación.', '']
    (output / 'report.md').write_text('\n'.join(lines))
    print(json.dumps(dict(output=str(output), checkpoints=len(rows),
        rattler_count_range=[min(r['rattler_count'] for r in rows), max(r['rattler_count'] for r in rows)],
        rattler_kinetic_energy_fraction_range=[min(r['rattler_kinetic_energy_fraction'] for r in rows),
                                              max(r['rattler_kinetic_energy_fraction'] for r in rows)],
        audit_max_errors=result['audit_max_errors']), indent=2))


if __name__ == '__main__':
    main()
