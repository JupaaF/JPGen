"""Population-specific report prose using the same analysis and section structure."""


def correlation_text(value, d):
    if d.get('population') != 'without_rattlers':
        return value
    c = d['correlations']
    h = d['hysteresis']
    p = d['prediction']
    replacements = {
        'Las correlaciones positivas fuertes':
            'Las correlaciones del recorrido completo mezclan la evolución bajo presión con diferencias entre packings. '
            f"Sin rattlers, MCN–φ tiene r bruto {c['loading']['raw']['pearson'][0][1]:+.3f} en carga y {c['unloading']['raw']['pearson'][0][1]:+.3f} en descarga. "
            'Las tablas separan evolución a lo largo del recorrido, diferencias entre packings y desviaciones dentro de un packing a presión comparable.',
        'El ciclo tiene memoria:':
            f"A la misma presión real, descarga − carga presenta ΔMCN = {h['mean_coordination_number']['matched_mean']:+.5f} y Δφ = {h['solid_fraction']['matched_mean']:+.6f} para las partículas con contactos. "
            'La densidad seleccionada suma únicamente sus volúmenes nominales sobre la misma caja. Las diferencias de overlaps se conservan: longitud y área disminuyen en descarga y el volumen de intersecciones aumenta.',
        'La presión y la rama ya predicen':
            f"La presión y la rama predicen gran parte de la variación de MCN. Añadir fracción sólida y volumen de overlap normalizado reduce un {100*(1-p['plus_density_overlap']['RMSE']/p['pressure_branch']['RMSE']):.1f} % el RMSE fuera de muestra bajo este protocolo. Esto es utilidad predictiva, no identificación causal.",
        'Cada registro proviene':
            'Cada registro proviene del mismo checkpoint físico. Las partículas con cero contactos de overlap positivo se excluyen de MCN y de la masa y volumen sólido seleccionados, sin modificar la caja. '
            'Los overlaps se reconstruyen de posiciones y radios periódicos, contando cada par una vez. D50 conserva la población original. Los archivos de simulación permanecen intactos.',
        'Pearson mide relación lineal;':
            f"Pearson mide relación lineal; Spearman, relación monotónica por rangos. MCN–volumen de overlap tiene Spearman {c['loading']['spearman'][0][4]:.3f}/{c['unloading']['spearman'][0][4]:.3f} y Pearson {c['loading']['raw']['pearson'][0][4]:.3f}/{c['unloading']['raw']['pearson'][0][4]:.3f} en carga/descarga. "
            f"Los intervalos usan {d['bootstrap']} remuestreos de simulaciones completas conservando sus objetivos; no se usan p-valores i.i.d. de checkpoints.",
        'A objetivo fijo, MCN–φ permanece':
            f"A objetivo fijo, MCN–φ tiene r = {c['loading']['target_adjusted']['pearson'][0][1]:+.3f}/{c['unloading']['target_adjusted']['pearson'][0][1]:+.3f} en carga/descarga. "
            f"Entre medias de run, r = {c['loading']['between_run_means_pearson'][0][1]:+.3f}/{c['unloading']['between_run_means_pearson'][0][1]:+.3f}. "
            f"Tras quitar efectos de run, objetivo y presión real queda r = {c['loading']['controlled']['pearson'][0][1]:+.3f}/{c['unloading']['controlled']['pearson'][0][1]:+.3f}. Las tablas muestran los IC correspondientes; estos niveles de análisis responden preguntas diferentes.",
        'MCN–volumen de overlap presenta':
            f"MCN–volumen de overlap tiene r bruto = {c['loading']['raw']['pearson'][0][4]:+.3f}/{c['unloading']['raw']['pearson'][0][4]:+.3f}; a objetivo fijo = {c['loading']['target_adjusted']['pearson'][0][4]:+.3f}/{c['unloading']['target_adjusted']['pearson'][0][4]:+.3f}; "
            f"entre medias de run = {c['loading']['between_run_means_pearson'][0][4]:+.3f}/{c['unloading']['between_run_means_pearson'][0][4]:+.3f}; con ajuste completo = {c['loading']['controlled']['pearson'][0][4]:+.3f}/{c['unloading']['controlled']['pearson'][0][4]:+.3f}, en carga/descarga. No debe inferirse una ley de contacto de la nube agregada.",
        'δmedio/D50 conserva':
            f"δmedio/D50 tiene correlación residual con MCN de {c['loading']['controlled']['pearson'][0][5]:+.3f}/{c['unloading']['controlled']['pearson'][0][5]:+.3f} en carga/descarga. El número de contactos se obtiene de Nactivo × MCN/2; por ello existe acoplamiento matemático y no constituye una prueba causal independiente. "
            f"Las correlaciones residuales de MCN con longitud son {c['loading']['controlled']['pearson'][0][2]:+.3f}/{c['unloading']['controlled']['pearson'][0][2]:+.3f}, y con área {c['loading']['controlled']['pearson'][0][3]:+.3f}/{c['unloading']['controlled']['pearson'][0][3]:+.3f}.",
        'Esta descomposición balanceada':
            'La descomposición balanceada es descriptiva y sus componentes suman 100 %. La tabla muestra cuánto corresponde a objetivos, offsets de run e interacción para la población con contactos. Las correlaciones ajustadas describen la variación residual, no demuestran que la presión sea la única causa.',
        'La descarga queda más densa':
            f"Descarga − carga da {100*h['solid_fraction']['matched_mean']:+.5f} puntos porcentuales de φ seleccionada, equivalentes a {2650*h['solid_fraction']['matched_mean']:+.3f} kg/m³. "
            f"ΔMCN = {h['mean_coordination_number']['matched_mean']:+.5f}. Los signos por run y sus intervalos están en la tabla. Estas cifras corresponden a las partículas con contactos; la historia y la población seleccionada importan.",
        'El signo se conserva usando':
            f"La sensibilidad PCHIP se muestra para todas las variables. El volumen de overlap tiene diferencia media {h['normalized_overlap_volume']['matched_mean']:.3e} con interpolación lineal y {h['normalized_overlap_volume']['matched_pchip_mean']:.3e} con PCHIP. El cambio de método no está cubierto por el IC entre runs; la tabla permite comparar signos y magnitudes.",
        'Los seis resúmenes apareados':
            'Los signos apareados se recalculan para la población con contactos. Se usa un contraste binomial bilateral y ajuste Benjamini–Hochberg para los seis resúmenes: '
            + '; '.join(f"{label}: p={h[field]['sign_p']:.3g}, q={h[field]['sign_q_BH']:.3g}" for field,label in zip(d['primary'],d['labels']))
            + '. Esto describe reproducibilidad entre semillas bajo este protocolo, no causalidad. Los IC por objetivo son puntuales, no bandas simultáneas.',
        'En carga, la media de MCN pasa':
            f"En carga, la media de MCN pasa de {d['profiles']['loading']['mean'][0][0]:.3f} a {d['profiles']['loading']['mean'][-1][0]:.3f} y φ de {d['profiles']['loading']['mean'][0][1]:.5f} a {d['profiles']['loading']['mean'][-1][1]:.5f} entre 5 y 200 kPa. "
            f"En descarga a 5 kPa: MCN = {d['profiles']['unloading']['mean'][0][0]:.3f}, φ = {d['profiles']['unloading']['mean'][0][1]:.5f}. Son medias al objetivo nominal de la población con contactos, no la comparación interpolada interior.",
        'El RMSE cae de':
            f"El RMSE cae de {p['pressure_branch']['RMSE']:.5f} a {p['plus_density_overlap']['RMSE']:.5f}: mejora del {100*(1-p['plus_density_overlap']['RMSE']/p['pressure_branch']['RMSE']):.1f} %. "
            'Son observaciones contemporáneas del mismo estado, no predicciones de estados futuros ni de otras presiones. Los IC remuestrean runs de predicciones ya obtenidas; no refitan el modelo en cada bootstrap.',
        'La multicolinealidad impide':
            'La multicolinealidad impide interpretar ingenuamente los coeficientes. Los VIF del diagnóstico de log P, φ y log overlap volumen son '
            + ', '.join(f"{d['linear_predictor_VIF'][key]:.2f}" for key in ['log_pressure','solid_fraction','log_normalized_overlap_volume'])
            + '. Una buena predicción conjunta no convierte cada coeficiente en un efecto físico independiente.',
    }
    for prefix, replacement in replacements.items():
        if value.startswith(prefix):
            return replacement
    return value


