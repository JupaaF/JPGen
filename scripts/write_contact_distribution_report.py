#!/usr/bin/env python3
"""Write an offline viewer of penetration distributions at fixed pressure targets."""
import base64
import html
import json
from rattler_report import add_population_switch
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
FOLDER=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'runs/mcn_overlap_density_characterization/2026-10-03_06-54-07Z/correlation_study/fixed_target/contact_distributions'
D=json.loads((FOLDER/'distributions.json').read_text())
NAMES={'loading':'Carga','unloading':'Descarga'}
body=[];md=[]


def paragraph(value):
    body.append('<p>'+html.escape(value)+'</p>');md.append(value+'\n')


def heading(value):
    body.append('<h2>'+html.escape(value)+'</h2>');md.append('## '+value+'\n')


def table(headers,rows):
    body.append('<div class="table"><table><thead><tr>'+''.join('<th>'+html.escape(str(c))+'</th>' for c in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(c))+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>')
    md.extend(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,row))+' |' for row in rows]+[''])


def figure(name,caption):
    encoded=base64.b64encode((FOLDER/'figures'/f'{name}.png').read_bytes()).decode()
    body.append(f'<figure><img src="data:image/png;base64,{encoded}" alt="{html.escape(caption)}"><figcaption>{html.escape(caption)} · <a href="figures/{name}.svg">SVG</a></figcaption></figure>')
    md.append(f'![{caption}](figures/{name}.png)\n')


paragraph(f"Se han reconstruido las penetraciones de cada contacto en {D['checkpoints']} checkpoints de {D['runs']} runs completadas de la instantánea {D['snapshot_time']}. Todas las comparaciones se hacen al mismo objetivo de presión y separando carga y descarga.")
heading('Qué se calcula y qué distingue estas distribuciones')
paragraph('Para cada par de esferas se calcula la distancia mínima periódica entre centros y δ = R₁ + R₂ − d. Solo se incluyen pares con δ > 0 y cada par se cuenta una vez. Un árbol espacial identifica candidatos sin comparar todas las partículas entre sí. Las penetraciones se obtienen de la geometría guardada, no de fuerzas inferidas ni de una nueva simulación.')
paragraph('El histograma usa δ/D50, donde D50 es dos veces la mediana de radios de esa run. Esto facilita comparar runs con diámetros ligeramente distintos. Es una profundidad normalizada por un diámetro de referencia; no es la deformación relativa individual de cada par. El CSV también guarda media y desviación estándar en metros.')
paragraph('Se calcula media, mediana, desviación estándar, CV = σ/μ, percentiles 90 y 99 y máximo. Además se mide qué porcentaje de Σδ, ΣA, ΣVoverlap y tr(K) aportan el 10 % y el 1 % de contactos con mayor δ. El conjunto de contactos seleccionado es el mismo para las cuatro métricas. Los histogramas de contribución muestran en qué profundidades se acumula cada total.')
paragraph('Los histogramas están normalizados a 100 %: dos curvas similares pueden corresponder a números distintos de contactos. Por eso también se muestra M en la tabla. La contribución térmica utiliza A × distancia entre centros; tr(K) es el indicador geométrico adimensional de JPGen, no una conductividad física en W/(m·K).')
paragraph('La distinción matemática es Σδ² = M(μ² + σ²) = Mμ²(1 + CV²), con M el número de contactos y σ poblacional. Para radios efectivos comparables y penetraciones pequeñas, ΣA ≈ 2πRₑ𝒻 Mμ, mientras ΣVoverlap ≈ πRₑ𝒻 Mμ²(1 + CV²). Así se separan número de contactos, profundidad media y dispersión. En esta población polidispersa Rₑ𝒻 cambia entre pares: las contribuciones de área y volumen que se muestran se calculan con la geometría exacta, no con un radio constante.')
heading('Explorador de un objetivo fijo')
paragraph(f"Selecciona objetivo y rama. “Media entre runs” da el mismo peso a cada run, normalizando antes su histograma. Seleccionar una run muestra su distribución individual. Los ejes X e Y son fijos y comunes a todas las selecciones y a ambos gráficos. El eje horizontal es logarítmico; la altura representa porcentaje por intervalo, no densidad por unidad lineal de penetración. Se utilizan {len(D['edges_depth_D50'])-3} intervalos logarítmicos, más dos para valores fuera del rango central. Los valores fuera del rango central se indican debajo de los gráficos.")
body.append('''<section class="explorer"><div class="controls"><label>Rama <select id="stage"><option value="loading">Carga</option><option value="unloading">Descarga</option></select></label><label>Objetivo <select id="target"></select></label><label>Objetivo / checkpoint <input id="slider" type="range" min="0" max="19" step="1" value="0"></label><label>Run <select id="run"><option value="">Media entre runs</option></select></label></div><p id="selection"></p><svg id="hist" viewBox="0 0 1000 440" role="img" aria-label="Histograma de penetraciones y contribuciones"></svg><p id="outliers"></p><div id="metrics" class="table"></div><p id="description"></p></section>''')
heading('Cuánto pesa la cola de penetraciones grandes')
rows=[]
for stage,groups in D['groups'].items():
    for index in [0,10,19]:
        g=groups[index];m=g['metrics']
        rows.append([NAMES[stage],f"{g['target_pressure']/1000:.3f}",f"{m['cv_depth']['mean']:.3f}"]+[f"{100*m['top10_'+field+'_share']['mean']:.1f} %" for field in ['depth','area','volume','thermal']])
