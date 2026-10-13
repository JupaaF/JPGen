#!/usr/bin/env python3
"""Prepare independent random packings for repeated 5–200–5 kPa pressure paths."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import secrets

import yaml

from jpgen.dem.configuration import build_dem_plan
from jpgen.packing.configuration import build_packing_plan


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'runs/pressure_cycles')
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--cycles', type=int, default=50)
    parser.add_argument('--fraction-min', type=float, default=0.56)
    parser.add_argument('--fraction-max', type=float, default=0.59)
    parser.add_argument('--free-evolution-friction', choices=('original', 'zero'), default='original')
    args = parser.parse_args()
    if args.count < 1 or args.cycles < 1:
        parser.error('count and cycles must be positive')
    if not (math.isfinite(args.fraction_min) and math.isfinite(args.fraction_max)
            and 0 < args.fraction_min <= args.fraction_max < 1):
        parser.error('Require 0 < fraction-min <= fraction-max < 1')
    template = yaml.safe_load((ROOT / 'scripts/templates/pressure_cycles.yaml').read_text())
    template['dem']['protocol']['stages'][1]['repeat'] = args.cycles
    template['dem']['protocol']['stages'][0]['friction'] = args.free_evolution_friction == 'original'
    template['dem']['protocol']['stages'][1]['friction'] = True
    rng = random.SystemRandom()
    configs, records, used_seeds = [], [], set()
    for index in range(1, args.count + 1):
        seed = secrets.randbits(128)
        while seed in used_seeds:
            seed = secrets.randbits(128)
        used_seeds.add(seed)
        fraction = rng.uniform(args.fraction_min, args.fraction_max)
        config = deepcopy(template)
        config['packing'].update(seed=seed, target_solid_fraction=fraction)
        packing = build_packing_plan(config['packing'])
        build_dem_plan(config['dem']).validate_box(packing.box)
        content = yaml.safe_dump(config, sort_keys=False)
        filename = f'configs/run_{index:04d}.yaml'
        configs.append((filename, content))
        records.append({'index': index, 'seed': seed, 'initial_fraction': fraction,
                        'config': filename, 'sha256': hashlib.sha256(content.encode()).hexdigest()})
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S-%fZ')
    batch = args.output_dir.resolve() / stamp
    (batch / 'configs').mkdir(parents=True, exist_ok=False)
    for filename, content in configs:
        (batch / filename).write_text(content, encoding='utf-8')
    metadata = {'schema_version': 1, 'experiment': 'pressure_cycles', 'created_at': stamp,
                'count': args.count, 'particles': 15000, 'cycles': args.cycles,
                'fraction_distribution': {'type': 'uniform', 'min': args.fraction_min, 'max': args.fraction_max},
                'free_evolution_friction': args.free_evolution_friction,
                'loading_unloading_friction': 'original',
                'seed_source': 'system random, independent 128-bit seeds',
                'free_evolution_max_duration_s': 1.0, 'static_friction': 0.4,
                'dynamic_friction': 0.4, 'jobs': records}
    (batch / 'batch.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    print(batch, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
