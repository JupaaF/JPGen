#!/usr/bin/env python3
"""Write Spanish Markdown/HTML reports from the reproducible correlation analysis."""

import base64
import csv
import html
import json
from pathlib import Path
import re
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
FOLDER=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'runs/mcn_overlap_density_characterization/2026-10-03_06-54-07Z/correlation_study'
D=json.loads((FOLDER/'statistics.json').read_text())
LABELS=D['labels'];FIELDS=D['primary']
STAGES={'loading':'Carga','unloading':'Descarga'}
lines=[]


def text(value):
    lines.extend(value.strip().splitlines());lines.append('')


def number(value):
    if value==0:return '0'
    return f'{value:.4g}' if abs(value)>=.001 else f'{value:.3e}'


def interval(low,high):
    return f'[{number(low)}, {number(high)}]'


def table(headers,rows):
    lines.append('| '+' | '.join(headers)+' |');lines.append('| '+' | '.join(['---']*len(headers))+' |')
    for row in rows:lines.append('| '+' | '.join(map(str,row))+' |')
    lines.append('')


def figure(name,caption):
    text(f'![{caption}](figures/{name}.png)\n\n{caption}. Versión vectorial: [SVG](figures/{name}.svg).')


text('# Estudio de correlación: MCN, densidad, overlaps y presión')
text(f"Lote 2026-10-03_06-54-07Z. Datos: {D['runs']} simulaciones completadas, {D['points']} estados aceptados de carga y descarga, 20 objetivos por rama y simulación. El tamaño independiente es 48 simulaciones, no 1920 observaciones independientes. Se estudia la instantánea {D['snapshot_time']}. Los 48 finales de evolución libre no entran en los modelos porque pertenecen a un régimen transitorio diferente. La suite original de 100 repeticiones sigue incompleta; estas conclusiones son provisionales para las terminadas.")
text('## 1. Qué muestran los datos')
text('Las correlaciones positivas fuertes del recorrido completo no describen una relación universal entre densidad y MCN. Mezclan la evolución bajo presión con diferencias entre packings. A un objetivo fijo, los packings más densos sí tienden a tener mayor MCN; al quitar además el desplazamiento persistente de cada simulación, esa asociación residual ya no está claramente resuelta. Esto distingue tres preguntas: evolución a lo largo del recorrido, diferencias entre packings y desviaciones dentro de un packing a presión comparable.')
text('El ciclo tiene memoria: a la misma presión real, la descarga presenta menor MCN pero mayor fracción sólida que la carga. Por tanto, una única curva MCN = f(density), sin conocer presión e historia, pierde información. Tampoco los overlaps de longitud, área y volumen son intercambiables: después de igualar presión, longitud y área disminuyen en descarga, mientras el volumen de intersecciones aumenta.')
text('La presión y la rama ya predicen la mayor parte de la variación de MCN. Añadir fracción sólida y volumen de overlap normalizado reduce un 36 % el RMSE fuera de muestra, dentro del mismo protocolo. Esto es utilidad predictiva, no identificación de un efecto causal de ninguna de las variables.')

text('## 2. Datos, definiciones y auditoría')
text('Cada registro proviene del mismo checkpoint físico: MCN y las densidades se leen del paso guardado y los overlaps se reconstruyen de sus posiciones, radios y caja periódica. No se mezcla un overlap de un paso con un MCN de otro. Se utiliza cada par de esferas una sola vez, con distancia periódica mínima. Los archivos de simulación permanecen intactos. Las 48 semillas son diferentes y cada población tiene 15000 partículas.')
table(['Variable','Definición y cautela'],[
 ['MCN','2 × contactos / 15000. Incluye partículas sin contactos (rattlers) en el denominador.'],
 ['Fracción sólida φ','Volumen nominal de las esferas / volumen de caja; no descuenta la suma de overlaps.'],
 ['Density aparente','ρ = 2650 × φ, en kg/m³. Es información redundante, no un predictor independiente.'],
 ['Σδ, ΣA, ΣVoverlap','Penetración total, área de círculos de intersección y volumen total de lentes. No son la unión geométrica de todas las esferas.'],
 ['Overlaps normalizados','Σδ/L, ΣA/L² y ΣVoverlap/V, con L = V^(1/3). Su normalización también depende del tamaño de caja.'],
 ['δmedio/D50','Σδ / (15000 × MCN/2) / D50; D50 se calcula de los radios originales de cada run. MCN aparece en su denominador.'],
 ['Presión','Presión real guardada; distinta del objetivo nominal.'],
 ['Checkpoint','Número secuencial de estado, no una causa física ni un predictor causal. Se usan los objetivos nominales para emparejar carga y descarga.']])
