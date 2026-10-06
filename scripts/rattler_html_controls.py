"""Keep population controls in regenerated standalone dashboard templates."""


def dashboard_controls(source):
    if 'id="excludeRattlers"' in source:
        return source
    source = source.replace('<label>Observable <select id="metric"></select></label>',
                            '<label>Observable <select id="metric"></select></label>\n'
                            '<label><input type="checkbox" id="excludeRattlers"> Excluir rattlers</label>\n'
                            '<p>Rattlers = partículas con cero contactos de overlap positivo. '
                            'Al excluirlos se usa la misma caja y se recalculan MCN, densidad y energía. '
                            'Las variables de contactos conservan su valor.</p>')
    source = source.replace("const completed=snapshot.jobs.filter(job=>job.status==='completed');",
                            "const completed=snapshot.jobs.filter(job=>job.status==='completed').map(job=>"
                            "({...job,values:$('excludeRattlers').checked?(job.without_rattlers??{}):job.values}));")
    source = source.replace("$('rows').replaceChildren();",
                            "if($('excludeRattlers').checked){const missing=completed.filter(job=>!Number.isFinite(job.values[metric])).length;"
                            "$('message').textContent+=` · Sin rattlers${missing?' · '+missing+' ejecuciones sin datos para este observable':''}`;}\n"
                            " $('rows').replaceChildren();")
    return source.replace("$('protocol').onchange=render;", "$('protocol').onchange=render;$('excludeRattlers').onchange=render;")


def viewer_controls(source):
    if 'id="excludeRattlers"' not in source:
        source = source.replace('<div class="toolbar">\n<label><input',
                                '<div class="toolbar">\n<label><input type="checkbox" id="excludeRattlers"> Excluir rattlers</label>\n<label><input', 1)
        source = source.replace('const available=data.points.filter(',
                                "const population=data.points.map(p=>$('excludeRattlers').checked?{...p,...p.without_rattlers}:p);\n const available=population.filter(")
        source = source.replace("'lines','singleCheckpoint']", "'lines','singleCheckpoint','excludeRattlers']")
        source = source.replace('${points.length} puntos visibles', "${$('excludeRattlers').checked?'Sin rattlers · ':''}${points.length} puntos visibles")
        source = source.replace('MCN es el valor registrado por LIGGGHTS.',
                                'MCN incluye todas las partículas por defecto. “Excluir rattlers” elimina las partículas '
                                'con cero contactos de overlap positivo del denominador de MCN y de la masa y volumen sólido '
                                'seleccionados; la caja se mantiene. Los overlaps y la presión conservan su valor.')
    source = source.replace("if(selected&&!points.includes(selected)){selected=null;$('hint').textContent='Pulsa un punto para ver sus valores.';$('details').replaceChildren()}",
                            "if(selected&&!points.includes(selected)){const previous=selected;selected=points.find(p=>p.run_id===previous.run_id&&p.state_id===previous.state_id)||null;if(selected)inspect(selected);else{$('hint').textContent='Pulsa un punto para ver sus valores.';$('details').replaceChildren()}}")
    source = source.replace("ctx.fillText('MCN · density · overlap',width/2,22);", "ctx.fillText('MCN · density · overlap'+($('excludeRattlers').checked?' · sin rattlers':''),width/2,22);")
    source = source.replace("download('mcn_density_overlap_checkpoints.csv',", "download('mcn_density_overlap_checkpoints'+($('excludeRattlers').checked?'_sin_rattlers':'')+'.csv',")
    return source.replace("`mcn_density_overlap_${$('view').value}.png`", "`mcn_density_overlap_${$('view').value}${$('excludeRattlers').checked?'_sin_rattlers':''}.png`")
