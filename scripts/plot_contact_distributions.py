#!/usr/bin/env python3
"""Export contact distribution and penetration-tail contribution figures."""
import json
from pathlib import Path
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
FOLDER=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'runs/mcn_overlap_density_characterization/2026-10-03_06-54-07Z/correlation_study/fixed_target/contact_distributions'
D=json.loads((FOLDER/'distributions.json').read_text())
OUT=FOLDER/'figures';OUT.mkdir(exist_ok=True)
edges=np.asarray(D['edges_depth_D50'][1:-1]);centers=np.sqrt(edges[:-1]*edges[1:])
occupied=np.flatnonzero(np.any(np.array([r['histograms']['count'][1:-1] for r in D['rows']])>0,axis=0))
first=max(0,int(occupied[0])-1);last=min(len(centers)-1,int(occupied[-1])+1)
FIXED_X=(edges[first],edges[last+1])
maximum_fraction=max(max(raw[1:-1])/sum(raw) for r in D['rows'] for raw in r['histograms'].values())
FIXED_Y=np.ceil(maximum_fraction*100*1.12*2)/2
plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
COLORS={'loading':'#147aa6','unloading':'#c76b2b'}
NAMES={'loading':'Carga','unloading':'Descarga'}
P=np.asarray(D['targets'])/1000


def save(fig,name):
    fig.savefig(OUT/(name+'.png'),dpi=170,bbox_inches='tight',facecolor='white')
    fig.savefig(OUT/(name+'.svg'),bbox_inches='tight',facecolor='white')
    plt.close(fig)


fig,axes=plt.subplots(1,3,figsize=(16,4.8),constrained_layout=True)
for ax,index in zip(axes,[0,10,19]):
    for stage,groups in D['groups'].items():
        g=groups[index];hist=g['histograms']['count'];y=100*np.array(hist['mean_fraction'][1:-1])
        ax.plot(centers,y,'-',color=COLORS[stage],label=NAMES[stage])
        ax.fill_between(centers,100*np.array(hist['p10_fraction'][1:-1]),100*np.array(hist['p90_fraction'][1:-1]),color=COLORS[stage],alpha=.15)
    ax.set(xscale='log',xlim=FIXED_X,ylim=(0,FIXED_Y),xlabel='Penetración δ / D50',ylabel='% de contactos por intervalo logarítmico',title=f'Objetivo {P[index]:.3f} kPa')
    ax.grid(alpha=.2);ax.legend()
fig.suptitle('Distribución por objetivo fijo · ejes comunes · media entre runs y percentiles 10–90')
save(fig,'01_contact_histograms')
fig,axes=plt.subplots(1,2,figsize=(13,4.8),constrained_layout=True)
for ax,(stage,groups) in zip(axes,D['groups'].items()):
    for field,label,color in [('top10_depth_share','Σδ','#167dad'),('top10_area_share','ΣA','#ba772d'),('top10_volume_share','ΣV overlap','#8846a5'),('top10_thermal_share','tr(K)','#b63d45')]:
        mean=100*np.array([g['metrics'][field]['mean'] for g in groups])
        low=100*np.array([g['metrics'][field]['p10'] for g in groups]);high=100*np.array([g['metrics'][field]['p90'] for g in groups])
        ax.plot(P,mean,color=color,label=label);ax.fill_between(P,low,high,color=color,alpha=.12)
    ax.axhline(10,color='#aaa',ls='--',label='Reparto uniforme')
    ax.set(xscale='log',xlabel='Objetivo de presión (kPa)',ylabel='% del total aportado por el 10 % más penetrado',title=NAMES[stage])
    ax.grid(alpha=.2);ax.legend(ncol=2,fontsize=10)
fig.suptitle('Concentración de contribuciones: mismos contactos ordenados por penetración')
save(fig,'02_top10_contributions')
fig,axes=plt.subplots(1,2,figsize=(13,4.5),constrained_layout=True)
for stage,groups in D['groups'].items():
    for ax,key in zip(axes,['mean_depth_D50','cv_depth']):
        mean=np.array([g['metrics'][key]['mean'] for g in groups])
        ax.plot(P,mean,color=COLORS[stage],label=NAMES[stage])
        ax.fill_between(P,[g['metrics'][key]['p10'] for g in groups],[g['metrics'][key]['p90'] for g in groups],color=COLORS[stage],alpha=.15)
        ax.set(xscale='log',xlabel='Objetivo de presión (kPa)');ax.grid(alpha=.2);ax.legend()
axes[0].set(ylabel='Media de δ / D50',title='Profundidad media de contacto',yscale='log')
axes[1].set(ylabel='CV = desviación estándar / media',title='Dispersión relativa de las penetraciones')
save(fig,'03_depth_and_dispersion')
print(OUT)
