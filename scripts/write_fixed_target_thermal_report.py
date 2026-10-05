#!/usr/bin/env python3
"""Build an offline interactive report restricted to fixed pressure targets."""
import base64
import csv
import html
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
FOLDER=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'runs/mcn_overlap_density_characterization/2026-10-03_06-54-07Z/correlation_study/fixed_target'
D=json.loads((FOLDER/'statistics.json').read_text())
NAMES={'loading':'Carga','unloading':'Descarga'}
BODY=[];MD=[]


def paragraph(value):
    BODY.append('<p>'+html.escape(value)+'</p>');MD.append(value+'\n')


def heading(value):
    BODY.append('<h2>'+html.escape(value)+'</h2>');MD.append('## '+value+'\n')


def table(headers,rows):
    BODY.append('<div class="table"><table><thead><tr>'+''.join('<th>'+html.escape(str(c))+'</th>' for c in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(c))+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>')
    MD.extend(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,row))+' |' for row in rows]+[''])


def figure(name,caption):
    data=base64.b64encode((FOLDER/'figures'/f'{name}.png').read_bytes()).decode()
    BODY.append(f'<figure><img src="data:image/png;base64,{data}" alt="{html.escape(caption)}"><figcaption>{html.escape(caption)} · <a href="figures/{name}.svg">SVG</a></figcaption></figure>')
    MD.append(f'![{caption}](figures/{name}.png)\n')


paragraph(f"Instantánea {D['snapshot_time']}: {D['runs']} runs completadas, {D['points']} checkpoints aceptados. Cada grupo reúne {D['runs']} runs al mismo objetivo nominal y en la misma rama. Se estudian 20 objetivos en carga y 20 en descarga; la evolución libre queda fuera. No se mezclan checkpoints de presiones diferentes para calcular las correlaciones de cada grupo.")
heading('Qué significa la traza térmica en estos archivos')
paragraph('K es el tensor geométrico de contactos guardado por LIGGGHTS: K = Σ(Acontacto × distancia entre centros × n⊗n) / Vcaja. Su traza es tr(K) = Σ(Acontacto × distancia entre centros) / Vcaja. Es adimensional: no es una conductividad en W/(m·K), porque esta expresión no incorpora una conductividad material ni resuelve flujo térmico.')
paragraph(f"JPGen denomina thermal_conductivity_trace a tr(K)/3. Este informe utiliza la traza completa tr(K), calculada de la diagonal del tensor del mismo checkpoint. Multiplicar por tres no cambia Pearson ni Spearman. La discrepancia máxima entre la traza calculada/3 y el campo guardado es {D['trace_divided_by_three_max_error']:.1g}. La traza conserva la intensidad total del tensor, pero no describe su anisotropía.")
paragraph('Density = 2650 × fracción sólida en estas runs. Sus correlaciones son idénticas; las tablas muestran φ para evitar duplicar información y el explorador permite seleccionar density en kg/m³. Los overlaps Σδ/L, ΣA/L² y ΣV/V se normalizan con L = Vcaja^(1/3). La penetración media δmedio/D50 divide por contactos = 15000 × MCN/2: su asociación con MCN incluye dependencia matemática.')
heading('Explorador: un objetivo y una rama cada vez')
paragraph('El selector de objetivo identifica también el número de checkpoint. Cada punto del gráfico es una run, con sus variables medidas en ese checkpoint. La carga y la descarga permanecen separadas incluso cuando comparten objetivo. Elegir una run resalta su punto y muestra sus valores; la matriz y las correlaciones describen el grupo completo.')
BODY.append('''<section class="explorer"><div class="controls"><label>Rama <select id="stage"><option value="loading">Carga</option><option value="unloading">Descarga</option></select></label><label>Objetivo <select id="target"></select></label><label>Objetivo / checkpoint <input id="slider" type="range" min="0" max="19" step="1" value="0"></label><label>Eje X <select id="x"></select></label><label>Eje Y <select id="y"></select></label><label>Color <select id="color"></select></label><label>Resaltar run <select id="run"><option value="">Todas</option></select></label></div><p id="selection"></p><svg id="scatter" viewBox="0 0 900 450" role="img" aria-label="Variables entre runs al mismo objetivo"></svg><p id="rvalues"></p><p id="runvalues"></p><div id="matrix" class="table"></div></section>''')
heading('Resumen exclusivo de las diferencias a objetivo fijo')
paragraph('Para resumir los 20 grupos de una rama se resta, a cada variable, su media entre runs en cada objetivo. La correlación se calcula sobre esas desviaciones, no sobre la curva de presión. Este resumen está ponderado por la amplitud de variación residual de cada objetivo; no es la media aritmética de sus 20 correlaciones. Las gráficas y tablas por objetivo muestran cuándo la relación cambia. No se elimina el offset de cada run: interesa comparar packings entre sí.')
rows=[]
for stage,g in D['fixed_target_summary'].items():
    for i,j in [(0,1),(0,5),(5,1),(5,3),(5,4),(0,4)]:
        rows.append([NAMES[stage],D['labels'][i]+' – '+D['labels'][j],f"{g['pearson'][i][j]:+.3f}",f"[{g['ci_low'][i][j]:+.3f}, {g['ci_high'][i][j]:+.3f}]"])
