"""Summarize timings and compare DEM numerical outputs by particle ID."""
import argparse
import json
from pathlib import Path
import re
import statistics

import numpy as np


def read_state(directory):
    metadata = json.loads((directory / 'final_state.json').read_text())
    with np.load(directory / 'final_state.npz', allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    order = np.argsort(arrays['ids'])
    return metadata, {key: value[order] for key, value in arrays.items()}


def compare(reference, candidate, density=2500.):
    meta, ref = read_state(reference)
    other_meta, other = read_state(candidate)
    if not np.array_equal(ref['ids'], other['ids']) or not np.array_equal(ref['radii'], other['radii']):
        raise ValueError('Population or radii changed')
    if meta['time'] != other_meta['time'] or meta['box'] != other_meta['box']:
        raise ValueError('Time or cell changed')
    if not all(np.isfinite(value).all() for value in other.values()):
        raise ValueError('Nonfinite state')
    lengths = np.array(meta['box']['lengths'])
    delta = other['positions']-ref['positions']
    delta -= lengths*np.rint(delta/lengths)
    mass = density * 4*np.pi/3*ref['radii']**3
    inertia = .4*mass*ref['radii']**2
    def energy(state):
        return float(.5*np.sum(mass[:,None]*state['velocities']**2) +
                     .5*np.sum(inertia[:,None]*state['angular_velocities']**2))
    def relative_l2(name):
        denominator = np.linalg.norm(ref[name])
        return float(np.linalg.norm(other[name]-ref[name])/denominator) if denominator else None
    return dict(count=len(mass), solid_fraction=float(np.sum(mass/density)/np.prod(lengths)),
                position_max_m=float(np.max(np.linalg.norm(delta,axis=1))),
                velocity_max_m_s=float(np.max(np.linalg.norm(other['velocities']-ref['velocities'],axis=1))),
                angular_velocity_max_rad_s=float(np.max(np.linalg.norm(other['angular_velocities']-ref['angular_velocities'],axis=1))),
                velocity_relative_l2=relative_l2('velocities'),
                angular_velocity_relative_l2=relative_l2('angular_velocities'),
                kinetic_energy_j=energy(other), kinetic_energy_relative_error=abs(energy(other)/energy(ref)-1),
                momentum_error_kg_m_s=float(np.linalg.norm(np.sum(mass[:,None]*(other['velocities']-ref['velocities']),axis=0))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('measurements',type=Path)
    parser.add_argument('reference',type=Path,help='Reference native_results directory')
    args=parser.parse_args()
    rows=[]
    for path in sorted(args.measurements.glob('*/measurement.json')):
        row=json.loads(path.read_text())
        if row['returncode'] != 0:
            raise ValueError(f'Failed worker: {path}')
        if row['execution']['steps'] != 1000 or row['execution']['stop_reason'] != 'end_time':
            raise ValueError(f'Unexpected simulation completion: {path}')
        row['comparison']=compare(args.reference,path.parent/'native_results')
        log = (path.parent/'stdout.log').read_text()
        cpu = re.search(r'Elapsed processing time \(sum across cores\): ([0-9.]+) seconds', log)
        if cpu:
            row['solver_cpu_seconds'] = float(cpu.group(1))
        rows.append(row)
    summary={}
    for variant in sorted({row['variant'] for row in rows}):
        subset=[row for row in rows if row['variant']==variant]
        times=[row['wall_seconds'] for row in subset]
        summary[variant]=dict(repetitions=len(times),median_seconds=statistics.median(times),
                              min_seconds=min(times),max_seconds=max(times),
                              comparison=subset[0]['comparison'],
                              max_errors={key: max(row['comparison'][key] for row in subset)
                                          for key in subset[0]['comparison'] if 'error' in key or '_max_' in key})
        if all('solver_cpu_seconds' in row for row in subset):
            summary[variant]['median_solver_cpu_seconds'] = statistics.median(
                row['solver_cpu_seconds'] for row in subset)
    result=dict(summary=summary,runs=rows)
    (args.measurements/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
