"""Standalone Kratos worker; requires only Kratos and the Python standard library.

Run a prepared case with its configured Python: python dem/input/run.py.
"""

import json
import os
import platform
from pathlib import Path


def main():
    import KratosMultiphysics as KM
    from KratosMultiphysics.DEMApplication.DEM_analysis_stage import DEMAnalysisStage

    inputs = Path(__file__).resolve().parent
    output = inputs.parent / "native_results"
    os.chdir(output)
    execution = json.loads((inputs / "execution.json").read_text(encoding="utf-8"))

    class JPGenAnalysis(DEMAnalysisStage):
        def __init__(self, model, parameters):
            self.completed_steps = 0
            self.final_state = None
            super().__init__(model, parameters)
            self.mdpas_folder_path = str(inputs)

        def model_part_reader(self, modelpart, nodeid=0, elemid=0, condid=0):
            # Keep the original JPGen IDs, including nonconsecutive imported IDs.
            return KM.ModelPartIO(modelpart, KM.IO.READ | KM.IO.SKIP_TIMER)

        def KeepAdvancingSolutionLoop(self):
            return self.completed_steps < execution["steps"]

        def _AdvanceTime(self):
            # Avoid cumulative rounding causing a spurious extra/missing step.
            previous_time = self.completed_steps * self.DEM_parameters["MaxTimeStep"].GetDouble()
            return self._GetSolver().AdvanceInTime(previous_time)

        def Initialize(self):
            try:
                super().Initialize()
            finally:
                (output / "resolved_parameters.json").write_text(
                    self.DEM_parameters.PrettyPrintJsonString(), encoding="utf-8")

        def FinalizeSolutionStep(self):
            super().FinalizeSolutionStep()
            self.completed_steps += 1

        def Finalize(self):
            nodes = sorted(self.spheres_model_part.Nodes, key=lambda node: node.Id)
            self.final_state = {
                "ids": [node.Id for node in nodes],
                "positions": [[node.X, node.Y, node.Z] for node in nodes],
                "radii": [node.GetSolutionStepValue(KM.RADIUS) for node in nodes],
                "velocities": [list(node.GetSolutionStepValue(KM.VELOCITY)) for node in nodes],
                "angular_velocities": [list(node.GetSolutionStepValue(KM.ANGULAR_VELOCITY)) for node in nodes],
                "time": self.time,
            }
            # Kratos deletes model parts during Finalize.
            super().Finalize()

    parameters = KM.Parameters((inputs / "ProjectParametersDEM.json").read_text(encoding="utf-8"))
    analysis = JPGenAnalysis(KM.Model(), parameters)
    analysis.Run()
    (output / "final_state.json").write_text(json.dumps(analysis.final_state, allow_nan=False), encoding="utf-8")
    (output / "execution_report.json").write_text(json.dumps({
        "steps": analysis.completed_steps,
        "versions": {"kratos": KM.Kernel.Version(), "python": platform.python_version()},
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