table(['Rama','Relación a objetivo fijo','Pearson r','IC 95 %'],rows)
paragraph('A objetivo fijo, los packings con más MCN tienden a tener mayor fracción sólida y mayor traza térmica. La traza guarda una relación positiva especialmente fuerte con el área normalizada de contacto, y una relación negativa fuerte con el volumen de overlap normalizado. Son asociaciones entre packings bajo este protocolo; no una ley causal ni una afirmación sobre condiciones materiales diferentes.')
paragraph('Una suma de volumen de lentes y una suma de áreas ponderadas por distancia no miden lo mismo. También cambian los radios de los pares activos y la normalización por caja. Por ello el signo negativo traza–overlap volumétrico no implica, por sí solo, que incrementar la penetración de un contacto reduzca su conducción. Para atribuirlo a una distribución concreta de contactos harían falta datos por par, no solo sus sumas.')
figure('05_fixed_target_summary','Correlaciones de las desviaciones respecto a la media de cada objetivo')
heading('Cómo cambian las relaciones según el objetivo')
paragraph('Se calculan Pearson y Spearman entre las runs de cada grupo, además de IC bootstrap de Pearson. Los intervalos por objetivo son puntuales, no simultáneos: un intervalo aislado que no incluya cero entre muchos pares no debe tomarse como confirmación definitiva. Spearman permite comprobar si la ordenación es estable frente a curvatura u observaciones extremas.')
figure('01_mcn_fixed_target','MCN frente a densidad, traza térmica y overlap de volumen, por objetivo')
figure('02_thermal_fixed_target','Traza térmica frente a densidad y overlaps, por objetivo')
paragraph('La excepción más clara aparece en descarga al objetivo de 5 kPa: tr(K)–ΣV/V tiene Pearson +0.760, IC 95 % [0.576, 0.878], mientras en carga al mismo objetivo es −0.956. En descarga las presiones reales van de 4.952 a 5.046 kPa; residualizando log(P real) dentro de ese grupo, la correlación pasa a −0.915. Por tanto, esta inversión nominal es muy sensible a la tolerancia del servo y no debe interpretarse directamente como un cambio de mecanismo térmico. Las cifras de correlación negativas del resumen no se cumplen sin excepción en cada objetivo nominal.')
paragraph('La relación no es constante a lo largo de los objetivos. En el objetivo de 5 kPa, MCN–tr(K) es moderada; a objetivos mayores resulta mucho más fuerte. La relación tr(K)–φ cerca de 5 kPa es débil y cambia de signo entre ramas. Por tanto, el resumen de todos los objetivos no debe sustituir la inspección del checkpoint de interés.')
rows=[]
for stage,groups in D['groups'].items():
    for index in [0,10,19]:
        g=groups[index]
        rows.append([NAMES[stage],f"{g['target_pressure']/1000:.3f}",g['checkpoint'],f"{g['pearson'][0][5]:+.3f}",f"{g['pearson'][1][5]:+.3f}",f"{g['pearson'][3][5]:+.3f}",f"{g['pearson'][4][5]:+.3f}"])