text(f"El error máximo de la identidad density = 2650 φ es {D['audit']['material_density_identity_max_error']}. La mayor desviación de presión respecto al objetivo es {100*D['audit']['max_target_pressure_relative_error']:.3f} %. Dos ramas al mismo objetivo nominal pueden diferir hasta {100*D['audit']['pair_actual_pressure_relative_difference_max']:.3f} % en presión real. Los objetivos logarítmicos invertidos se emparejan con tolerancia relativa 1e-12, evitando diferencias de redondeo de punto flotante.")
text('Para las correlaciones principales se elimina la densidad aparente redundante, pero statistics.json conserva las matrices descriptivas de todas las variables, incluidas presión, checkpoint y overlaps sin normalizar. No se excluyeron outliers ni simulaciones completadas del visualizador.')

text('## 3. Correlaciones descriptivas: fuertes, pero no todas lineales')
rows=[]
for stage,name in STAGES.items():
    g=D['correlations'][stage]
    for j in range(1,6):
        raw=g['raw'];rows.append([name,'MCN vs '+LABELS[j],f"{raw['pearson'][0][j]:.4f}",f"{g['spearman'][0][j]:.4f}",interval(raw['ci_low'][0][j],raw['ci_high'][0][j])])
table(['Rama','Relación','Pearson r','Spearman ρ','IC 95 % de r, por simulación'],rows)
text('Pearson mide relación lineal; Spearman, relación monotónica por rangos. MCN–volumen de overlap es mucho más monotónica que lineal: Spearman ≈ 0.991–0.992 frente a Pearson ≈ 0.903–0.910. Una recta en la escala original perdería parte de esa curvatura. Los intervalos se calculan con 2000 remuestreos de simulaciones enteras, conservando juntos sus 20 objetivos; no se usan los p-valores i.i.d. de los 960 checkpoints de cada rama.')
figure('02_scatter_pressure','Relaciones brutas coloreadas por presión real')
text('La correlación entre Σδ/L y ΣA/L² es aproximadamente 0.999998 en ambas ramas: aportan casi la misma ordenación en estos datos. La identidad density–φ es exacta y las métricas de overlap comparten geometría y denominadores. Juntarlas como si fueran medidas independientes exageraría la cantidad de evidencia.')
figure('01_correlation_matrices','Matrices de Pearson brutas y con efectos de run, objetivo y presión real eliminados')

text('## 4. Separar presión, diferencias entre packings y desviaciones internas')
text('Se calculan cuatro versiones. Bruta: todos los checkpoints. Dentro de run: se resta la media de cada simulación, pero el recorrido de presión permanece. A objetivo fijo: se resta la media de cada objetivo entre simulaciones, quitando la curva de presión sin imponer que sea lineal o cúbica. Ajustada completa: se eliminan efectos aditivos de run y objetivo y luego la presión real residual; así se controla también la tolerancia del servo. No es una correlación causal ni un modelo dinámico de todas las variables internas.')
rows=[]
for stage,name in STAGES.items():
    for mode,title in [('raw','Bruta'),('within_run','Dentro de run'),('target_adjusted','A objetivo fijo'),('controlled','Run + objetivo + P real')]:
        g=D['correlations'][stage][mode]
        rows.append([name,title,*[f"{g['pearson'][0][j]:.3f} {interval(g['ci_low'][0][j],g['ci_high'][0][j])}" for j in [1,4]]])
