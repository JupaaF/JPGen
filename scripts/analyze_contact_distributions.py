#!/usr/bin/env python3
"""Reconstruct contact penetration distributions from saved periodic checkpoints."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]
LOG_BINS=288
EDGES=np.r_[0.,np.geomspace(1e-9,1.,LOG_BINS+1),np.inf]


def extract(run,point):
    stem=run/'stages/dem/results/states'/point['state_id']
    metadata=json.loads(stem.with_suffix('.json').read_text())
    box=np.asarray(metadata['box']['lengths'],dtype=float)
    if not metadata['box']['periodic']:
        raise ValueError('Expected periodic box')
    with np.load(stem.with_suffix('.npz'),allow_pickle=False) as arrays:
        radii=arrays['radii'];positions=(arrays['positions']-metadata['box']['origin'])%box
        pairs=cKDTree(positions,boxsize=box).query_pairs(2*float(radii.max()),output_type='ndarray')
        displacement=positions[pairs[:,0]]-positions[pairs[:,1]]
        displacement-=box*np.rint(displacement/box)
        distance=np.linalg.norm(displacement,axis=1)
        first,second=radii[pairs[:,0]],radii[pairs[:,1]]
        active=distance<first+second
        distance,first,second=distance[active],first[active],second[active]
        depth=first+second-distance
        if not len(depth):
            raise ValueError(f'No geometric contacts: {stem}')
        diameter=float(2*np.median(radii));cell_volume=float(np.prod(box))
    effective_radius=first*second/(first+second)
    contained=distance<=np.abs(first-second)
    partial=~contained
    area=np.zeros_like(depth);volume=np.zeros_like(depth)
    volume[contained]=4*np.pi/3*np.minimum(first[contained],second[contained])**3
    r1,r2,d,p=first[partial],second[partial],distance[partial],depth[partial]
    h1=np.clip(p*(2*r2-p)/(2*d),0,2*r1)
    h2=np.clip(p*(2*r1-p)/(2*d),0,2*r2)
    area[partial]=np.pi*np.maximum(h1*(2*r1-h1),0)
    volume[partial]=np.pi/3*(h1**2*(3*r1-h1)+h2**2*(3*r2-h2))
    thermal=area*distance
    relative=depth/diameter
    order=np.argsort(depth)
    result={key:point[key] for key in ['run','run_id','state_id','stage','checkpoint','target_pressure','pressure','solid_fraction','mean_coordination_number']}
    result.update({'contacts':len(depth),'particle_count':len(radii),'D50_m':diameter,
        'mean_depth_m':float(depth.mean()),'std_depth_m':float(depth.std()),
        'mean_depth_D50':float(relative.mean()),'median_depth_D50':float(np.median(relative)),
        'p90_depth_D50':float(np.quantile(relative,.9)),'p99_depth_D50':float(np.quantile(relative,.99)),
        'max_depth_D50':float(relative.max()),'cv_depth':float(depth.std()/depth.mean()),
        'sum_depth_m':float(depth.sum()),'sum_depth_squared_m2':float(np.sum(depth**2)),
        'effective_contact_fraction':float(depth.sum()**2/(len(depth)*np.sum(depth**2))),
        'sum_area_m2':float(area.sum()),'sum_volume_m3':float(volume.sum()),
        'thermal_tensor_trace':float(thermal.sum()/cell_volume),
        'contained_contacts':int(contained.sum()),'zero_distance_contacts':int(np.sum(distance==0)),
        'logged_contacts':float(len(radii)*point['mean_coordination_number']/2),
        'contact_count_difference':float(len(depth)-len(radii)*point['mean_coordination_number']/2),
        'small_overlap_area_approx_relative_error':float((2*np.pi*np.sum(effective_radius*depth))/area.sum()-1),
        'small_overlap_volume_approx_relative_error':float((np.pi*np.sum(effective_radius*depth**2))/volume.sum()-1)})
    for fraction,label in [(.1,'top10'),(.01,'top1')]:
        tail=order[-math.ceil(len(depth)*fraction):]
        result[label+'_actual_contact_fraction']=len(tail)/len(depth)
        for weights,name in [(depth,'depth'),(area,'area'),(volume,'volume'),(thermal,'thermal')]:
            result[label+'_'+name+'_share']=float(weights[tail].sum()/weights.sum())
    hist={}
    for weights,name in [(None,'count'),(depth,'depth'),(area,'area'),(volume,'volume'),(thermal,'thermal')]:
        counts=np.histogram(relative,bins=EDGES,weights=weights)[0]
        hist[name]=counts.tolist()
    result['histograms']=hist
    result['audit_area_relative_error']=float(abs(area.sum()/float(point['overlap_area'])-1))
    result['audit_volume_relative_error']=float(abs(volume.sum()/float(point['overlap_volume'])-1))
    result['audit_depth_relative_error']=float(abs(depth.sum()/float(point['overlap_length'])-1))
    result['audit_thermal_relative_error']=float(abs(result['thermal_tensor_trace']/point['thermal_tensor_trace']-1))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',type=Path,default=ROOT/'runs/mcn_overlap_density_characterization/2026-10-03_06-54-07Z/correlation_study/fixed_target')
    parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args();study=args.study.resolve();output=study/'contact_distributions';output.mkdir(exist_ok=True)
    data=json.loads((study/'statistics.json').read_text());points=data['points_data']
    run_paths={}
    for path in study.parent.parent.glob('*/*/run.json'):
        manifest=json.loads(path.read_text())
        if manifest['run_id'] in data['run_order']:
            if manifest['status']!='completed':raise ValueError('Non-completed run')
            run_paths[manifest['run_id']]=path.parent
    cache_path=output/'cache.json';cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
    rows=[];pending={}
    with ThreadPoolExecutor(max_workers=max(1,min(args.workers,2))) as pool:
        for p in points:
            run=run_paths[p['run_id']];stem=run/'stages/dem/results/states'/p['state_id']
            signature=[[f.stat().st_size,f.stat().st_mtime_ns] for f in [stem.with_suffix('.json'),stem.with_suffix('.npz')]]
            key=p['run_id']+'/'+p['state_id']
            if (key in cache and cache[key]['signature']==signature
                    and len(cache[key]['row']['histograms']['count'])==len(EDGES)-1):
                rows.append(cache[key]['row'])
            else:pending[pool.submit(extract,run,p)]=(key,signature)
        completed=0
        for future in as_completed(pending):
            key,signature=pending[future];row=future.result();rows.append(row);cache[key]={'signature':signature,'row':row}
            completed+=1
            if completed%100==0 or completed==len(pending):
                print(f'Extracted {completed}/{len(pending)} checkpoints',flush=True)
                cache_path.write_text(json.dumps(cache,allow_nan=False),encoding='utf-8')
    rows.sort(key=lambda r:(r['run'],r['checkpoint']))
    result={'created_at':datetime.now(timezone.utc).isoformat(),'snapshot_time':data['snapshot_time'],
        'runs':data['runs'],'checkpoints':len(rows),'targets':data['targets'],
        'edges_depth_D50':[float(v) if np.isfinite(v) else None for v in EDGES],
        'definition':'Unordered geometric pairs with positive overlap; periodic minimum image; each pair counted once.',
        'rows':rows,'groups':{},'audit':{}}
    for stage in ['loading','unloading']:
        groups=[]
        for target in data['targets']:
            group=[r for r in rows if r['stage']==stage and np.isclose(r['target_pressure'],target,rtol=1e-12,atol=0)]
            if len(group)!=data['runs']:raise ValueError('Incomplete fixed-target group')
            group_summary={'target_pressure':target,'checkpoint':group[0]['checkpoint'],'count':len(group),'metrics':{},'histograms':{}}
            for field in [k for k in group[0] if isinstance(group[0][k],(float,int))]:
                values=np.array([r[field] for r in group])
                group_summary['metrics'][field]={'mean':float(values.mean()),'median':float(np.median(values)),
                    'p10':float(np.quantile(values,.1)),'p90':float(np.quantile(values,.9))}
            # Each run has equal weight; these are fractions, not densities per log unit.
            for field in ['count','depth','area','volume','thermal']:
                fractions=np.array([np.array(r['histograms'][field])/sum(r['histograms'][field]) for r in group])
                group_summary['histograms'][field]={'mean_fraction':fractions.mean(axis=0).tolist(),
                    'p10_fraction':np.quantile(fractions,.1,axis=0).tolist(),'p90_fraction':np.quantile(fractions,.9,axis=0).tolist()}
            groups.append(group_summary)
        result['groups'][stage]=groups
    for field in ['audit_area_relative_error','audit_volume_relative_error','audit_depth_relative_error','audit_thermal_relative_error']:
        result['audit'][field+'_max']=max(r[field] for r in rows)
    result['audit']['max_absolute_contact_count_difference']=max(abs(r['contact_count_difference']) for r in rows)
    result['audit']['contained_contacts_total']=sum(r['contained_contacts'] for r in rows)
    (output/'distributions.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    cache_path.write_text(json.dumps(cache,allow_nan=False),encoding='utf-8')
    with (output/'checkpoint_contact_metrics.csv').open('w',newline='') as stream:
        fields=[key for key in rows[0] if key!='histograms'];writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader();writer.writerows({k:r[k] for k in fields} for r in rows)
    print(output,flush=True)


if __name__=='__main__':main()
