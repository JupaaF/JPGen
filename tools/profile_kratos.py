"""Reproducible Kratos performance experiment on an existing JPGen DEM case.

No packing generation is timed. Each worker starts from the same input files.
Uses the local Release installation, writes isolated cases and raw profiles.
"""
import argparse
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

VARIANTS = {
    'baseline': (1, 1, 0.0),
    'skin_only': (1, 1, 5e-5),
    'threads2': (2, 1, 0.0),
    'threads4': (4, 1, 0.0),
    'search10': (1, 10, 5e-5),
    'search10_threads2': (2, 10, 5e-5),
    'search10_threads4': (4, 10, 5e-5),
    'search20': (1, 20, 5e-5),
    'search10_no_skin': (1, 10, 0.0),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path, help='Existing dem directory')
    parser.add_argument('output', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--variants', nargs='+', choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--phases', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    installation = root / 'Kratos/bin/Release'
    args.output.mkdir(parents=True, exist_ok=True)
    jobs = [(variant, repeat) for repeat in range(args.repeats) for variant in args.variants]
    random.Random(20260921).shuffle(jobs)
    for variant, repeat in jobs:
        threads, frequency, skin = VARIANTS[variant]
        target = (args.output / f'{variant}_{repeat}').resolve()
        target.mkdir(exist_ok=False)
        shutil.copytree(args.case / 'input', target / 'input')
        (target / 'native_results').mkdir()
        params_path = target / 'input/ProjectParametersDEM.json'
        params = json.loads(params_path.read_text())
        params.update(NeighbourSearchFrequency=frequency, DeltaOption='Absolute', SearchTolerance=skin)
        params_path.write_text(json.dumps(params, indent=2) + '\n')
        env = os.environ.copy()
        env.update(OMP_NUM_THREADS=str(threads), OPENBLAS_NUM_THREADS='1')
        env['PYTHONPATH'] = str(installation) + os.pathsep + env.get('PYTHONPATH', '')
        env['LD_LIBRARY_PATH'] = str(installation / 'libs') + os.pathsep + env.get('LD_LIBRARY_PATH', '')
        command = [sys.executable]
        if args.profile:
            command += ['-m', 'cProfile', '-o', str(target / 'worker.pstats')]
        if args.phases:
            command += [str(root / 'tools/kratos_phase_profile.py')]
        command += [str(target / 'input/run.py')]
        started = time.perf_counter()
        with (target / 'stdout.log').open('w') as stdout, (target / 'stderr.log').open('w') as stderr:
            completed = subprocess.run(command, env=env, stdout=stdout, stderr=stderr, timeout=600)
        result = dict(variant=variant, repeat=repeat, threads=threads, frequency=frequency,
                      skin=skin, wall_seconds=time.perf_counter()-started, returncode=completed.returncode,
                      profiled=args.profile, phase_timers=args.phases, command=command)
        report = target / 'native_results/execution_report.json'
        if report.exists():
            result['execution'] = json.loads(report.read_text())
        (target / 'measurement.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result), flush=True)
        if completed.returncode:
            raise RuntimeError(f'Worker failed: {target}')


if __name__ == '__main__':
    main()
