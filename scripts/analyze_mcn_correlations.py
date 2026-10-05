#!/usr/bin/env python3
"""Analyze completed-run checkpoint correlations without treating steps as independent runs."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy import stats
from scipy.interpolate import PchipInterpolator

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ["mean_coordination_number", "solid_fraction", "normalized_overlap_length",
           "normalized_overlap_area", "normalized_overlap_volume", "relative_mean_overlap_per_contact"]
ALL = PRIMARY + ["bulk_density", "pressure", "checkpoint", "overlap_length",
                 "overlap_area", "overlap_volume", "log_pressure"]
LABELS = ["MCN", "Fracción sólida", "Σδ/L", "ΣA/L²", "ΣVoverlap/V", "δmedio/D50"]


def correlation(values):
    values = values.reshape(-1, values.shape[-1])
    centered = values - values.mean(axis=0)
    covariance = centered.T @ centered
    scale = np.sqrt(np.diag(covariance))
    return covariance / np.outer(scale, scale)


def transformed(values, mode, pressure):
    if mode == "raw":
        return values
    if mode == "within_run":
        return values - values.mean(axis=1, keepdims=True)
    if mode == "target_adjusted":
        return values - values.mean(axis=0, keepdims=True)
    result = values - values.mean(axis=1, keepdims=True) - values.mean(axis=0, keepdims=True) + values.mean(axis=(0, 1), keepdims=True)
    if mode == "controlled":
        p = pressure - pressure.mean(axis=1, keepdims=True) - pressure.mean(axis=0, keepdims=True) + pressure.mean()
        denominator = np.sum(p*p)
        if denominator > 0:
            result -= p[..., None] * np.sum(p[..., None] * result, axis=(0, 1)) / denominator
    return result


def r2(y, predicted):
    return 1 - np.sum((y-predicted)**2) / np.sum((y-y.mean())**2)


def bh_adjust(values):
    order = np.argsort(values)
    adjusted = np.minimum.accumulate((np.array(values)[order] * len(values) / np.arange(1, len(values)+1))[::-1])[::-1]
    result = np.empty(len(values))
    result[order] = np.minimum(1, adjusted)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viewer", type=Path, default=ROOT / "runs/mcn_overlap_density_characterization/2026-10-03_06-54-07Z/viewer_3d.html")
    parser.add_argument("--bootstrap", type=int, default=2000)
    args = parser.parse_args()
    source = args.viewer.resolve()
    output = source.parent / "correlation_study"
    output.mkdir(exist_ok=True)
    html = source.read_text()
    snapshot = json.loads(html.split('<script id="dataset" type="application/json">', 1)[1].split('</script>', 1)[0])
    points = [dict(point) for point in snapshot["points"] if point["stage"] in {"loading", "unloading"}]
    run_ids = sorted({point["run_id"] for point in points})
    runs = {}
    for path in source.parent.glob('*/*/run.json'):
        manifest = json.loads(path.read_text())
        if manifest['run_id'] in run_ids:
            if manifest['status'] != 'completed':
                raise ValueError(f"Snapshot includes non-completed run: {path}")
            effective = path.parent / 'config/effective.yaml'
            import yaml
            configuration = yaml.safe_load(effective.read_text())
            with np.load(path.parent / 'stages/dem/results/states/state_00000001.npz') as state:
                count, diameter = len(state['radii']), float(2*np.median(state['radii']))
            runs[manifest['run_id']] = {'label': manifest['label'], 'seed': configuration['packing']['seed'],
                'count': count, 'D50': diameter, 'material_density': configuration['dem']['material']['density']}
    if len({run['seed'] for run in runs.values()}) != len(run_ids):
        raise ValueError('Repetition seeds are not unique')
    for point in points:
        run = runs[point['run_id']]
        contacts = run['count'] * point['mean_coordination_number'] / 2
        point['mean_overlap_per_contact'] = point['overlap_length'] / contacts
        point['relative_mean_overlap_per_contact'] = point['mean_overlap_per_contact'] / run['D50']
        point['log_pressure'] = float(np.log(point['pressure']))
    cube = {}
    for stage in ('loading', 'unloading'):
        group = []
        for run_id in run_ids:
            states = sorted((p for p in points if p['run_id']==run_id and p['stage']==stage), key=lambda p:p['target_pressure'])
            if len(states)!=20 or len({p['target_pressure'] for p in states})!=20:
                raise ValueError(f'Unbalanced path: {run_id}/{stage}')
            group.append(states)
        cube[stage] = np.array([[[p[key] for key in ALL] for p in states] for states in group])
    target = sorted(p['target_pressure'] for p in points
                    if p['stage']=='loading' and p['run_id']==run_ids[0])
    if len(target)!=20:
        raise ValueError('Expected 20 paired pressure targets')
    for stage in ('loading','unloading'):
        for run_id in run_ids:
            actual_targets=sorted(p['target_pressure'] for p in points if p['stage']==stage and p['run_id']==run_id)
            if not np.allclose(actual_targets,target,rtol=1e-12,atol=0):
                raise ValueError(f'Pressure targets do not match: {run_id}/{stage}')
    rng = np.random.default_rng(20261005)
    indices = rng.integers(0, len(run_ids), size=(args.bootstrap, len(run_ids)))
    result = {'created_at':datetime.now(timezone.utc).isoformat(), 'source':str(source),
        'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'snapshot_time':snapshot['created_at'],
        'runs':len(run_ids), 'points':len(points), 'excluded_free_points':len(snapshot['points'])-len(points),
        'bootstrap':args.bootstrap, 'bootstrap_seed':20261005, 'primary':PRIMARY, 'all_fields':ALL,
        'labels':LABELS, 'target_pressure':target, 'run_metadata':runs, 'correlations':{}, 'profiles':{},
        'hysteresis':{}, 'prediction':{}, 'audit':{}}
    flat = np.array([[p[key] for key in ALL] for p in points])
    result['pooled_pearson'] = correlation(flat).tolist()
    result['pooled_spearman'] = stats.spearmanr(flat, axis=0).statistic.tolist()
    result['audit']['material_density_identity_max_error'] = max(abs(p['bulk_density']-runs[p['run_id']]['material_density']*p['solid_fraction']) for p in points)
    result['audit']['max_target_pressure_relative_error'] = max(abs(p['pressure']/p['target_pressure']-1) for p in points)
    result['audit']['pair_actual_pressure_relative_difference_max'] = float(np.max(np.abs(cube['unloading'][...,7]-cube['loading'][...,7])/np.asarray(target)))
    for stage, values in cube.items():
        print(f'Analyzing {stage}: {len(run_ids)} runs × 20 targets', flush=True)
        primary = values[..., :len(PRIMARY)]
        pressure = np.log(values[..., ALL.index('pressure')])
        stage_result = {}
        for mode in ('raw','within_run','target_adjusted','controlled'):
            values_transformed = transformed(primary, mode, pressure)
            estimate = correlation(values_transformed)
            samples = np.array([correlation(transformed(primary[idx], mode, pressure[idx])) for idx in indices])
            low, high = np.quantile(samples, [.025,.975], axis=0)
            stage_result[mode] = {'pearson':estimate.tolist(), 'ci_low':low.tolist(), 'ci_high':high.tolist()}
        stage_result['spearman'] = stats.spearmanr(primary.reshape(-1,len(PRIMARY)),axis=0).statistic.tolist()
        stage_result['between_run_means_pearson'] = correlation(primary.mean(axis=1)).tolist()
        total_variance = primary.var(axis=(0,1))
        stage_result['variance_partition'] = {
            'target_percent':(100*primary.mean(axis=0).var(axis=0)/total_variance).tolist(),
            'run_percent':(100*primary.mean(axis=1).var(axis=0)/total_variance).tolist(),
            'interaction_percent':(100*(primary-primary.mean(axis=1,keepdims=True)-primary.mean(axis=0,keepdims=True)+primary.mean(axis=(0,1),keepdims=True)).var(axis=(0,1))/total_variance).tolist(),
        }
        per_run = np.array([correlation(row) for row in primary])
        stage_result['per_run_pearson_median'] = np.median(per_run,axis=0).tolist()
        stage_result['per_run_pearson_range95'] = np.quantile(per_run,[.025,.975],axis=0).tolist()
        loo = []
        for i in range(len(run_ids)):
            keep = np.arange(len(run_ids))!=i
            loo.append(correlation(transformed(primary[keep],'controlled',pressure[keep])))
        stage_result['controlled_leave_one_run_out_min'] = np.min(loo,axis=0).tolist()
        stage_result['controlled_leave_one_run_out_max'] = np.max(loo,axis=0).tolist()
        stage_result['by_target_pearson'] = [correlation(primary[:,i,:]).tolist() for i in range(20)]
        result['correlations'][stage] = stage_result
        mean_boot = np.array([primary[idx].mean(axis=0) for idx in indices])
        result['profiles'][stage] = {'mean':primary.mean(axis=0).tolist(), 'sd':primary.std(axis=0,ddof=1).tolist(),
            'ci_low':np.quantile(mean_boot,.025,axis=0).tolist(), 'ci_high':np.quantile(mean_boot,.975,axis=0).tolist()}

    # Pressure matching at 18 interior targets, within each run's actual range.
    matched, matched_pchip, matched_load = [], [], []
    for row in range(len(run_ids)):
        load, unload = cube['loading'][row], cube['unloading'][row]
        common = np.asarray(target[1:-1])
        if common.min()<max(load[:,7].min(),unload[:,7].min()) or common.max()>min(load[:,7].max(),unload[:,7].max()):
            raise ValueError('Pressure-matched comparison would require extrapolation')
        matched.append(np.column_stack([np.interp(np.log(common), np.log(unload[:,7]), unload[:,col])-
            np.interp(np.log(common),np.log(load[:,7]),load[:,col]) for col in range(len(PRIMARY))]))
        matched_load.append(np.column_stack([np.interp(np.log(common),np.log(load[:,7]),load[:,col])
                                            for col in range(len(PRIMARY))]))
        matched_pchip.append(PchipInterpolator(np.log(unload[:,7]),unload[:,:len(PRIMARY)],axis=0)(np.log(common))-
                             PchipInterpolator(np.log(load[:,7]),load[:,:len(PRIMARY)],axis=0)(np.log(common)))
    matched = np.array(matched)
    matched_pchip = np.array(matched_pchip)
    matched_load = np.array(matched_load)
    delta = cube['unloading'][...,:len(PRIMARY)]-cube['loading'][...,:len(PRIMARY)]
    p_values = []
    for column,key in enumerate(PRIMARY):
        point_delta = delta[...,column]
        boot = np.array([point_delta[idx].mean(axis=0) for idx in indices])
        # Targets are equally spaced in log pressure, so their interior mean is
        # an equally weighted summary on that scale (not a work/energy integral).
        run_delta = matched[...,column].mean(axis=1)
        overall = np.array([run_delta[idx].mean() for idx in indices])
        positive, negative = int(np.sum(run_delta>0)), int(np.sum(run_delta<0))
        p = float(stats.binomtest(positive,positive+negative,.5).pvalue) if positive+negative else 1.0
        p_values.append(p)
        nominal_area = np.trapezoid(point_delta,np.log(target),axis=1)/np.log(target[-1]/target[0])
        result['hysteresis'][key] = {'nominal_target_delta':point_delta.mean(axis=0).tolist(),
            'nominal_target_ci_low':np.quantile(boot,.025,axis=0).tolist(),
            'nominal_target_ci_high':np.quantile(boot,.975,axis=0).tolist(),
            'matched_pressure_delta':matched[...,column].mean(axis=0).tolist(),
            'matched_run_summary':run_delta.tolist(), 'matched_mean':float(run_delta.mean()),
            'matched_ci95':np.quantile(overall,[.025,.975]).tolist(),
            'matched_load_mean':float(matched_load[...,column].mean()),
            'matched_relative_percent':float(100*run_delta.mean()/matched_load[...,column].mean()),
            'matched_pchip_mean':float(matched_pchip[...,column].mean()),
            'matched_pchip_positive_runs':int(np.sum(matched_pchip[...,column].mean(axis=1)>0)),
            'matched_pchip_negative_runs':int(np.sum(matched_pchip[...,column].mean(axis=1)<0)),
            'positive_runs':positive,'negative_runs':negative,'sign_p':p,
            'normalized_log_pressure_area_mean':float(nominal_area.mean())}
    for key,q in zip(PRIMARY,bh_adjust(p_values)):
        result['hysteresis'][key]['sign_q_BH'] = float(q)

    # Leave complete runs out, retaining both branches of a run in the same fold.
    combined = np.concatenate([cube['loading'],cube['unloading']],axis=1)
    logp = np.log(combined[...,7]/5000)
    branch = np.tile(np.r_[np.zeros(20),np.ones(20)],(len(run_ids),1))
    base = np.stack([np.ones_like(logp),logp,logp**2,logp**3,branch,branch*logp,branch*logp**2,branch*logp**3],axis=-1)
    phi = combined[...,1,None]
    overlap = np.log(combined[...,4,None])
    designs = {'pressure_branch':base,'plus_density':np.concatenate([base,phi],axis=-1),
        'plus_overlap':np.concatenate([base,overlap],axis=-1),
        'plus_density_overlap':np.concatenate([base,phi,overlap],axis=-1)}
    observed = combined[...,0]
    for name,design in designs.items():
        predicted = np.zeros_like(observed)
        for i in range(len(run_ids)):
            keep = np.arange(len(run_ids))!=i
            train = design[keep].reshape(-1,design.shape[-1]); y=observed[keep].reshape(-1)
            center=train.mean(axis=0);scale=train.std(axis=0);center[0]=0;scale[0]=1
            beta=np.linalg.lstsq((train-center)/scale,y,rcond=None)[0]
            predicted[i]=(design[i]-center)/scale@beta
        error = observed-predicted
        bootstrap_rmse=[np.sqrt(np.mean(error[idx]**2)) for idx in indices]
        result['prediction'][name]={'R2':float(r2(observed,predicted)), 'RMSE':float(np.sqrt(np.mean(error**2))),
            'MAE':float(np.mean(abs(error))), 'RMSE_ci95_conditional':np.quantile(bootstrap_rmse,[.025,.975]).tolist(),
            'per_run_RMSE':np.sqrt(np.mean(error**2,axis=1)).tolist(), 'predictions':predicted.tolist()}
    predictors=np.column_stack([logp.ravel(),phi.ravel(),overlap.ravel()])
    predictor_correlation=correlation(predictors)
    result['linear_predictor_VIF'] = dict(zip(['log_pressure','solid_fraction','log_normalized_overlap_volume'],np.diag(np.linalg.inv(predictor_correlation)).tolist()))
    for key in PRIMARY:
        # log-log exponent per run/branch is descriptive and avoids pooling seeds.
        column=ALL.index(key)
        if 'overlap' in key:
            result.setdefault('power_laws',{})[key]={}
            for stage,values in cube.items():
                slopes=np.array([np.polyfit(np.log(row[:,7]),np.log(row[:,column]),1)[0] for row in values])
                means=np.array([slopes[idx].mean() for idx in indices])
                result['power_laws'][key][stage]={'mean_exponent':float(slopes.mean()),'ci95':np.quantile(means,[.025,.975]).tolist()}
    with (output/'checkpoint_data.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(points[0]));writer.writeheader();writer.writerows(points)
    result['stage_arrays']={stage:values.tolist() for stage,values in cube.items()}
    result['run_order']=run_ids
    (output/'statistics.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2))
    print(f'Statistics saved: {output}/statistics.json',flush=True)
    for stage in cube:
        raw=result['correlations'][stage]['raw']['pearson']
        controlled=result['correlations'][stage]['controlled']['pearson']
        print(stage,'raw MCN vs phi/L/A/V/meanδ:',raw[0][1:],'controlled:',controlled[0][1:])
    print('Matched hysteresis:',{k:(v['matched_mean'],v['matched_ci95']) for k,v in result['hysteresis'].items()})
    print('Predictive models:',{k:(v['R2'],v['RMSE']) for k,v in result['prediction'].items()})


if __name__=='__main__':
    main()