table(['Rama','Objetivo kPa','Checkpoint','MCN–tr(K)','φ–tr(K)','ΣA/L²–tr(K)','ΣV/V–tr(K)'],rows)
heading('Traza térmica y diferencia entre ramas al mismo objetivo')
paragraph('La figura muestra la media de tr(K) en cada grupo y los percentiles 10–90 entre runs, que describen dispersión y no incertidumbre de la media. Las diferencias descarga − carga se calculan emparejando la misma run al mismo objetivo. Sus IC remuestrean pares completos. Esta comparación es nominal: no interpola a una presión real común.')
figure('04_thermal_targets','Traza en cada objetivo y diferencias apareadas descarga − carga')
rows=[]
for index in [0,10,19]:
    g=D['paired_thermal_difference'][index]
    rows.append([f"{g['target_pressure']/1000:.3f}",f"{D['groups']['loading'][index]['mean'][5]:.6g}",f"{D['groups']['unloading'][index]['mean'][5]:.6g}",f"{g['relative_percent']:+.3f} %",f"{g['positive_runs']} + / {g['negative_runs']} −",f"{g['actual_pressure_delta_mean']:+.1f}"])
table(['Objetivo kPa','tr(K) carga','tr(K) descarga','Δ relativo','Signo entre runs','Δ P real media, Pa'],rows)
paragraph('El signo de la diferencia térmica nominal cambia con el objetivo: no es correcto asignar un único signo de histéresis térmica a todo el recorrido. En particular, diferencias pequeñas en objetivos altos pueden estar afectadas por el desajuste de presión real; esta tabla no demuestra irreversibilidad térmica a presión real idéntica.')
heading('Sensibilidad a la tolerancia del servo dentro del objetivo')
paragraph('Objetivo fijo no significa presión real exactamente igual. Como comprobación secundaria, dentro de cada objetivo y rama se resta la asociación lineal de cada variable con log(P real). Se muestran correlaciones de esos residuos. El análisis principal sigue siendo el del objetivo nominal; esta sensibilidad no cambia de objetivo ni compara etapas del recorrido. No elimina efectos no lineales ni prueba causalidad.')
figure('03_pressure_sensitivity','Correlaciones dentro del objetivo después de residualizar log(P real)')
rows=[]
for stage,g in D['fixed_target_summary'].items():
    for i,j in [(0,1),(0,5),(5,4)]:
        rows.append([NAMES[stage],D['labels'][i]+' – '+D['labels'][j],f"{g['pearson'][i][j]:+.3f}",f"{g['pressure_residual_pearson'][i][j]:+.3f}",f"[{g['pressure_residual_ci_low'][i][j]:+.3f}, {g['pressure_residual_ci_high'][i][j]:+.3f}]"])
table(['Rama','Relación','Objetivo fijo','Además P real residual','IC 95 % residual'],rows)
paragraph('Las principales direcciones se conservan en esta comprobación: MCN–traza y MCN–densidad siguen siendo positivas y traza–volumen de overlap sigue siendo negativa. La magnitud sí cambia. La dispersión de presión real de cada grupo se muestra en el explorador, junto con la correlación ajustada del par elegido.')
heading('Tabla de checkpoints: MCN y traza térmica a cada objetivo')
rows=[]
for stage,groups in D['groups'].items():
    for g in groups:
        rows.append([NAMES[stage],g['checkpoint'],f"{g['target_pressure']/1000:.3f}",f"{g['pressure_min']/1000:.3f}–{g['pressure_max']/1000:.3f}",f"{g['pearson'][0][5]:+.3f}",f"[{g['ci_low'][0][5]:+.3f}, {g['ci_high'][0][5]:+.3f}]",f"{g['spearman'][0][5]:+.3f}"])
table(['Rama','Checkpoint','Objetivo kPa','P real mín–máx kPa','MCN–tr(K) Pearson','IC 95 %','Spearman'],rows)
heading('Alcance y archivos reproducibles')
paragraph(f"Se utilizan {D['bootstrap']} remuestreos con semilla {D['bootstrap_seed']}. Para cada objetivo se remuestrean runs. En el resumen de una rama se conservan juntos los 20 checkpoints de cada run, y se recalculan las medias por objetivo en cada remuestreo. Los mismos índices se usan en las diferencias apareadas. Las {D['runs']} runs completadas no representan necesariamente las 100 previstas: las conclusiones corresponden solo a esta instantánea.")
paragraph('No se aplican efectos fijos de run, modelos predictivos ni correlaciones brutas de toda la trayectoria. No se interpreta el checkpoint como causa física. Los intervalos cubren variación entre semillas, no incertidumbre del modelo DEM, reconstrucción geométrica ni sesgo por haber terminado primero estas runs. No se han alterado ni relanzado simulaciones.')
BODY.append('<p>Descargas: <a href="checkpoint_data.csv">Datos con ambas definiciones de traza</a> · <a href="correlations_by_target.csv">Todos los pares por objetivo</a> · <a href="statistics.json">Estadísticas y auditoría</a> · <a href="report.md">Informe Markdown</a>.</p>')
if (FOLDER/'contact_distributions/report.html').exists():
    BODY.append('<p><a href="contact_distributions/report.html">Distribución de penetraciones por contacto</a>: histogramas por objetivo y run, y contribución de los contactos más penetrados al área, volumen de overlap y traza térmica.</p>')
    MD.append('[Distribución de penetraciones por contacto](contact_distributions/report.html).\n')
