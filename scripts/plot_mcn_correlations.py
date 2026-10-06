#!/usr/bin/env python3
"""Render standalone correlation figures with NumPy and Matplotlib."""

import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'runs/mcn_overlap_density_characterization/2026-10-03_06-54-07Z/correlation_study'
DATA = json.loads((FOLDER/'statistics.json').read_text())
FIGURES = FOLDER/'figures'
FIGURES.mkdir(exist_ok=True)
plt.rcParams.update({'font.size':10, 'axes.spines.top':False, 'axes.spines.right':False,
                    'svg.fonttype':'none', 'figure.facecolor':'white', 'axes.grid':True,
                    'grid.alpha':.18, 'savefig.dpi':180})
COLORS={'loading':'#268bd2','unloading':'#cb4b16'}
NAMES={'loading':'Carga','unloading':'Descarga'}
FIELDS=DATA['primary']
LABELS=['MCN (sin rattlers)' if DATA.get('population')=='without_rattlers' else 'MCN (incluye rattlers)','Fracción sólida φ','Σδ / L','ΣA / L²','ΣVoverlap / V','δmedio / D50']
P=np.array(DATA['target_pressure'])/1000
ARRAYS={key:np.array(value) for key,value in DATA['stage_arrays'].items()}


def save(fig,name):
    fig.savefig(FIGURES/f'{name}.png',bbox_inches='tight')
    fig.savefig(FIGURES/f'{name}.svg',bbox_inches='tight')
    plt.close(fig)
    print(name,flush=True)


fig,axes=plt.subplots(2,2,figsize=(14,12),constrained_layout=True)
for row,mode in enumerate(['raw','controlled']):
    for col,stage in enumerate(['loading','unloading']):
        ax=axes[row,col];matrix=np.array(DATA['correlations'][stage][mode]['pearson'])
        image=ax.imshow(matrix,vmin=-1,vmax=1,cmap='RdBu_r')
        ax.set_xticks(range(6),LABELS,rotation=50,ha='right');ax.set_yticks(range(6),LABELS);ax.grid(False)
        for i in range(6):
            for j in range(6):ax.text(j,i,f'{matrix[i,j]:.2f}',ha='center',va='center',color='white' if abs(matrix[i,j])>.6 else 'black')
        ax.set_title(f'{NAMES[stage]} · '+('Pearson bruto' if mode=='raw' else 'Ajustado por run, objetivo y presión real'))
fig.colorbar(image,ax=axes.ravel().tolist(),shrink=.65,label='Correlación r')
save(fig,'01_correlation_matrices')

fig,axes=plt.subplots(2,3,figsize=(15,9),constrained_layout=True)
pairs=[(1,0),(4,0),(1,4)]
for row,stage in enumerate(['loading','unloading']):
    values=ARRAYS[stage].reshape(-1,len(DATA['all_fields']))
    for col,(x,y) in enumerate(pairs):
        ax=axes[row,col];image=ax.scatter(values[:,x],values[:,y],c=values[:,7]/1000,s=10,alpha=.6,cmap='viridis',norm=LogNorm(vmin=5,vmax=200))
        ax.set_xlabel(LABELS[x]);ax.set_ylabel(LABELS[y]);ax.set_title(NAMES[stage])
        if x==4:ax.set_xscale('log')
        if y==4:ax.set_yscale('log')
fig.colorbar(image,ax=axes.ravel().tolist(),shrink=.7,label='Presión real (kPa), escala log')
save(fig,'02_scatter_pressure')

fig,axes=plt.subplots(2,3,figsize=(15,9),constrained_layout=True)
for j,ax in enumerate(axes.flat):
    for stage in ['loading','unloading']:
        profile=DATA['profiles'][stage]
        mean=np.array(profile['mean'])[:,j];lo=np.array(profile['ci_low'])[:,j];hi=np.array(profile['ci_high'])[:,j]
        ax.plot(P,mean,color=COLORS[stage],label=NAMES[stage]);ax.fill_between(P,lo,hi,color=COLORS[stage],alpha=.2)
    ax.set_xscale('log');ax.set_xlabel('Presión objetivo (kPa)');ax.set_ylabel(LABELS[j]);ax.legend()
fig.suptitle('Medias e IC 95 % bootstrap por simulación; no son bandas de dispersión individual')
save(fig,'03_pressure_profiles')

fig,axes=plt.subplots(2,3,figsize=(15,9),constrained_layout=True)
for j,ax in enumerate(axes.flat):
    h=DATA['hysteresis'][FIELDS[j]]
    ax.axhline(0,color='grey',lw=1)
    ax.plot(P,h['nominal_target_delta'],color='#6c71c4',label='Mismo objetivo nominal')
    ax.fill_between(P,h['nominal_target_ci_low'],h['nominal_target_ci_high'],color='#6c71c4',alpha=.2)
    ax.plot(P[1:-1],h['matched_pressure_delta'],'o--',ms=3,color='#859900',label='Misma presión real (interpolada)')
    ax.set_xscale('log');ax.set_xlabel('Presión (kPa)');ax.set_ylabel('Descarga − carga · '+LABELS[j]);ax.legend(fontsize=8)