table(['Rama','Ajuste','MCN–φ: r e IC 95 %','MCN–ΣV/V: r e IC 95 %'],rows)
text('A objetivo fijo, MCN–φ permanece en ≈ +0.661 en ambas ramas. Eso es una relación entre realizaciones del packing a presión nominal comparable. La correlación entre las medias de cada run es +0.694 en carga y +0.688 en descarga. Tras quitar esos desplazamientos persistentes, MCN–φ pasa a −0.124 en carga y +0.135 en descarga, con ambos IC incluyendo cero. Los datos no resuelven una asociación lineal residual consistente entre MCN y φ bajo ese ajuste más estricto. Esto no equivale a afirmar que la densidad carezca de importancia física.')
text('MCN–volumen de overlap presenta una inversión de signo según el nivel de análisis. Durante el recorrido la asociación es positiva; entre runs a objetivo fijo es ≈ −0.534 en carga y −0.554 en descarga. Entre medias de run es ≈ −0.889 y −0.885. Después del ajuste completo queda una asociación negativa pequeña (−0.190/−0.170), con mayor incertidumbre y un IC que incluye cero en descarga. La inversión muestra por qué no debe inferirse una ley de contacto a partir de la nube agregada.')
text('δmedio/D50 conserva una correlación residual negativa con MCN de aproximadamente −0.65. Pero esta variable divide por el número de contactos derivado de MCN: parte de la relación puede ser acoplamiento matemático. No debe presentarse como una prueba independiente de que aumentar MCN causa menor penetración. Las sumas de longitud y área, en cambio, tienen correlaciones residuales positivas pequeñas, aproximadamente +0.21 y +0.30.')
figure('05_controlled_relationships','Relaciones residuales, con presión e identidad del packing controladas')
figure('06_fixed_pressure_correlations','Correlación entre packings por cada objetivo de presión, sin agrupar el recorrido')
rows=[]
for stage,name in STAGES.items():
    v=D['correlations'][stage]['variance_partition']
    for j in [0,1,4]:rows.append([name,LABELS[j],f"{v['target_percent'][j]:.5f} %",f"{v['run_percent'][j]:.5f} %",f"{v['interaction_percent'][j]:.5f} %"])
table(['Rama','Variable','Variación entre objetivos','Offset entre runs','Interacción/resto'],rows)
text('Esta descomposición balanceada es descriptiva: la suma de los componentes es 100 %. El objetivo de presión y todo lo que cambia junto a él concentra más del 99 % de la variación de MCN y casi el 99.999 % de la del overlap de volumen normalizado. Las correlaciones ajustadas se calculan sobre un resto muy pequeño, por lo que deben interpretarse con sus intervalos y con cautela sobre errores de medición y de reconstrucción. La descomposición no demuestra que la presión sea la única causa.')

text('## 5. Histéresis: comparar a la misma presión real')
text('Primero se emparejan carga y descarga dentro del mismo run y objetivo. Después se interpola cada rama en log(P real) en los 18 objetivos interiores comunes, sin extrapolar a los extremos. La diferencia es siempre descarga − carga. Cada run aporta un resumen medio de esos 18 objetivos igualmente ponderados en escala logarítmica. Esta media no es energía disipada ni trabajo mecánico.')
rows=[]
for key,label in zip(FIELDS,LABELS):
    h=D['hysteresis'][key]
    rows.append([label,number(h['matched_mean']),interval(*h['matched_ci95']),f"{h['matched_relative_percent']:+.3f} %",f"{h['positive_runs']} + / {h['negative_runs']} −"])
table(['Variable','Diferencia a P real comparable','IC 95 % de la media','Respecto a carga emparejada','Signo del resumen por run'],rows)
h=D['hysteresis']['solid_fraction']
text(f"La descarga queda más densa en aproximadamente {100*h['matched_mean']:.5f} puntos porcentuales de φ, equivalente a {2650*h['matched_mean']:.3f} kg/m³ de densidad aparente. A la vez pierde aproximadamente 0.0485 unidades de MCN de media. Todas las 48 realizaciones tienen ese signo en su resumen interior. Mayor densidad y mayor número de contactos no avanzan necesariamente juntos después de un ciclo; conocer la historia importa.")
figure('04_hysteresis','Diferencias nominales e interpoladas a presión real comparable')
text('La figura permite ver un problema práctico: a objetivos nominales iguales, longitud, área y penetración media pueden aparentar aumentar en parte de la descarga. Al igualar presión real, sus diferencias medias son negativas. El servo alcanza los objetivos con una tolerancia pequeña, pero esa tolerancia es comparable o superior a varios efectos de histéresis que se intentan medir. Una comparación solamente por número de checkpoint u objetivo puede cambiar la interpretación.')
rows=[]
for key,label in zip(FIELDS,LABELS):
    h=D['hysteresis'][key]
    rows.append([label,number(h['matched_mean']),number(h['matched_pchip_mean']),f"{h['matched_pchip_positive_runs']} + / {h['matched_pchip_negative_runs']} −"])