def fixed_target_text(value, d):
    if d.get('population') != 'without_rattlers':
        return value
    if value.startswith('Instantánea '):
        return value + ' La población seleccionada excluye las partículas con cero contactos de overlap positivo; se conservan la caja y D50 original.'
    if value.startswith('Density = '):
        return ('Density = 2650 × fracción sólida seleccionada. Ambas suman únicamente masa y volumen nominal de las partículas con contactos sobre la caja original. '
                'Sus correlaciones son idénticas. Los overlaps Σδ/L, ΣA/L² y ΣV/V conservan la misma normalización por caja. '
                'δmedio/D50 divide por contactos = Nactivo × MCN/2, conservando D50 original y el mismo conjunto de pares.')
    if value.startswith('A objetivo fijo, los packings'):
        return 'Las relaciones entre packings con contactos, resumidas a objetivo fijo, son: ' + '; '.join(
            f"{name}: MCN–φ {d['fixed_target_summary'][stage]['pearson'][0][1]:+.3f}, MCN–tr(K) {d['fixed_target_summary'][stage]['pearson'][0][5]:+.3f}, tr(K)–ΣA/L² {d['fixed_target_summary'][stage]['pearson'][5][3]:+.3f}, tr(K)–ΣV/V {d['fixed_target_summary'][stage]['pearson'][5][4]:+.3f}"
            for stage,name in [('loading','Carga'),('unloading','Descarga')]) + '. Son asociaciones bajo este protocolo, no una ley causal.'
    if value.startswith('La relación no es constante'):
        return 'La relación cambia entre objetivos. Para MCN–tr(K), Pearson a 5 kPa y a 200 kPa es ' + '; '.join(
            f"{name}: {d['groups'][stage][0]['pearson'][0][5]:+.3f} y {d['groups'][stage][-1]['pearson'][0][5]:+.3f}"
            for stage,name in [('loading','Carga'),('unloading','Descarga')]) + '. El resumen no sustituye la inspección del checkpoint de interés.'
    if value.startswith('Las principales direcciones se conservan'):
        return 'La sensibilidad a presión real para la población seleccionada da: ' + '; '.join(
            f"{name}: MCN–tr(K) {d['fixed_target_summary'][stage]['pressure_residual_pearson'][0][5]:+.3f}, MCN–φ {d['fixed_target_summary'][stage]['pressure_residual_pearson'][0][1]:+.3f}, tr(K)–ΣV/V {d['fixed_target_summary'][stage]['pressure_residual_pearson'][5][4]:+.3f}"
            for stage,name in [('loading','Carga'),('unloading','Descarga')]) + '. La tabla y el explorador muestran los intervalos y la dispersión de cada grupo.'
    return value
