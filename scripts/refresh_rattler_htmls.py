#!/usr/bin/env python3
"""Refresh embedded rattler selections in all existing characterization HTMLs.

Does not change simulation files. Run again after refreshing offline snapshots.
"""
import argparse
import importlib
import json
from pathlib import Path
import re

from rattler_observables import enrich_points, final_selection
from rattler_report import add_population_switch
from rattler_html_controls import dashboard_controls, viewer_controls

ROOT = Path(__file__).resolve().parents[1]


def replace_dataset(source, element_id, payload):
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    return re.sub(r'(<script id="' + element_id + r'" type="application/json">).*?(</script>)',
                  lambda m: m[1] + data + m[2], source, count=1, flags=re.S)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, default=ROOT/'runs/mcn_overlap_density_characterization/2026-10-03_06-54-07Z')
    args = parser.parse_args()
    batch = args.batch.resolve()
    for path in [ROOT/'examples/characterization/mcn_overlap_density_dashboard.html', batch/'viewer_3d.html']:
        if not path.exists():
            continue
        source = path.read_text()
        match = re.search(r'<script id="dataset" type="application/json">(.*?)</script>', source, re.S)
        if not match or match[1] == '__DATA__':
            continue
        data = json.loads(match[1])
        snapshot_batch = ROOT/'runs/mcn_overlap_density_characterization'/data['batch']
        enrich_points(data['points'], snapshot_batch)
        path.write_text(replace_dataset(viewer_controls(source), 'dataset', data))
        print(f'{path}: {len(data["points"])} checkpoints', flush=True)
    for kind in ('particle_count', 'volume_fraction', 'variable_box_fraction'):
        server = importlib.import_module('serve_' + kind + '_dashboard')
        path = server.PAGE
        if not path.exists():
            continue
        source = path.read_text()
        match = re.search(r'<script id="dashboard-data" type="application/json">(.*?)</script>', source, re.S)
        if not match:
            continue
        payload = json.loads(match[1])
        for name, summary in payload['summaries'].items():
            for job in summary['jobs']:
                if job['status'] != 'completed':
                    continue
                manifest = server.job_run_dir(server.BATCHES/name/job['job'])
                try:
                    selected = final_selection(manifest.parent, job['values']) if manifest else None
                    job['without_rattlers'] = server.observable_values(selected) if selected else None
                except (OSError, ValueError, KeyError) as error:
                    job['without_rattlers'] = None
                    print(f'{job["job"]}: selección no disponible: {error}', flush=True)
            print(f'{kind}/{name}: {sum(j.get("without_rattlers") is not None for j in summary["jobs"])} runs seleccionables', flush=True)
        path.write_text(replace_dataset(dashboard_controls(source), 'dashboard-data', payload))
    study = batch/'correlation_study'
    for folder, contact_only in ((study,False), (study/'fixed_target',False), (study/'fixed_target/contact_distributions',True)):
        if (folder/'report.html').exists():
            add_population_switch(folder/'report.html', folder, contact_only)
            print(folder/'report.html', flush=True)


if __name__ == '__main__':
    main()
