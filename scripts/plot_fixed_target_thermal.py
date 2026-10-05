#!/usr/bin/env python3
"""Export figures for correlations across runs at each fixed pressure target."""
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
FOLDER=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'runs/mcn_overlap_density_characterization/2026-10-03_06-54-07Z/correlation_study/fixed_target'
D=json.loads((FOLDER/'statistics.json').read_text())
OUT=FOLDER/'figures';OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white','savefig.facecolor':'white'})
COLORS={'loading':'#137eab','unloading':'#d27630'}
NAMES={'loading':'Carga','unloading':'Descarga'}
P=np.asarray(D['targets'])/1000


def save(fig,name):
    fig.savefig(OUT/(name+'.png'),dpi=170,bbox_inches='tight')
    fig.savefig(OUT/(name+'.svg'),bbox_inches='tight')
    plt.close(fig)


def correlations(pairs,filename,title,partial=False):
    fig,axes=plt.subplots(1,3,figsize=(16,4.7),sharey=True)
    prefix='pressure_residual_' if partial else ''
    for ax,(i,j) in zip(axes,pairs):
        for stage,groups in D['groups'].items():
            y=[g[prefix+'pearson'][i][j] for g in groups]
            low=[g[prefix+'ci_low'][i][j] for g in groups]
            high=[g[prefix+'ci_high'][i][j] for g in groups]
            ax.plot(P,y,'o-',color=COLORS[stage],label=NAMES[stage],ms=3)
            ax.fill_between(P,low,high,color=COLORS[stage],alpha=.16)
        ax.axhline(0,color='#aaa',lw=.9)
        ax.set(xscale='log',xlabel='Objetivo de presión (kPa)',title=D['labels'][i]+' vs '+D['labels'][j],ylim=(-1.05,1.05))
        ax.grid(alpha=.15)
    axes[0].set_ylabel('Pearson r entre runs al mismo objetivo')
    axes[-1].legend();fig.suptitle(title+' · IC 95 % puntuales, '+str(D['runs'])+' runs',y=1.02)
    fig.tight_layout();save(fig,filename)


correlations([(0,1),(0,5),(0,4)],'01_mcn_fixed_target','MCN a objetivo fijo')
correlations([(5,1),(5,3),(5,4)],'02_thermal_fixed_target','Traza térmica a objetivo fijo')
correlations([(0,1),(0,5),(5,4)],'03_pressure_sensitivity','Sensibilidad: residualizar log de presión real dentro de cada objetivo',True)
fig,axes=plt.subplots(1,2,figsize=(13,5))
for stage,groups in D['groups'].items():
    mean=np.array([g['mean'][5] for g in groups])
    low=np.array([g['p10'][5] for g in groups]);high=np.array([g['p90'][5] for g in groups])
    axes[0].plot(P,mean,'o-',label=NAMES[stage],color=COLORS[stage],ms=4)
    axes[0].fill_between(P,low,high,color=COLORS[stage],alpha=.18)
axes[0].set(xscale='log',yscale='log',xlabel='Objetivo de presión (kPa)',ylabel='tr(K), adimensional',title='Traza por objetivo: media y percentiles 10–90')
axes[0].legend();axes[0].grid(alpha=.2)
paired=D['paired_thermal_difference']
mean=np.array([g['mean'] for g in paired]);ci=np.array([g['ci95'] for g in paired])
axes[1].plot(P,mean,'o-',color='#8053a1',ms=4)
axes[1].fill_between(P,ci[:,0],ci[:,1],color='#8053a1',alpha=.2)
axes[1].axhline(0,color='#aaa')
axes[1].set(xscale='log',xlabel='Objetivo de presión (kPa)',ylabel='Δ tr(K), adimensional',title='Descarga − carga al mismo objetivo · IC 95 %')
axes[1].grid(alpha=.2)
fig.tight_layout();save(fig,'04_thermal_targets')
fig,axes=plt.subplots(1,2,figsize=(16,6),constrained_layout=True)
for ax,(stage,g) in zip(axes,D['fixed_target_summary'].items()):
    matrix=np.array(g['pearson'])
    im=ax.imshow(matrix,vmin=-1,vmax=1,cmap='RdBu_r')
    ax.set_xticks(range(7),D['labels'],rotation=45,ha='right');ax.set_yticks(range(7),D['labels'])
    for i in range(7):
        for j in range(7):ax.text(j,i,f'{matrix[i,j]:.2f}',ha='center',va='center',color='white' if abs(matrix[i,j])>.6 else '#222',fontsize=10)
    ax.set_title(NAMES[stage]+' · media de cada objetivo eliminada')
fig.colorbar(im,ax=axes.ravel().tolist(),shrink=.7,label='Pearson r')
save(fig,'05_fixed_target_summary')
print(OUT)