table(['Rama','Objetivo kPa','CV medio','10 % más penetrado: Σδ','ΣA','ΣV overlap','tr(K)'],rows)
load=D['groups']['loading'][0]['metrics'];unload=D['groups']['unloading'][0]['metrics']
paragraph(f"En el objetivo de 5 kPa, el CV medio es {load['cv_depth']['mean']:.3f} en carga y {unload['cv_depth']['mean']:.3f} en descarga. En carga, el 10 % más penetrado aporta {100*load['top10_area_share']['mean']:.1f} % del área y {100*load['top10_volume_share']['mean']:.1f} % del volumen; en descarga aporta {100*unload['top10_area_share']['mean']:.1f} % y {100*unload['top10_volume_share']['mean']:.1f} %, respectivamente. La descarga presenta en este objetivo una distribución relativamente más dispersa y un volumen más concentrado en los contactos de la cola. Esto compara proporciones y dispersión, no afirma que el volumen total sea mayor.")
paragraph('El 10 % más penetrado aporta una fracción mayor del volumen de overlap que del área y de la traza térmica. Esto confirma, en las distribuciones reconstruidas, que el volumen da más peso a la cola de penetraciones grandes. No implica que esos contactos sean necesariamente los de mayor fuerza o mayor radio: se han ordenado por δ, no por esas otras variables.')
figure('02_top10_contributions','Contribución del 10 % más penetrado en cada objetivo; bandas de percentiles 10–90 entre runs')
heading('Forma de la distribución y profundidad media')
figure('01_contact_histograms','Histogramas por objetivo fijo; media y percentiles 10–90 de las fracciones entre runs')
figure('03_depth_and_dispersion','Profundidad media y dispersión relativa por objetivo fijo')
paragraph('Dos runs pueden tener la misma suma de penetraciones pero diferir en número de contactos, profundidad media, dispersión o radios de los pares activos. Incluso manteniendo M y Σδ, una mayor dispersión aumenta Σδ². La fracción efectiva Mₑ𝒻/M = (Σδ)²/(MΣδ²) = 1/(1 + CV²) cuantifica la concentración de las penetraciones; es un índice matemático, no el número de contactos que conducen calor.')
heading('Valores por checkpoint y objetivo')
rows=[]
for stage,groups in D['groups'].items():
    for g in groups:
        m=g['metrics'];rows.append([NAMES[stage],g['checkpoint'],f"{g['target_pressure']/1000:.3f}",f"{m['contacts']['mean']:.0f}",f"{m['mean_depth_m']['mean']*1e6:.2f}",f"{m['cv_depth']['mean']:.3f}",f"{100*m['top10_volume_share']['mean']:.1f} %",f"{100*m['top1_volume_share']['mean']:.1f} %"])