table(['Variable','Interpolación lineal en log P','Sensibilidad PCHIP','Signos PCHIP por run'],rows)
text('El signo se conserva usando interpolación cúbica de Hermite de forma preservada (PCHIP). La estimación de histéresis del volumen de overlap pasa de 3.30e−7 a 3.43e−7: el signo es estable, pero el cambio de método es aproximadamente un 4 % del efecto y no está cubierto por el IC de remuestreo entre runs. Debe comunicarse como una diferencia aproximada, no con falsa precisión. Los otros efectos también se muestran con ambos métodos.')
text('Los seis resúmenes apareados tienen el mismo signo en las 48 simulaciones. El contraste binomial bilateral de signos da p = 7.105e−15 y el ajuste Benjamini–Hochberg entre esos seis resúmenes conserva ese valor. La interpretación es una dirección reproducible entre semillas bajo este protocolo; no causalidad ni validez para materiales distintos. Los IC de las curvas por objetivo son puntuales, no bandas simultáneas para los 20 objetivos. Las restantes correlaciones son exploratorias y sus IC tampoco corrigen todas las comparaciones.')
text('El incremento del volumen de intersecciones junto a una caída de penetración media es compatible con cambios en la distribución y en los tamaños de los pares que están en contacto. Los totales de longitud, área y volumen no determinan por sí solos esa distribución. Para confirmarlo harían falta histogramas de penetración por contacto y radios efectivos, no solo sus sumas.')

text('## 6. Curvas de presión y no linealidad del overlap')
with (FOLDER/'checkpoint_data.csv').open() as stream:
    checkpoint_rows=list(csv.DictReader(stream))
checkpoint_relationships=[]
for stage,title in STAGES.items():
    subset=[row for row in checkpoint_rows if row['stage']==stage]
    checkpoints=[float(row['checkpoint']) for row in subset]
    checkpoint_relationships.append([title]+[f"{statistics.correlation(checkpoints,[float(row[field]) for row in subset]):.4f}" for field in ['pressure',FIELDS[0],FIELDS[1],FIELDS[4]]])
table(['Correlación del número de checkpoint','Presión real','MCN','Fracción sólida','ΣVoverlap/V'],checkpoint_relationships)
text(f"El número de checkpoint aumenta mientras la presión sube en carga y baja en descarga. Por eso sus correlaciones cambian de signo entre ramas. Agrupando ambas, checkpoint–MCN es {D['pooled_pearson'][8][0]:.4f} y checkpoint–φ es {D['pooled_pearson'][8][1]:.4f}: valores próximos a cero que ocultan recorridos muy ordenados. El índice sirve para navegar y situar el estado dentro de la historia, pero una correlación global con ese índice no mide la fuerza de una relación física. Conviene usar presión real y rama, y distinguir el checkpoint aceptado del tiempo físico transcurrido.")
figure('03_pressure_profiles','Evolución media de las seis métricas; bandas de incertidumbre de la media entre simulaciones')
text('En carga, la media de MCN pasa de 3.704 a 4.888 y φ de 0.60179 a 0.62066 entre los objetivos de 5 y 200 kPa. En descarga al objetivo de 5 kPa, las medias son MCN = 3.617 y φ = 0.60245. Estas cifras de extremos corresponden a los objetivos nominales, no a la comparación interpolada interior. La fracción inicial 0.56 pertenece al estado anterior a la servo-compresión, fuera de estas nubes de objetivos aceptados.')
rows=[]
for key in [FIELDS[i] for i in [2,3,4,5]]:
    entry=D['power_laws'][key]
    rows.append([LABELS[FIELDS.index(key)],*[f"{entry[s]['mean_exponent']:.4f} {interval(*entry[s]['ci95'])}" for s in STAGES]])
table(['Métrica en ajuste overlap ∝ P^b','b carga e IC 95 %','b descarga e IC 95 %'],rows)
text('Los ajustes log-log se hacen por run y rama antes de resumir los exponentes. Describen el intervalo 5–200 kPa; no son constantes universales ni una validación aislada de una ley de contacto. Cambian a la vez penetraciones, número de contactos, radios de los pares activos y volumen de caja. Los overlaps de volumen crecen con presión mucho más rápido que los de longitud y área, coherente con su mayor no linealidad geométrica.')
figure('08_overlap_pressure_scaling','Exponentes descriptivos de los overlaps frente a presión')

