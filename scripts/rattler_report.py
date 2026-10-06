"""Update original report elements in place when changing particle population."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NOTE = ('Rattler = partícula con cero contactos de overlap positivo. Se conserva la caja y D50 original. '
        'El checkbox actualiza las tablas, figuras y resultados en las mismas secciones del informe.')
CONTROL = '<label style="display:flex;align-items:center;gap:8px;margin:18px 0"><input type="checkbox" id="excludeRattlers"> Excluir rattlers</label>'
ELEMENT = re.compile(r'<(?P<tag>p|th|td|img|figcaption)\b(?P<attrs>[^>]*)(?:>(?P<body>.*?)</(?P=tag)>|(?P<image>>))', re.S)


def run_script(name, folder, *, plot=False, raw=False):
    env = dict(os.environ, MPLCONFIGDIR='/tmp/jpgen-matplotlib')
    if raw:
        env['JPGEN_RATTLER_REPORT_RAW'] = '1'
    if plot:
        # The system Matplotlib is built for the system NumPy. Keep that pair
        # together rather than loading a different NumPy from /usr/local.
        cmd = ['/usr/bin/python3', '-S', '-c',
               "import sys,runpy;sys.path.insert(0,'/usr/lib/python3/dist-packages');"
               "sys.path.insert(0,'scripts');sys.argv=sys.argv[1:];"
               "runpy.run_path(sys.argv[0],run_name='__main__')", str(ROOT/'scripts'/name), str(folder)]
    else:
        cmd = [sys.executable, str(ROOT/'scripts'/name), str(folder)]
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def filtered_report(folder, stats):
    fixed = 'points_data' in stats
    study = folder.parent if fixed else folder
    original = json.loads((study/'statistics.json').read_text())
    selected_study = study/'without_rattlers'
    viewer = Path(original['source'])
    digest = hashlib.sha256(viewer.read_bytes()).hexdigest()
    selected_stats = selected_study/'statistics.json'
    selected = json.loads(selected_stats.read_text()) if selected_stats.exists() else {}
    recompute = selected.get('source_sha256') != digest or selected.get('bootstrap') != original['bootstrap']
    if recompute:
        subprocess.run([sys.executable, str(ROOT/'scripts/analyze_mcn_correlations.py'),
                        '--viewer', str(viewer), '--without-rattlers', '--output', str(selected_study),
                        '--bootstrap', str(original['bootstrap'])], cwd=ROOT, check=True)
    target = selected_study/'fixed_target' if fixed else selected_study
    fixed_stats = json.loads((target/'statistics.json').read_text()) if fixed and (target/'statistics.json').exists() else {}
    csv_digest = hashlib.sha256((selected_study/'checkpoint_data.csv').read_bytes()).hexdigest()
    if fixed and (recompute or fixed_stats.get('bootstrap') != stats['bootstrap'] or fixed_stats.get('source_checkpoint_csv_sha256') != csv_digest):
        subprocess.run([sys.executable, str(ROOT/'scripts/analyze_fixed_target_thermal.py'),
                        '--study', str(selected_study), '--bootstrap', str(stats['bootstrap'])], cwd=ROOT, check=True)
    figure = '05_fixed_target_summary' if fixed else '08_overlap_pressure_scaling'
    if recompute or not (target/'figures'/f'{figure}.png').exists():
        run_script('plot_fixed_target_thermal.py' if fixed else 'plot_mcn_correlations.py', target, plot=True)
    run_script('write_fixed_target_thermal_report.py' if fixed else 'write_mcn_correlation_report.py', target, raw=True)
    fragment = target/'report.fragment'
    (target/'report.html').replace(fragment)
    return fragment


def body(source):
    return source.split('<main>', 1)[1].split('</main>', 1)[0]


def elements(main):
    # Elements with IDs are the existing interactive explorer's outputs.
    # They are refreshed by its own update() without replacing its controls.
    return [m for m in ELEMENT.finditer(main) if not re.search(r'\bid\s*=', m['attrs'])]


def rebase_links(fragment, original, selected):
    def link(match):
        href = match[1]
        if (selected/href).is_file():
            href = os.path.relpath(selected/href, original)
        return 'href="' + href + '"'
    return re.sub(r'href="([^"]+)"', link, fragment)


def add_population_switch(path, folder, contact_only=False):
    if os.environ.get('JPGEN_RATTLER_REPORT_RAW') == '1':
        return
    path, folder = Path(path), Path(folder)
    source = path.read_text()
    if 'id="excludeRattlers"' in source:
        # Already decorated reports remain intact. Report writers create fresh
        # originals before this function, so regeneration replaces the data.
        return
    if contact_only:
        source = source.replace('<main>', '<main>' + CONTROL + '<p id="populationNote" role="status">'
                                + 'Los histogramas y métricas por contacto son iguales para ambas poblaciones; D50 conserva la población original.</p>', 1)
        source = source.replace('</html>', '''<script>document.getElementById('excludeRattlers').onchange=function(){document.getElementById('populationNote').textContent=this.checked?'Sin rattlers: los histogramas y métricas no cambian porque las partículas excluidas no tienen contactos. D50 conserva la población original.':'Incluye todas las partículas. Solo los pares con overlap positivo contribuyen a estos histogramas y métricas.';};</script></html>''')
        path.write_text(source)
        return
    stats = json.loads((folder/'statistics.json').read_text())
    selected_path = filtered_report(folder, stats)
    original_main = body(source)
    selected_main = body(selected_path.read_text())
    originals, selections = elements(original_main), elements(selected_main)
    if len(originals) != len(selections) or any(a['tag'] != b['tag'] for a,b in zip(originals,selections)):
        raise ValueError('Population variants must preserve the original report structure')
    patches = []
    replacements = []
    for a,b in zip(originals,selections):
        if a['tag'] == 'img':
            all_src = re.search(r'src="([^"]*)"', a['attrs'])[1]
            selected_src = re.search(r'src="([^"]*)"', b['attrs'])[1]
            all_value, selected_value, attribute = all_src, selected_src, 'src'
        else:
            all_value = a['body']
            selected_value = rebase_links(b['body'], folder, selected_path.parent)
            attribute = None
        if all_value == selected_value:
            continue
        index = len(patches)
        patches.append(dict(all=all_value, selected=selected_value, attribute=attribute))
        annotated = a[0].replace('<' + a['tag'], '<' + a['tag'] + f' data-population-index="{index}"', 1)
        replacements.append((a.start(), a.end(), annotated))
    for start,end,fragment in reversed(replacements):
        original_main = original_main[:start] + fragment + original_main[end:]
    source = source.replace(body(source), CONTROL + '<p id="populationNote" role="status">' + NOTE + '</p>' + original_main, 1)
    fixed = 'points_data' in stats
    selected_data = json.loads((selected_path.parent/'statistics.json').read_text()) if fixed else None
    payload = json.dumps(dict(patches=patches, selected_data=selected_data), ensure_ascii=False, allow_nan=False).replace('<','\\u003c')
    script = '<script id="population-data" type="application/json">' + payload + '</script><script>' + JS + '</script>'
    source = source.replace('</html>', script + '</html>')
    path.write_text(source)


JS = r'''
(()=>{
const population=JSON.parse(document.getElementById('population-data').textContent);
const originalData=population.selected_data?D:null;
const checkbox=document.getElementById('excludeRattlers');
checkbox.addEventListener('change',()=>{
 const selected=checkbox.checked;
 for(const element of document.querySelectorAll('[data-population-index]')){
  const patch=population.patches[+element.dataset.populationIndex],value=selected?patch.selected:patch.all;
  if(patch.attribute)element.setAttribute(patch.attribute,value);else element.innerHTML=value;
 }
 if(population.selected_data){D=selected?population.selected_data:originalData;update();}
 document.getElementById('populationNote').textContent=(selected?'Sin rattlers. ':'Incluye todas las partículas. ')+
 'Rattler = partícula con cero contactos de overlap positivo. Se conserva la caja y D50 original. Las secciones y controles son los mismos para ambas poblaciones.';
});
})();
'''
