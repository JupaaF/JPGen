"""Select particles with positive-overlap contacts in saved periodic checkpoints.

Only postprocessing is performed. The cell and original D50 are retained.
"""
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
import yaml

_CACHE = {}
_CONFIG = {}


def selected_observables(run, record, observed=None):
    run = Path(run)
    stem = run / record['state']
    paths = [stem.with_suffix('.json'), stem.with_suffix('.npz')]
    signature = tuple((p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
    key = str(stem)
    cached = _CACHE.get(key)
    if cached and cached[0] == signature:
        population = cached[1]
    else:
        metadata = json.loads(paths[0].read_text())
        box = metadata['box']
        if not box['periodic']:
            raise ValueError('Rattler selection requires a periodic checkpoint')
        lengths = np.asarray(box['lengths'])
        with np.load(paths[1], allow_pickle=False) as arrays:
            radii = arrays['radii']
            positions = (arrays['positions'] - box['origin']) % lengths
            velocities = arrays['velocities']
            angular = arrays['angular_velocities']
        pairs = cKDTree(positions, boxsize=lengths).query_pairs(2 * float(radii.max()), output_type='ndarray')
        delta = positions[pairs[:, 0]] - positions[pairs[:, 1]]
        delta -= lengths * np.rint(delta / lengths)
        pairs = pairs[np.linalg.norm(delta, axis=1) < radii[pairs[:, 0]] + radii[pairs[:, 1]]]
        active = np.zeros(len(radii), dtype=bool)
        active[pairs.ravel()] = True
        config_path = run / 'config/effective.yaml'
        config_signature = config_path.stat().st_mtime_ns
        cached_config = _CONFIG.get(str(config_path))
        if not cached_config or cached_config[0] != config_signature:
            cached_config = (config_signature, yaml.safe_load(config_path.read_text())['dem'])
            _CONFIG[str(config_path)] = cached_config
        dem = cached_config[1]
        volume = float(np.prod(lengths))
        particle_volume = 4 * np.pi / 3 * radii**3
        mass = dem['material']['density'] * particle_volume
        translation = float((.5 * mass[active] * np.sum(velocities[active]**2, axis=1)).sum())
        rotation = float((.2 * mass[active] * radii[active]**2 * np.sum(angular[active]**2, axis=1)).sum())
        n = int(active.sum())
        population = dict(particle_count=n, total_particle_count=len(radii),
                          rattler_count=int(len(radii)-n), rattler_fraction=float(1-n/len(radii)),
                          mean_coordination_number=2 * len(pairs) / n if n else None,
                          solid_fraction=float(particle_volume[active].sum()/volume),
                          bulk_density=float(mass[active].sum()/volume),
                          kinetic_energy_translation=translation, kinetic_energy_rotation=rotation,
                          kinetic_energy=translation+rotation, cell_volume=volume,
                          infer_unbalanced=dem['engine']=='liggghts' and not np.any(dem['gravity']))
        _CACHE[key] = (signature, population)
    result = dict(observed if observed is not None else record.get('observables', {}))
    for field in ('mean_coordination_number', 'solid_fraction', 'bulk_density', 'kinetic_energy',
                  'kinetic_energy_translation', 'kinetic_energy_rotation'):
        if field in result:
            result[field] = population[field]
    if 'normalized_kinetic_energy' in result:
        denominator = result.get('pressure', 0) * population['cell_volume']
        result['normalized_kinetic_energy'] = population['kinetic_energy']/denominator if denominator else None
    if 'unbalanced_force' in result:
        n = population['particle_count']
        result['unbalanced_force'] = (result['unbalanced_force'] * np.sqrt(population['total_particle_count']/n)
                                     if n and population['infer_unbalanced'] and result['unbalanced_force'] is not None else None)
    result.update({k: population[k] for k in ('particle_count', 'rattler_count', 'rattler_fraction')})
    return result


def end_records(run):
    path = Path(run)/'stages/dem/results/states.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def final_selection(run, observed):
    """Return a selection only if geometry is saved at the exact final sample."""
    records = end_records(run)
    time = observed.get('time')
    matches = [r for r in records if r.get('phase') == 'end' and r.get('time') == time]
    if not matches:
        return None
    return selected_observables(run, matches[-1], observed)


def enrich_points(points, batch):
    runs = {}
    for path in Path(batch).glob('*/*/run.json'):
        manifest = json.loads(path.read_text())
        runs[manifest['run_id']] = path.parent
    states = {}
    for point in points:
        if 'without_rattlers' in point:
            continue
        run = runs[point['run_id']]
        if run not in states:
            states[run] = {r['state_id']: r for r in end_records(run)}
        observed = {k: v for k, v in point.items() if not isinstance(v, dict)}
        selected = selected_observables(run, states[run][point['state_id']], observed)
        point['without_rattlers'] = selected
    return points