text('## 7. Predicción de MCN en un packing que no participa en el ajuste')
text('La validación deja fuera un run completo en cada una de 48 particiones; ambas ramas de ese run quedan fuera juntas. El modelo base usa un polinomio cúbico de log presión real, con coeficientes separados por rama. Se añaden φ, log(ΣVoverlap/V) o ambos, sin introducir el identificador de run como predictor. El escalado se ajusta solo con los runs de entrenamiento.')
models={'pressure_branch':'Presión + rama','plus_density':'+ fracción sólida','plus_overlap':'+ log overlap volumen','plus_density_overlap':'+ fracción sólida + log overlap'}
rows=[]
for key,title in models.items():
    m=D['prediction'][key];rows.append([title,f"{m['R2']:.6f}",f"{m['RMSE']:.6f}",f"{m['MAE']:.6f}",interval(*m['RMSE_ci95_conditional'])])
table(['Modelo','R² fuera de muestra','RMSE MCN','MAE MCN','IC 95 % RMSE condicional'],rows)
text('El RMSE cae de 0.03303 a 0.02113 al añadir las dos variables: mejora del 36.0 % frente al modelo de presión y rama. La mejora no implica que esas variables expliquen causalmente MCN; son observaciones contemporáneas del mismo estado. Tampoco es una predicción de estados futuros ni de presiones fuera de 5–200 kPa. Los IC de RMSE remuestrean runs de las predicciones ya obtenidas; no incluyen una refitación completa del modelo en cada bootstrap.')
figure('07_out_of_run_prediction','Predicción fuera de run y comparación de error')
text('La multicolinealidad impide interpretar ingenuamente los coeficientes. En un diagnóstico lineal de log P, φ y log overlap volumen, los VIF son aproximadamente 11669, 8.74 y 11745. Presión y overlap volumétrico son casi redundantes como indicadores del estado del recorrido. Una buena predicción conjunta no convierte cada coeficiente en un efecto físico independiente.')
worst=sorted(enumerate(D['prediction']['plus_density_overlap']['per_run_RMSE']),key=lambda v:v[1],reverse=True)[:5]
table(['Run con mayor error del modelo completo','RMSE'],[[D['run_metadata'][D['run_order'][i]]['label'],f'{value:.6f}'] for i,value in worst])
text('Esos runs se conservan en el análisis. Las estadísticas por run y los rangos al dejar uno fuera están en statistics.json para revisar sensibilidad sin eliminar realizaciones a posteriori.')

text('## 8. Qué conviene medir o variar después')
text('Para una ley MCN–densidad transferible, repetir con varias fracciones iniciales, fricciones y distribuciones de radios, manteniendo emparejadas las semillas de cada comparación. Ajustar modelos con presión e historia explícitas y dejar fuera condiciones completas, no solo semillas del mismo protocolo. Este estudio mantiene esos parámetros fijos y no puede identificarlos como causas.')
text('Para histéresis precisa, bajar la tolerancia relativa del objetivo de presión o aceptar a una presión real común antes de comparar, y guardar más objetivos cerca de las zonas donde las curvas divergen. La comparación nominal actual es insuficiente para efectos del orden del 1 %. La sensibilidad a interpolación debe acompañar los intervalos entre semillas.')
text('Para relacionar topología y deformación, guardar penetraciones por contacto, distribución de radios de los pares activos, cuantiles y dispersión de penetración, fracción de rattlers y coordinación excluyéndolos. Así se separa la creación/destrucción de contactos de la deformación de contactos existentes. Normalizar overlaps y dividir por MCN son decisiones distintas y ambas pueden introducir dependencias matemáticas.')
text('## 9. Límites, reproducción y fuentes')
text('El análisis incluye solo los 48 runs terminados de la instantánea. Si el tiempo de convergencia está relacionado con el estado final, completar primero algunos runs puede introducir sesgo de selección. Actualizar después de finalizar las 100 repeticiones antes de publicar conclusiones. Los IC bootstrap cubren variación entre estas semillas, no error de modelo de contacto, integración temporal, reconstrucción geométrica, selección de completadas o extrapolación.')
text('Las asociaciones no establecen causalidad. Los ajustes eliminan efectos aditivos de run y objetivo, no toda posible estructura dinámica, contactos o morfología. Las curvas son medidas repetidas con historia; el remuestreo siempre conserva bloques de simulación. Los p-valores convencionales de los checkpoints agrupados no se utilizan.')
text('Referencias metodológicas: [Pearson y sus supuestos, documentación SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html); [Spearman, documentación SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.spearmanr.html); [Bakdash y Marusich, medidas repetidas](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2017.00456/full). Se utiliza un ajuste por factores y bootstrap de bloques propio; no se afirma que sea exactamente el estimador rmcorr del artículo.')
text('Archivos de auditoría: [Datos de checkpoints](checkpoint_data.csv), [Estadísticas y predicciones](statistics.json), [Correlaciones e intervalos](correlations.csv), [Correlaciones por objetivo](correlations_by_pressure.csv). Las figuras también se guardan como SVG y PNG independientes.')
text(f"Huella SHA-256 del HTML fuente utilizado: {D['source_sha256']}. Bootstrap: {D['bootstrap']} repeticiones; semilla {D['bootstrap_seed']}. El análisis numérico usa NumPy/SciPy y los gráficos Matplotlib. La generación de este informe no relanza simulaciones.")
text('Comando numérico: .venv/bin/python scripts/analyze_mcn_correlations.py. Después generar figuras con scripts/plot_mcn_correlations.py en un Python con Matplotlib compatible, y el informe con .venv/bin/python scripts/write_mcn_correlation_report.py. El HTML de este informe lleva las imágenes incrustadas y funciona sin conexión.')

