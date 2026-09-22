"""Run a prepared DEM case with phase timers and record loaded native libraries."""
import json
import os
from pathlib import Path
import runpy
import sys

case = Path(sys.argv[1]).resolve().parent.parent
try:
    runpy.run_path(str(Path(__file__).with_name('kratos_phase_profile.py')), run_name='__main__')
finally:
    libraries = sorted({line.split()[-1] for line in Path('/proc/self/maps').read_text().splitlines()
                        if 'Kratos' in line and '.so' in line})
    (case/'runtime.json').write_text(json.dumps({
        'libraries': libraries,
        'switches': {key: os.environ.get(key) for key in (
            'KRATOS_DEM_REUSE_SEARCH_STORAGE', 'KRATOS_DEM_INDEXED_NEIGHBOURS', 'OMP_NUM_THREADS')},
    }, indent=2)+'\n')
