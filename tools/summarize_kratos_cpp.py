"""Aggregate a completed (or explicitly partial) C++ profiling campaign."""
import argparse
import json
from pathlib import Path
import statistics


def summarize(directory, allow_incomplete=False):
    manifest = json.loads((directory/'manifest.json').read_text())
    rows = []
    pending = []
    for variant, threads, repeat, _ in manifest['jobs']:
        name = f'{variant}_t{threads}_r{repeat}'
        path = directory/name/'measurement.json'
        if not path.exists():
            pending.append(name)
            continue
        row = json.loads(path.read_text())
        if row['returncode']:
            raise ValueError(f'Failed simulation: {name}')
        if 'arrays_exactly_equal' not in row:
            pending.append(name)
            continue
        if row['comparison']['count'] != 4000 or abs(row['comparison']['solid_fraction']-.60)>1e-12:
            raise ValueError(f'Wrong particle population or volume fraction: {name}')
        rows.append(row)
    if pending and not allow_incomplete:
        raise ValueError(f'{len(pending)} simulations have not finished')
    summary = {}
    groups = sorted({(r['threads'], r['variant']) for r in rows})
    for threads, variant in groups:
        subset = [r for r in rows if r['threads']==threads and r['variant']==variant]
        wall = [r['wall_seconds'] for r in subset]
        cpu = [r['resources']['user_seconds']+r['resources']['system_seconds'] for r in subset]
        summary[f'{variant}_t{threads}'] = {
            'variant': variant, 'threads': threads, 'repetitions': len(subset),
            'wall_median_s': statistics.median(wall), 'wall_min_s': min(wall), 'wall_max_s': max(wall),
            'cpu_median_s': statistics.median(cpu),
            'rss_median_mib': statistics.median(r['resources']['max_rss_kib']/1024 for r in subset),
            'solve_median_s': statistics.median(r['phases']['ExplicitStrategy.SolveSolutionStep']['seconds'] for r in subset),
            'all_arrays_exactly_equal': all(r['arrays_exactly_equal'] for r in subset),
            'max_errors': {k: max(r['comparison'][k] for r in subset)
                           for k in ('position_max_m','velocity_max_m_s','angular_velocity_max_rad_s',
                                     'kinetic_energy_relative_error','momentum_error_kg_m_s')},
        }
    for entry in summary.values():
        reference = summary.get(f"reference_t{entry['threads']}")
        if reference and entry['variant']!='original':
            entry['speedup'] = reference['wall_median_s']/entry['wall_median_s']
            entry['wall_reduction_percent'] = 100*(1-entry['wall_median_s']/reference['wall_median_s'])
            entry['cpu_reduction_percent'] = 100*(1-entry['cpu_median_s']/reference['cpu_median_s'])
    return {'complete': not pending, 'pending': pending, 'manifest': manifest, 'summary': summary, 'runs': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign',type=Path)
    parser.add_argument('--allow-incomplete',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=summarize(args.campaign,args.allow_incomplete)
    output=args.output or args.campaign/'summary.json'
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(f"Completed: {len(result['runs'])}; pending: {len(result['pending'])}")
    for key, row in result['summary'].items():
        speedup = f"{row['speedup']:.3f}x" if 'speedup' in row else '-'
        print(f"{key:16s} n={row['repetitions']} wall={row['wall_median_s']:.3f}s "
              f"cpu={row['cpu_median_s']:.3f}s rss={row['rss_median_mib']:.1f}MiB "
              f"speedup={speedup} exact={row['all_arrays_exactly_equal']}")


if __name__=='__main__':
    main()