(FOLDER/'report.md').write_text('\n'.join(lines),encoding='utf-8')
with (FOLDER/'correlations.csv').open('w',newline='') as stream:
    writer=csv.writer(stream);writer.writerow(['stage','adjustment','variable_1','variable_2','pearson_r','ci95_low','ci95_high'])
    for stage in STAGES:
        for mode in ['raw','within_run','target_adjusted','controlled']:
            g=D['correlations'][stage][mode]
            for i in range(6):
                for j in range(i+1,6):writer.writerow([stage,mode,FIELDS[i],FIELDS[j],g['pearson'][i][j],g['ci_low'][i][j],g['ci_high'][i][j]])
with (FOLDER/'correlations_by_pressure.csv').open('w',newline='') as stream:
    writer=csv.writer(stream);writer.writerow(['stage','pressure_target_pa','variable_1','variable_2','pearson_r_between_runs'])
    for stage in STAGES:
        for t,p in enumerate(D['target_pressure']):
            for i in range(6):
                for j in range(i+1,6):writer.writerow([stage,p,FIELDS[i],FIELDS[j],D['correlations'][stage]['by_target_pearson'][t][i][j]])


def inline(value):
    value=html.escape(value)
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)',lambda m:f'<a href="{m[2]}">{m[1]}</a>',value)


body=[];in_table=False
for line in lines:
    if line.startswith('|'):
        cells=[cell.strip() for cell in line.strip('|').split('|')]
        if not in_table:
            body.append('<div class="table"><table><thead><tr>'+''.join('<th>'+inline(c)+'</th>' for c in cells)+'</tr></thead><tbody>');in_table=True
        elif not all(c=='---' for c in cells):body.append('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in cells)+'</tr>')
        continue
    if in_table:body.append('</tbody></table></div>');in_table=False
    if not line:continue
    if line.startswith('!['):
        match=re.match(r'!\[([^\]]*)\]\(([^)]+)\)',line)
        image=(FOLDER/match[2]).read_bytes()
        body.append(f'<figure><img src="data:image/png;base64,{base64.b64encode(image).decode()}" alt="{html.escape(match[1])}"></figure>')
    elif line.startswith('## '):body.append('<h2>'+inline(line[3:])+'</h2>')
    elif line.startswith('# '):body.append('<h1>'+inline(line[2:])+'</h1>')
    else:body.append('<p>'+inline(line)+'</p>')
if in_table:body.append('</tbody></table></div>')
style='body{font:16px system-ui;color:#34454d;background:#fdf6e3;line-height:1.6;margin:0}main{max-width:1160px;margin:auto;padding:32px}h1,h2{color:#073642;line-height:1.3}h2{margin-top:42px}a{color:#268bd2}table{border-collapse:collapse;width:100%;font-size:14px;background:#fff}th,td{padding:10px;border:1px solid #ddd;text-align:left}th{background:#eee8d5}.table{overflow:auto}figure{margin:24px 0}img{width:100%;height:auto}@media print{body{background:white}main{padding:0}h2{break-after:avoid}figure{break-inside:avoid}}'
(FOLDER/'report.html').write_text('<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Correlación MCN, density y overlaps</title><style>'+style+'</style><main>'+''.join(body)+'</main></html>',encoding='utf-8')
print(FOLDER/'report.html')
