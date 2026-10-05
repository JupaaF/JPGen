#!/usr/bin/env python3
"""Compare completed packings at fixed pressure targets, including thermal tensor trace."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ['mean_coordination_number', 'solid_fraction', 'normalized_overlap_length',
          'normalized_overlap_area', 'normalized_overlap_volume', 'thermal_tensor_trace',
          'relative_mean_overlap_per_contact']
LABELS = ['MCN', 'Fracción sólida', 'Σδ/L', 'ΣA/L²', 'ΣVoverlap/V', 'tr(K)', 'δmedio/D50']


def corr(values):
    centered = values - values.mean(axis=-2, keepdims=True)
    covariance = np.einsum('...ni,...nj->...ij', centered, centered)
    scale = np.sqrt(np.diagonal(covariance, axis1=-2, axis2=-1))
    return covariance / (scale[..., :, None] * scale[..., None, :])


def pressure_residual(values, logp):
    x = values - values.mean(axis=-2, keepdims=True)
    p = logp - logp.mean(axis=-1, keepdims=True)
    slope = np.sum(x * p[..., None], axis=-2) / np.sum(p*p, axis=-1)[..., None]
    return x - p[..., None] * slope[..., None, :]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, default=ROOT/'runs/mcn_overlap_density_characterization/2026-10-03_06-54-07Z/correlation_study')
    parser.add_argument('--bootstrap', type=int, default=2000)
    args = parser.parse_args()
    study = args.study.resolve()
    output = study/'fixed_target'
    output.mkdir(exist_ok=True)
    provenance = json.loads((study/'statistics.json').read_text())
    with (study/'checkpoint_data.csv').open() as stream:
        points = list(csv.DictReader(stream))
    for row in points:
        for field in FIELDS + ['pressure', 'bulk_density', 'checkpoint', 'target_pressure', 'time', 'step']:
            if field in row:
                row[field] = float(row[field])
        row['checkpoint'] = int(row['checkpoint'])
    run_ids = sorted({row['run_id'] for row in points})
    observations = {}
    source_hashes = {}
    for path in study.parent.glob('*/*/run.json'):
        manifest = json.loads(path.read_text())
        if manifest['run_id'] not in run_ids:
            continue
        if manifest['status'] != 'completed':
            raise ValueError(f'Non-completed run: {path}')
        statefile = path.parent/'stages/dem/results/states.jsonl'
        source_hashes[manifest['run_id']] = hashlib.sha256(statefile.read_bytes()).hexdigest()
        records = [json.loads(line) for line in statefile.read_text().splitlines() if line.strip()]
        for record in records:
            if record.get('phase') == 'end' and record.get('accepted') is True:
                observations[manifest['run_id'], record['state_id']] = record['observables']
    max_trace_error = 0
    for row in points:
        observed = observations[row['run_id'], row['state_id']]
        tensor = np.asarray(observed['thermal_conductivity'], dtype=float)
        if tensor.shape != (3, 3) or not np.isfinite(tensor).all():
            raise ValueError('Invalid saved thermal tensor')
        row['thermal_tensor_trace'] = float(np.trace(tensor))
        row['thermal_conductivity_trace'] = float(observed['thermal_conductivity_trace'])
        max_trace_error = max(max_trace_error, abs(row['thermal_tensor_trace']/3-row['thermal_conductivity_trace']))
        if abs(float(observed['pressure'])-row['pressure']) > 1e-8:
            raise ValueError('Checkpoint pressure mismatch')
    targets = provenance['target_pressure']
    cubes = {}
    for stage in ['loading', 'unloading']:
        cubes[stage] = [sorted((p for p in points if p['run_id']==run and p['stage']==stage),
                              key=lambda p:p['target_pressure']) for run in run_ids]
        if any(len(group)!=len(targets) or not np.allclose([p['target_pressure'] for p in group],targets,rtol=1e-12,atol=0) for group in cubes[stage]):
            raise ValueError('Incomplete or unbalanced fixed-target groups')
    rng = np.random.default_rng(20261005)
    bootstrap = rng.integers(0,len(run_ids),(args.bootstrap,len(run_ids)))
    result = {'created_at':datetime.now(timezone.utc).isoformat(), 'snapshot_time':provenance['snapshot_time'],
              'runs':len(run_ids), 'points':len(points), 'run_order':run_ids, 'fields':FIELDS, 'labels':LABELS,
              'targets':targets, 'bootstrap':args.bootstrap, 'bootstrap_seed':20261005,
              'trace_divided_by_three_max_error':max_trace_error, 'source_states_sha256':source_hashes,
              'source_checkpoint_csv_sha256':hashlib.sha256((study/'checkpoint_data.csv').read_bytes()).hexdigest(),
              'groups':{}, 'fixed_target_summary':{}, 'paired_thermal_difference':[], 'points_data':points}
    for stage, groups in cubes.items():
        # target × run × variable: every correlation uses only one target and branch.
        values = np.array([[[row[field] for field in FIELDS] for row in group] for group in groups]).transpose(1,0,2)
        logp = np.log(np.array([[row['pressure'] for row in group] for group in groups]).T)
        summaries = []
        for t,target in enumerate(targets):
            x,p = values[t],logp[t]
            sampled = x[bootstrap]
            r_boot = corr(sampled)
            partial = pressure_residual(x,p)
            partial_boot = corr(pressure_residual(sampled,p[bootstrap]))
            means = sampled.mean(axis=1)
            summaries.append({'target_pressure':target,'checkpoint':groups[0][t]['checkpoint'],
                'count':len(run_ids),'pearson':corr(x).tolist(), 'spearman':stats.spearmanr(x,axis=0).statistic.tolist(),
                'ci_low':np.quantile(r_boot,.025,axis=0).tolist(),'ci_high':np.quantile(r_boot,.975,axis=0).tolist(),
                'pressure_residual_pearson':corr(partial).tolist(),
                'pressure_residual_ci_low':np.quantile(partial_boot,.025,axis=0).tolist(),
                'pressure_residual_ci_high':np.quantile(partial_boot,.975,axis=0).tolist(),
                'mean':x.mean(axis=0).tolist(), 'median':np.median(x,axis=0).tolist(),
                'p10':np.quantile(x,.1,axis=0).tolist(),'p90':np.quantile(x,.9,axis=0).tolist(),
                'mean_ci_low':np.quantile(means,.025,axis=0).tolist(),'mean_ci_high':np.quantile(means,.975,axis=0).tolist(),
                'pressure_mean':float(np.exp(p).mean()), 'pressure_min':float(np.exp(p).min()),
                'pressure_max':float(np.exp(p).max())})
        result['groups'][stage] = summaries
        centered = values-values.mean(axis=1,keepdims=True)
        residual = pressure_residual(values,logp)
        fixed_boot, residual_boot = [], []
        for idx in bootstrap:
            selected = values[:,idx,:]
            demeaned = selected-selected.mean(axis=1,keepdims=True)
            fixed_boot.append(corr(demeaned.reshape(-1,len(FIELDS))))
            residual_boot.append(corr(pressure_residual(selected,logp[:,idx]).reshape(-1,len(FIELDS))))
        result['fixed_target_summary'][stage] = {
            'pearson':corr(centered.reshape(-1,len(FIELDS))).tolist(),
            'ci_low':np.quantile(fixed_boot,.025,axis=0).tolist(), 'ci_high':np.quantile(fixed_boot,.975,axis=0).tolist(),
            'pressure_residual_pearson':corr(residual.reshape(-1,len(FIELDS))).tolist(),
            'pressure_residual_ci_low':np.quantile(residual_boot,.025,axis=0).tolist(),
            'pressure_residual_ci_high':np.quantile(residual_boot,.975,axis=0).tolist()}
        print(f'{stage}: {len(targets)} fixed targets, {len(run_ids)} runs',flush=True)
    for t,target in enumerate(targets):
        load = np.array([group[t]['thermal_tensor_trace'] for group in cubes['loading']])
        unload = np.array([group[t]['thermal_tensor_trace'] for group in cubes['unloading']])
        delta = unload-load
        means = delta[bootstrap].mean(axis=1)
        result['paired_thermal_difference'].append({'target_pressure':target, 'mean':float(delta.mean()),
            'ci95':np.quantile(means,[.025,.975]).tolist(), 'relative_percent':float(100*delta.mean()/load.mean()),
            'positive_runs':int(np.sum(delta>0)), 'negative_runs':int(np.sum(delta<0)),
            'actual_pressure_delta_mean':float(np.mean([cubes['unloading'][i][t]['pressure']-cubes['loading'][i][t]['pressure'] for i in range(len(run_ids))]))})
    (output/'statistics.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    with (output/'checkpoint_data.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(points[0]));writer.writeheader();writer.writerows(points)
    with (output/'correlations_by_target.csv').open('w',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['stage','target_pressure_pa','checkpoint','variable_1','variable_2','pearson','spearman','ci_low','ci_high','partial_actual_log_pressure','partial_ci_low','partial_ci_high'])
        for stage,groups in result['groups'].items():
            for g in groups:
                for i in range(len(FIELDS)):
                    for j in range(i+1,len(FIELDS)):
                        writer.writerow([stage,g['target_pressure'],g['checkpoint'],FIELDS[i],FIELDS[j],g['pearson'][i][j],g['spearman'][i][j],g['ci_low'][i][j],g['ci_high'][i][j],g['pressure_residual_pearson'][i][j],g['pressure_residual_ci_low'][i][j],g['pressure_residual_ci_high'][i][j]])
    print(output)


if __name__=='__main__':
    main()