table(['Rama','Checkpoint','Objetivo kPa','Contactos medios','δ media, µm','CV medio','ΣV del 10 % más penetrado','ΣV del 1 % más penetrado'],rows)
heading('Auditoría y límites de la interpretación')
paragraph(f"Máxima diferencia absoluta entre contactos geométricos y los deducidos de MCN: {D['audit']['max_absolute_contact_count_difference']:.3g}. Error relativo máximo al reproducir Σδ: {D['audit']['audit_depth_relative_error_max']:.3g}; ΣA: {D['audit']['audit_area_relative_error_max']:.3g}; ΣV: {D['audit']['audit_volume_relative_error_max']:.3g}; tr(K): {D['audit']['audit_thermal_relative_error_max']:.3g}. Pares completamente contenidos en otra esfera: {D['audit']['contained_contacts_total']}.")
paragraph(f"Al evaluar las aproximaciones de penetración pequeña con el radio efectivo real de cada par, el error relativo máximo frente al cálculo exacto es {100*max(abs(r['small_overlap_area_approx_relative_error']) for r in D['rows']):.3f} % para la suma de áreas y {100*max(abs(r['small_overlap_volume_approx_relative_error']) for r in D['rows']):.3f} % para la suma de volúmenes. Esto respalda el uso de las dependencias lineal y cuadrática en la explicación geométrica de estos checkpoints.")
paragraph('La auditoría comprueba que las distribuciones reproducen los totales utilizados en el estudio anterior. No demuestra por sí sola que la dispersión explique causalmente las correlaciones entre runs. Para esa atribución habría que comparar a objetivo fijo los cambios de M, μ, CV y la composición de radios de los contactos, controlando también la presión real. No se han alterado resultados ni relanzado simulaciones.')
paragraph('Las bandas de las figuras son percentiles entre runs, no intervalos de confianza. Las diferencias entre carga y descarga se comparan al objetivo nominal; sigue existiendo la tolerancia de presión real documentada en el informe térmico. Los histogramas se guardan como agregados por checkpoint; no se exporta una fila por cada par.')
body.append('<p><a href="checkpoint_contact_metrics.csv">Métricas por run y checkpoint, CSV</a> · <a href="distributions.json">Histogramas y estadísticas, JSON</a> · <a href="report.md">Informe Markdown</a> · <a href="../report.html">Correlaciones a objetivo fijo y traza térmica</a>.</p>')
md.append('Archivos: [métricas](checkpoint_contact_metrics.csv), [histogramas](distributions.json), [estudio térmico](../report.html).\n')
paragraph('Reproducción: scripts/analyze_contact_distributions.py, scripts/plot_contact_distributions.py y scripts/write_contact_distribution_report.py. El extractor utiliza dos hilos y una caché por checkpoint. Las figuras se exportan como PNG y SVG y este HTML funciona sin conexión.')