MD.append('Datos: [checkpoints](checkpoint_data.csv), [correlaciones por objetivo](correlations_by_target.csv), [estadísticas](statistics.json).\n')
paragraph('Reproducción: .venv/bin/python scripts/analyze_fixed_target_thermal.py; generar figuras con scripts/plot_fixed_target_thermal.py en un Python con Matplotlib compatible; generar este informe con .venv/bin/python scripts/write_fixed_target_thermal_report.py. Las figuras se exportan como PNG y SVG; este HTML incrusta imágenes y datos y funciona sin conexión.')

JS=r'''
const D=JSON.parse(document.getElementById('dataset').textContent), $=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';
const labels=[...D.labels,'Density (kg/m³)'],fields=[...D.fields,'bulk_density'];
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>Math.abs(n)<.001&&n!==0?n.toExponential(3):Number(n).toPrecision(5);
for(const id of ['x','y','color']) fields.forEach((f,i)=>$(id).add(new Option(labels[i],f)));
$('x').value=fields[0];$('y').value=fields[5];$('color').value=fields[1];
D.targets.forEach((p,i)=>$('target').add(new Option((p/1000).toFixed(3)+' kPa',i)));
const runs=new Map(D.points_data.map(p=>[p.run_id,p.run]));[...runs].sort((a,b)=>a[1].localeCompare(b[1])).forEach(([id,label])=>$('run').add(new Option(label,id)));
function node(tag,attrs,text){const n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;$('scatter').append(n);return n;}
function update(){
 const stage=$('stage').value,t=+$('target').value,g=D.groups[stage][t],i=fields.indexOf($('x').value),j=fields.indexOf($('y').value),ci=fields.indexOf($('color').value);
 $('slider').value=t;
 const pts=D.points_data.filter(p=>p.stage===stage&&Math.abs(p.target_pressure-g.target_pressure)<1e-6);
 $('selection').textContent=`${stage==='loading'?'Carga':'Descarga'} · objetivo ${(g.target_pressure/1000).toFixed(3)} kPa · checkpoint ${g.checkpoint} · ${pts.length} runs · P real ${(g.pressure_min/1000).toFixed(3)}–${(g.pressure_max/1000).toFixed(3)} kPa.`;
 const extent=k=>{let min=Math.min(...pts.map(p=>p[k])),max=Math.max(...pts.map(p=>p[k]));const pad=(max-min||Math.abs(max)*.01||1)*.08;return [min-pad,max+pad];};
 const [xmin,xmax]=extent(fields[i]),[ymin,ymax]=extent(fields[j]);const colors=pts.map(p=>p[fields[ci]]),cmin=Math.min(...colors),cmax=Math.max(...colors);
 const X=v=>95+(v-xmin)/(xmax-xmin)*690,Y=v=>365-(v-ymin)/(ymax-ymin)*310;
 $('scatter').replaceChildren();
 for(let k=0;k<=5;k++){const xv=xmin+(xmax-xmin)*k/5,yv=ymin+(ymax-ymin)*k/5;
  node('line',{x1:X(xv),x2:X(xv),y1:55,y2:365,stroke:'#e3e6e7'});node('line',{x1:95,x2:785,y1:Y(yv),y2:Y(yv),stroke:'#e3e6e7'});
  node('text',{x:X(xv),y:389,'text-anchor':'middle','font-size':12},fmt(xv));node('text',{x:87,y:Y(yv)+4,'text-anchor':'end','font-size':12},fmt(yv));
 }
 node('text',{x:440,y:430,'text-anchor':'middle','font-size':16},labels[i]);node('text',{x:20,y:220,transform:'rotate(-90 20 220)','text-anchor':'middle','font-size':16},labels[j]);
 node('text',{x:440,y:25,'text-anchor':'middle','font-size':16},'Cada punto es una run al mismo objetivo');
 pts.forEach(p=>{const a=(p[fields[ci]]-cmin)/(cmax-cmin||1),chosen=$('run').value===p.run_id;
 const n=node('circle',{cx:X(p[fields[i]]),cy:Y(p[fields[j]]),r:chosen?8:5,fill:`hsl(${240-240*a},65%,48%)`,stroke:chosen?'#111':'white','stroke-width':chosen?2:1,opacity:$('run').value&&!chosen?.35:.85});
 const title=document.createElementNS(NS,'title');title.textContent=`${p.run} · checkpoint ${p.checkpoint}\n${labels[i]}: ${fmt(p[fields[i]])}\n${labels[j]}: ${fmt(p[fields[j]])}\n${labels[ci]}: ${fmt(p[fields[ci]])}\nP real: ${fmt(p.pressure/1000)} kPa`;n.append(title);
 n.addEventListener('click',()=>{$('run').value=p.run_id;update();});});
 node('text',{x:810,y:70,'font-size':12},'Color:');node('text',{x:810,y:87,'font-size':11},labels[ci]);
 for(let k=0;k<80;k++)node('rect',{x:815,y:105+k*2.5,width:15,height:3,fill:`hsl(${240*k/79},65%,48%)`});
 node('text',{x:838,y:110,'font-size':11},fmt(cmax));node('text',{x:838,y:303,'font-size':11},fmt(cmin));
 const ii=i===7?1:i,jj=j===7?1:j;
 $('rvalues').textContent=`Pearson r = ${g.pearson[ii][jj].toFixed(3)} · IC 95 % [${g.ci_low[ii][jj].toFixed(3)}, ${g.ci_high[ii][jj].toFixed(3)}] · Spearman ρ = ${g.spearman[ii][jj].toFixed(3)}. Sensibilidad a P real: r = ${g.pressure_residual_pearson[ii][jj].toFixed(3)}.`;
 const selected=pts.find(p=>p.run_id===$('run').value);
 $('runvalues').textContent=selected?`${selected.run}: MCN ${fmt(selected.mean_coordination_number)} · φ ${fmt(selected.solid_fraction)} · density ${fmt(selected.bulk_density)} kg/m³ · tr(K) ${fmt(selected.thermal_tensor_trace)} · campo trace=${fmt(selected.thermal_conductivity_trace)} · P real ${fmt(selected.pressure/1000)} kPa.`:'Pulsa un punto para ver sus valores o resalta una run con el selector.';
 $('matrix').innerHTML='<table><caption>Pearson entre runs en este objetivo y rama</caption><thead><tr><th></th>'+D.labels.map(s=>'<th>'+esc(s)+'</th>').join('')+'</tr></thead><tbody>'+g.pearson.map((row,k)=>'<tr><th>'+esc(D.labels[k])+'</th>'+row.map(v=>`<td style="background:hsl(${v>0?210:15},70%,${97-Math.abs(v)*30}%)">${v.toFixed(3)}</td>`).join('')+'</tr>').join('')+'</tbody></table>';
}
for(const id of ['stage','target','x','y','color','run'])$(id).addEventListener('change',update);
$('slider').addEventListener('input',()=>{$('target').value=$('slider').value;update();});update();
'''
style='body{font:16px system-ui;background:#f7f8f9;color:#273642;line-height:1.6;margin:0}main{max-width:1180px;padding:30px;margin:auto}h1,h2{line-height:1.25}h2{margin-top:42px}a{color:#0876ae}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px;background:white}th,td{border:1px solid #dde2e5;padding:9px;text-align:left}th{background:#eaf0f4}.controls{display:flex;gap:15px;flex-wrap:wrap}.controls label{display:flex;flex-direction:column}select{padding:7px;max-width:250px}.explorer{background:white;border:1px solid #dde2e5;padding:20px;border-radius:10px}svg{width:100%;height:auto}figure{margin:25px 0}img{width:100%;height:auto}figcaption{font-size:14px;color:#53636e}@media print{.controls{display:none}main{padding:0}figure{break-inside:avoid}}'
data=json.dumps(D,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
title='Correlaciones a objetivo fijo y traza térmica'
(FOLDER/'report.html').write_text('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+style+'</style></head><body><main><h1>'+title+'</h1>'+''.join(BODY)+'</main><script id="dataset" type="application/json">'+data+'</script><script>'+JS+'</script></body></html>',encoding='utf-8')
(FOLDER/'report.md').write_text('# '+title+'\n\n'+'\n'.join(MD),encoding='utf-8')
print(FOLDER/'report.html')