fig.suptitle('Histéresis apareada dentro de cada simulación; bandas puntuales, no simultáneas')
save(fig,'04_hysteresis')

fig,axes=plt.subplots(2,3,figsize=(15,9),constrained_layout=True)
for row,stage in enumerate(['loading','unloading']):
    values=ARRAYS[stage][...,:6]
    residual=values-values.mean(axis=1,keepdims=True)-values.mean(axis=0,keepdims=True)+values.mean(axis=(0,1),keepdims=True)
    p=np.log(ARRAYS[stage][...,7]);p=p-p.mean(axis=1,keepdims=True)-p.mean(axis=0,keepdims=True)+p.mean()
    residual-=p[...,None]*np.sum(p[...,None]*residual,axis=(0,1))/np.sum(p*p)
    for col,x in enumerate([1,4,5]):
        ax=axes[row,col];r=DATA['correlations'][stage]['controlled']['pearson'][0][x]
        ax.scatter(residual[...,x].ravel(),residual[...,0].ravel(),s=9,alpha=.35,color=COLORS[stage])
        ax.axhline(0,color='grey',lw=.7);ax.axvline(0,color='grey',lw=.7)
        ax.set_xlabel('Residual · '+LABELS[x]);ax.set_ylabel('Residual · MCN');ax.set_title(f'{NAMES[stage]} · r ajustado = {r:.3f}')
save(fig,'05_controlled_relationships')

fig,axes=plt.subplots(2,3,figsize=(15,9),constrained_layout=True)
for row,stage in enumerate(['loading','unloading']):
    by_target=np.array(DATA['correlations'][stage]['by_target_pearson'])
    for col,x in enumerate([1,4,5]):
        ax=axes[row,col];ax.plot(P,by_target[:,0,x],'o-',ms=3,color=COLORS[stage]);ax.axhline(0,color='grey',lw=1);ax.set_ylim(-1,1);ax.set_xscale('log')
        ax.set_xlabel('Presión objetivo (kPa)');ax.set_ylabel('r entre simulaciones a objetivo fijo');ax.set_title(NAMES[stage]+' · MCN vs '+LABELS[x])
save(fig,'06_fixed_pressure_correlations')

fig,axes=plt.subplots(1,3,figsize=(15,5),constrained_layout=True)
actual=np.concatenate([ARRAYS['loading'][...,0],ARRAYS['unloading'][...,0]],axis=1)
for ax,name,title in zip(axes[:2],['pressure_branch','plus_density_overlap'],['Presión + rama','Presión + rama + φ + overlap']):
    prediction=np.array(DATA['prediction'][name]['predictions'])
    for stage,selection in [('loading',slice(0,20)),('unloading',slice(20,40))]:ax.scatter(actual[:,selection].ravel(),prediction[:,selection].ravel(),s=8,alpha=.3,color=COLORS[stage],label=NAMES[stage])
    lo,hi=actual.min(),actual.max();ax.plot([lo,hi],[lo,hi],'k--',lw=1);ax.set_xlabel('MCN observado');ax.set_ylabel('MCN predicho fuera de muestra');ax.set_title(title);ax.legend()
models=list(DATA['prediction']);rmse=[DATA['prediction'][m]['RMSE'] for m in models]
axes[2].bar(range(len(models)),rmse,color=['#93a1a1','#268bd2','#859900','#6c71c4'])
intervals=np.array([DATA['prediction'][m]['RMSE_ci95_conditional'] for m in models])
axes[2].errorbar(range(len(models)),rmse,yerr=[np.array(rmse)-intervals[:,0],intervals[:,1]-np.array(rmse)],fmt='none',color='black',capsize=3)
axes[2].set_xticks(range(len(models)),['P + rama','+ φ','+ overlap','+ ambos'],rotation=25);axes[2].set_ylabel('RMSE de MCN');axes[2].set_title('Dejando fuera una simulación completa')
save(fig,'07_out_of_run_prediction')

fig,ax=plt.subplots(figsize=(9,5),constrained_layout=True)
labels=['Σδ/L','ΣA/L²','ΣVoverlap/V','δmedio/D50']
keys=[FIELDS[i] for i in [2,3,4,5]]
for stage,offset in [('loading',-.1),('unloading',.1)]:
    exponents=[DATA['power_laws'][key][stage]['mean_exponent'] for key in keys]
    intervals=np.array([DATA['power_laws'][key][stage]['ci95'] for key in keys])
    ax.errorbar(np.arange(4)+offset,exponents,yerr=[np.array(exponents)-intervals[:,0],intervals[:,1]-np.array(exponents)],fmt='o',capsize=4,label=NAMES[stage],color=COLORS[stage])
ax.set_xticks(range(4),labels);ax.set_ylabel('Exponente b en overlap ∝ P^b');ax.set_title('Ajustes log-log descriptivos por simulación; IC 95 % de la media');ax.legend()
save(fig,'08_overlap_pressure_scaling')