js=r'''
const D=JSON.parse(document.getElementById('dataset').textContent),$=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={count:'Contactos',depth:'Σδ',area:'ΣA',volume:'ΣV overlap',thermal:'tr(K)'},colors={count:'#637680',depth:'#147aa6',area:'#ba772d',volume:'#8846a5',thermal:'#b63d45'};
const edges=D.edges_depth_D50;
let occupiedFirst=edges.length-3,occupiedLast=1,maximumFraction=0;
for(const row of D.rows){
 for(let k=1;k<row.histograms.count.length-1;k++)if(row.histograms.count[k]>0){occupiedFirst=Math.min(occupiedFirst,k);occupiedLast=Math.max(occupiedLast,k);}
 for(const raw of Object.values(row.histograms)){const total=raw.reduce((a,b)=>a+b,0);for(let k=1;k<raw.length-1;k++)maximumFraction=Math.max(maximumFraction,raw[k]/total);}
}
const first=Math.max(1,occupiedFirst-1),last=Math.min(edges.length-3,occupiedLast+1),lo=Math.log10(edges[first]),hi=Math.log10(edges[last+1]);
const fixedYMax=Math.ceil(maximumFraction*100*1.12*2)/2;
D.targets.forEach((p,i)=>$('target').add(new Option((p/1000).toFixed(3)+' kPa',i)));
const runs=new Map(D.rows.map(r=>[r.run_id,r.run]));[...runs].sort((a,b)=>a[1].localeCompare(b[1])).forEach(([id,name])=>$('run').add(new Option(name,id)));
function node(tag,attrs,text){const n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;$('hist').append(n);return n;}
function update(){
 const stage=$('stage').value,index=+$('target').value,g=D.groups[stage][index],run=$('run').value;
 $('slider').value=index;const r=run?D.rows.find(r=>r.run_id===run&&r.stage===stage&&Math.abs(r.target_pressure-g.target_pressure)<1e-6):null;
 const h={};for(const field of Object.keys(labels)){if(r){const raw=r.histograms[field],sum=raw.reduce((a,b)=>a+b,0);h[field]=raw.map(v=>v/sum);}else h[field]=g.histograms[field].mean_fraction;}
 $('selection').textContent=`${stage==='loading'?'Carga':'Descarga'} · objetivo ${(g.target_pressure/1000).toFixed(3)} kPa · checkpoint ${g.checkpoint} · ${r?r.run:g.count+' runs con igual peso'}. Ejes fijos: X = ${edges[first].toExponential(2)}–${edges[last+1].toExponential(2)} δ/D50; Y = 0–${fixedYMax} %.`;
 $('hist').replaceChildren();
 for(let chart=0;chart<2;chart++){
  const left=chart===0?65:550,right=chart===0?455:940,bottom=345,top=65;
  const fields=chart===0?['count']:['depth','area','volume','thermal'];
  const ymax=fixedYMax;
  const X=v=>left+(Math.log10(v)-lo)/(hi-lo)*(right-left),Y=v=>bottom-v/ymax*(bottom-top);
  node('text',{x:(left+right)/2,y:28,'text-anchor':'middle','font-size':16},chart===0?'Distribución de contactos':'Distribución de las contribuciones');
  for(let k=0;k<=4;k++){const yv=ymax*k/4;node('line',{x1:left,x2:right,y1:Y(yv),y2:Y(yv),stroke:'#e2e6e8'});node('text',{x:left-6,y:Y(yv)+4,'text-anchor':'end','font-size':11},yv.toFixed(1)+' %');}
  for(let power=Math.ceil(lo);power<=Math.floor(hi);power++){const value=10**power;node('line',{x1:X(value),x2:X(value),y1:top,y2:bottom,stroke:'#e2e6e8'});node('text',{x:X(value),y:370,'text-anchor':'middle','font-size':12},'10^'+power);}
  for(const f of fields){let line=[];
   for(let k=first;k<=last;k++){const center=Math.sqrt(edges[k]*edges[k+1]),x=X(center),y=Y(100*h[f][k]);line.push(x+','+y);
    if(chart===0){const bar=node('rect',{x:X(edges[k]),y,width:Math.max(.1,X(edges[k+1])-X(edges[k])-.15),height:bottom-y,fill:colors[f]});const title=document.createElementNS(NS,'title');title.textContent=`δ/D50: ${edges[k].toExponential(2)}–${edges[k+1].toExponential(2)}\n${(100*h[f][k]).toFixed(3)} % de contactos`;bar.append(title);}}
   if(chart===1)node('polyline',{points:line.join(' '),fill:'none',stroke:colors[f],'stroke-width':2.5});
  }
  node('text',{x:(left+right)/2,y:408,'text-anchor':'middle','font-size':14},'Penetración δ / D50 (escala logarítmica)');
 }
 ['depth','area','volume','thermal'].forEach((f,i)=>{node('line',{x1:550+i*95,x2:569+i*95,y1:48,y2:48,stroke:colors[f],'stroke-width':3});node('text',{x:574+i*95,y:52,'font-size':12},labels[f]);});
 $('outliers').textContent=`Contactos fuera del rango central δ/D50 ∈ [10⁻⁹, 1]: ${(100*(h.count[0]+h.count.at(-1))).toPrecision(3)} %. Cada serie de contribuciones suma el 100 % incluyendo esos intervalos.`;
 const value=k=>r?r[k]:g.metrics[k].mean;
 const metrics=[['Número de contactos',value('contacts').toFixed(0)],['δ media (µm)',(value('mean_depth_m')*1e6).toFixed(3)],['δ mediana / D50',value('median_depth_D50').toExponential(3)],['P90 δ/D50',value('p90_depth_D50').toExponential(3)],['P99 δ/D50',value('p99_depth_D50').toExponential(3)],['CV = σ/μ',value('cv_depth').toFixed(3)],['M efectivo / M',(100*value('effective_contact_fraction')).toFixed(1)+' %']];
 $('metrics').innerHTML='<table><thead><tr>'+metrics.map(([name])=>'<th>'+esc(name)+'</th>').join('')+'</tr></thead><tbody><tr>'+metrics.map(([,v])=>'<td>'+esc(v)+'</td>').join('')+'</tr></tbody></table><table><thead><tr><th>Contactos ordenados por δ</th>'+['depth','area','volume','thermal'].map(f=>'<th>'+labels[f]+'</th>').join('')+'</tr></thead><tbody>'+['top10','top1'].map((prefix,i)=>'<tr><th>'+(i===0?'10 %':'1 %')+' más penetrado</th>'+['depth','area','volume','thermal'].map(f=>'<td>'+(100*value(prefix+'_'+f+'_share')).toFixed(2)+' %</td>').join('')+'</tr>').join('')+'</tbody></table>';
 $('description').textContent=r?'Métricas de esta run. Los contactos más penetrados se seleccionan redondeando su número hacia arriba.':'Las métricas son medias entre runs de los estadísticos individuales. Por ejemplo, la mediana mostrada es la media de las medianas por run, no la mediana de todos los contactos agrupados.';
}
for(const id of ['stage','target','run'])$(id).addEventListener('change',update);$('slider').addEventListener('input',()=>{$('target').value=$('slider').value;update();});update();
'''
style='body{font:16px system-ui;line-height:1.6;background:#f7f8f9;color:#283b47;margin:0}main{max-width:1180px;margin:auto;padding:30px}h1,h2{line-height:1.25}h2{margin-top:38px}a{color:#0878af}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px;background:white;margin:15px 0}th,td{padding:9px;border:1px solid #dce4e9;text-align:left}th{background:#eaf0f4}.controls{display:flex;gap:16px;flex-wrap:wrap}.controls label{display:flex;flex-direction:column}select{padding:7px;max-width:280px}.explorer{background:white;padding:20px;border:1px solid #dce4e9;border-radius:10px}svg,img{width:100%;height:auto}figure{margin:25px 0}figcaption{font-size:14px;color:#526471}@media print{.controls{display:none}figure{break-inside:avoid}}'
title='Distribución de penetraciones por contacto a objetivo fijo'
data=json.dumps(D,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
(FOLDER/'report.html').write_text('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+style+'</style></head><body><main><h1>'+title+'</h1>'+''.join(body)+'</main><script id="dataset" type="application/json">'+data+'</script><script>'+js+'</script></body></html>',encoding='utf-8')
(FOLDER/'report.md').write_text('# '+title+'\n\n'+'\n'.join(md),encoding='utf-8')
print(FOLDER/'report.html')

add_population_switch(FOLDER / "report.html", FOLDER, contact_only=True)
