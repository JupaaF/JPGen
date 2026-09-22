"""Time Python lifecycle boundaries, including enclosed native Kratos calls.

Usage (with Kratos environment active): python tools/kratos_phase_profile.py CASE/input/run.py
Nested measurements overlap and must not be added together.
"""
import functools
import json
from pathlib import Path
import runpy
import sys
import time

import KratosMultiphysics as KM
from KratosMultiphysics.DEMApplication.DEM_analysis_stage import DEMAnalysisStage
from KratosMultiphysics.DEMApplication.sphere_strategy import ExplicitStrategy

measurements = {}


def instrument(cls, name):
    original = getattr(cls, name)
    key = cls.__name__ + '.' + name
    measurements[key] = {'calls': 0, 'seconds': 0.0}

    @functools.wraps(original)
    def measured(*args, **kwargs):
        start = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            measurements[key]['calls'] += 1
            measurements[key]['seconds'] += time.perf_counter()-start
    setattr(cls, name, measured)


for method in ('Initialize', 'InitializeSolutionStep', 'SolveSolutionStep', 'FinalizeSolutionStep', 'Finalize'):
    instrument(ExplicitStrategy, method)
for method in ('Initialize', 'InitializeSolutionStep', 'FinalizeSolutionStep', 'OutputSolutionStep', 'Finalize', 'RunSolutionLoop'):
    instrument(DEMAnalysisStage, method)

worker = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(worker.parent))
start = time.perf_counter()
try:
    runpy.run_path(str(worker), run_name='__main__')
finally:
    result = {'elapsed_after_imports': time.perf_counter()-start,
              'kratos_module': KM.__file__, 'phases': measurements}
    (worker.parent.parent / 'phases.json').write_text(json.dumps(result, indent=2)+'\n')
