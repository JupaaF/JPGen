"""Archived comparison of independently switched C++ DEM optimizations.

The optimizations were rolled back. Running a new campaign requires separately
prepared baseline and experimental runtimes. No compilation or tests are run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

import numpy as np
from summarize_kratos_profile import compare, read_state

SWITCHES = {'reference': (0, 0), 'storage': (1, 0), 'indexed': (0, 1), 'both': (1, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--installations', type=Path, default=Path('benchmarks/kratos_cpp/installations'))
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--threads', nargs='+', type=int, default=[1, 4])
    parser.add_argument('--variants', nargs='+', choices=SWITCHES, default=list(SWITCHES))
    parser.add_argument('--original-control', action='store_true')
    args = parser.parse_args()
    if args.repeats < 1 or any(n < 1 for n in args.threads):
        parser.error('Repetitions and thread counts must be positive')
    for runtime in ('baseline', 'experimental'):
        if not (args.installations/runtime/'libs/libKratosDEMCore.so').is_file():
            parser.error(f'Missing {runtime} runtime under {args.installations}. '
                         'This experiment was archived after rollback; prepare '
                         'separate runtimes before running a new campaign.')
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=False)
    reference = args.case.resolve()/'native_results'
    jobs = [(variant, threads, repeat, 'experimental') for repeat in range(args.repeats)
            for threads in args.threads for variant in args.variants]
    random.Random(20260922).shuffle(jobs)
    # Verify the disabled path before evaluating optimizations.
    calibration = ('reference', args.threads[0], 0, 'experimental')
    if calibration in jobs:
        jobs.remove(calibration)
        jobs.insert(0, calibration)
    if args.original_control:
        jobs.insert(0, ('original', args.threads[0], 0, 'baseline'))
    manifest = {'seed': 20260922, 'case': str(args.case.resolve()), 'jobs': jobs,
                'libraries': {}, 'source_sha256': {}}
    for installation in ('baseline', 'experimental'):
        manifest['libraries'][installation] = {}
        for library in (args.installations/installation/'libs').glob('*Kratos*.so'):
            with library.open('rb') as stream:
                manifest['libraries'][installation][library.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    for source in (args.case/'input').iterdir():
        if source.is_file():
            with source.open('rb') as stream:
                manifest['source_sha256'][source.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    for variant, threads, repeat, runtime in jobs:
        target = (args.output/f'{variant}_t{threads}_r{repeat}').resolve()
        target.mkdir()
        shutil.copytree(args.case/'input', target/'input')
        (target/'native_results').mkdir()
        # These are the identical physical inputs, including search frequency 1.
        params = json.loads((target/'input/ProjectParametersDEM.json').read_text())
        if params['NeighbourSearchFrequency'] != 1:
            raise ValueError('This experiment requires searching every step')
        storage, indexed = SWITCHES.get(variant, (0, 0))
        installation = (args.installations/runtime).resolve()
        env = os.environ.copy()
        env.update(PYTHONPATH=str(installation), LD_LIBRARY_PATH=str(installation/'libs'),
                   OMP_NUM_THREADS=str(threads), OPENBLAS_NUM_THREADS='1',
                   KRATOS_DEM_REUSE_SEARCH_STORAGE=str(storage),
                   KRATOS_DEM_INDEXED_NEIGHBOURS=str(indexed))
        command = ['/usr/bin/time', '-f', '{"user_seconds":%U,"system_seconds":%S,"max_rss_kib":%M}',
                   '-o', str(target/'resources.json'), sys.executable,
                   str(root/'tools/kratos_cpp_worker.py'), str(target/'input/run.py')]
        before = os.getloadavg()
        started = time.perf_counter()
        with (target/'stdout.log').open('w') as stdout, (target/'stderr.log').open('w') as stderr:
            process = subprocess.run(command, env=env, stdout=stdout, stderr=stderr, timeout=600)
        row = {'variant': variant, 'threads': threads, 'repeat': repeat,
               'installation': runtime, 'returncode': process.returncode,
               'wall_seconds': time.perf_counter()-started,
               'load_before': before, 'load_after': os.getloadavg()}
        (target/'measurement.json').write_text(json.dumps(row, indent=2)+'\n')
        if process.returncode:
            raise RuntimeError(f'Failed simulation: {target}; see stderr.log')
        loaded = json.loads((target/'runtime.json').read_text())
        for library in ('libKratosCore.so', 'libKratosDEMCore.so'):
            if str(installation/'libs'/library) not in loaded['libraries']:
                raise RuntimeError(f'Wrong native runtime: {loaded}')
        report = json.loads((target/'native_results/execution_report.json').read_text())
        if report['steps'] != 1000 or report['stop_reason'] != 'end_time':
            raise RuntimeError(f'Unexpected completion: {report}')
        row['comparison'] = compare(reference, target/'native_results')
        _, original = read_state(reference)
        _, result = read_state(target/'native_results')
        row['arrays_exactly_equal'] = all(np.array_equal(original[k], result[k]) for k in original)
        row['resources'] = json.loads((target/'resources.json').read_text())
        row['phases'] = json.loads((target/'phases.json').read_text())['phases']
        (target/'measurement.json').write_text(json.dumps(row, indent=2)+'\n')
        print(json.dumps({k: row[k] for k in ('variant','threads','repeat','wall_seconds','arrays_exactly_equal','comparison')}), flush=True)
        if variant in ('reference', 'original') and not row['arrays_exactly_equal']:
            raise RuntimeError('Reference differs from the original case; investigate before timing variants')


if __name__ == '__main__':
    main()
