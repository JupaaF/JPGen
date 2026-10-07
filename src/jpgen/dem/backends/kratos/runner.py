"""Standalone Kratos worker; requires Kratos and NumPy.

Run a prepared case with its configured Python: python stages/dem/backend/kratos/input/run.py.
"""

import json
import os
import platform
from pathlib import Path

import numpy as np


def main():
    import KratosMultiphysics as KM
    from KratosMultiphysics.DEMApplication.DEM_analysis_stage import DEMAnalysisStage

    inputs = Path(__file__).resolve().parent
    import argparse
    import shutil
    parser = argparse.ArgumentParser(description="Execute a prepared Kratos case")
    parser.add_argument("--output-dir", help="Fresh stage directory for a standalone rerun")
    args = parser.parse_args()
    if args.output_dir:
        stage = Path(args.output_dir).resolve()
        if stage.exists():
            raise FileExistsError("Standalone output directory must not already exist.")
        copied = stage / "backend/kratos/input"
        shutil.copytree(inputs, copied)
        inputs = copied
    stage = inputs.parents[2]
    output = stage / "backend/kratos/native"
    output.mkdir(parents=True, exist_ok=True)
    # Never silently overwrite an existing run's scientific results.
    with (output / ".worker-started").open("x", encoding="utf-8") as marker:
        marker.write("Use --output-dir for a fresh standalone execution.\n")
    os.chdir(output)
    execution = json.loads((inputs / "execution.json").read_text(encoding="utf-8"))

    from protocol import ProtocolRunner, STRESS_OBSERVABLES, required_observables
    from protocol_adapter import KratosProtocolAdapter
    from atomic_io import atomic_json, atomic_text
    from state_exchange import write_state
    from output_writer import StageOutput
    store = StageOutput(stage)

    class JPGenAnalysis(DEMAnalysisStage):
        def __init__(self, model, parameters):
            self.output_store = store
            self.completed_steps = 0
            self.final_state = None
            self.protocol = None
            self.adapter = None
            self.observables = {}
            super().__init__(model, parameters)
            self.mdpas_folder_path = str(inputs)

        def model_part_reader(self, modelpart, nodeid=0, elemid=0, condid=0):
            # Keep the original JPGen IDs, including nonconsecutive imported IDs.
            return KM.ModelPartIO(modelpart, KM.IO.READ | KM.IO.SKIP_TIMER)

        def KeepAdvancingSolutionLoop(self):
            if self.protocol is not None:
                return not self.protocol.done
            return self.completed_steps < execution["steps"]

        def _AdvanceTime(self):
            # Avoid cumulative rounding causing a spurious extra/missing step.
            previous_time = (self.protocol.time if self.protocol is not None else
                             self.completed_steps * self.DEM_parameters["MaxTimeStep"].GetDouble())
            return self._GetSolver().AdvanceInTime(previous_time)

        def Initialize(self):
            try:
                super().Initialize()
                if execution.get("protocol"):
                    specification = execution['protocol']
                    self.protocol = ProtocolRunner(specification, self.DEM_parameters["MaxTimeStep"].GetDouble())
                    self.output_observables = {'kinetic_energy', 'mean_coordination_number', 'fabric_tensor'}
                    if execution['boundary'] == 'periodic':
                        self.output_observables |= {'solid_fraction', 'bulk_density', 'thermal_conductivity'}
                    requested = required_observables(specification['stages'])
                    self.needs_stress = bool(requested & STRESS_OBSERVABLES)
                    self.needs_contacts = True
                    if self.needs_stress:
                        self.output_observables |= STRESS_OBSERVABLES | {'normalized_kinetic_energy'}
                    if 'unbalanced_force' in requested:
                        self.output_observables.add('unbalanced_force')
                    self.adapter = KratosProtocolAdapter(self, execution)
                    self.protocol.attach(self.adapter)
                    self.observables = self.adapter.observe(self.protocol.observables)
                    self._save_boundaries(output)
            finally:
                atomic_text(output / "resolved_parameters.json", self.DEM_parameters.PrettyPrintJsonString())

        def InitializeSolutionStep(self):
            super().InitializeSolutionStep()
            if self.protocol is not None:
                if self.needs_contacts:
                    self.UpdateIsTimeToUpdateContactElementForServo(True)
                dt = self.protocol.dt
                command = self.protocol.act(
                    self.observables, self.adapter.control_context(dt))
                self.adapter.apply(command, dt)

        def FinalizeSolutionStep(self):
            super().FinalizeSolutionStep()
            self.completed_steps += 1
            if self.protocol is not None:
                stage_path = self.protocol.path
                density = self.protocol.density
                sample_context = ({'density_phase': density.phase, 'cycles': density.cycles}
                                  if density is not None else {})
                self.observables = self.protocol.advance(self.adapter.observe(self.protocol.observables))
                stage_exited = self.protocol.stage_exited
                sampled = self.completed_steps % execution['protocol']['sample_every'] == 0
                if sampled or stage_exited:
                    missing = self.output_observables - self.observables.keys()
                    self.observables.update(self.adapter.observe(missing))
                # Boundary metadata sees the same completed-step measurements as
                # the observables log, including density and the stress tensor.
                self._save_boundaries(output)
                if sampled or stage_exited:
                    store.sample({"step": self.completed_steps,
                                  "stage": stage_path, "observables": self.observables,
                                  "box": self.adapter.box(), "time_step": {"dt": self.protocol.dt},
                                  **sample_context})
                if stage_exited and not self.protocol.done:
                    # Seed the next controller with measurements from the current
                    # state, never with stale values from an earlier stage.
                    missing = self.protocol.observables - self.observables.keys()
                    self.observables.update(self.adapter.observe(missing))

        def _particle_arrays(self):
            nodes = sorted(self.spheres_model_part.Nodes, key=lambda node: node.Id)
            count = len(nodes)
            yield "ids", np.fromiter((node.Id for node in nodes), dtype=np.int64, count=count)
            yield "positions", np.fromiter(
                (value for node in nodes for value in (node.X, node.Y, node.Z)),
                dtype=np.float64, count=3 * count).reshape(count, 3)
            yield "radii", np.fromiter((node.GetSolutionStepValue(KM.RADIUS) for node in nodes),
                                       dtype=np.float64, count=count)
            for name, variable in (("velocities", KM.VELOCITY),
                                   ("angular_velocities", KM.ANGULAR_VELOCITY)):
                yield name, np.fromiter(
                    (value for node in nodes for value in node.GetSolutionStepValue(variable)),
                    dtype=np.float64, count=3 * count).reshape(count, 3)

        def _save_boundaries(self, output):
            boundaries = self.protocol.take_boundaries()
            if not boundaries:
                return
            box = self.adapter.box()
            saved = store.state(self._particle_arrays(), time=self.protocol.time, box=box, key=self.completed_steps)
            for boundary in boundaries:
                store.boundary({**saved, **boundary, "step": self.completed_steps})

        def Finalize(self):
            if self.protocol is None:
                self.adapter = KratosProtocolAdapter(self, execution)
                final_observables = {'mean_coordination_number', 'fabric_tensor'}
                if execution['boundary'] == 'periodic':
                    final_observables.add('thermal_conductivity')
                self.observables = self.adapter.observe(final_observables)
                store.sample({"step": self.completed_steps,
                              "stage": None, "observables": self.observables,
                              "box": self.adapter.box(), "time_step": {"dt": execution['end_time'] / execution['steps']}})
            self.final_state = {
                "time": self.time,
                "box": self.adapter.box() if self.adapter else {
                    "origin": [getattr(self, f"BoundingBoxMin{axis}_update") for axis in "XYZ"],
                    "lengths": [getattr(self, f"BoundingBoxMax{axis}_update") - getattr(self, f"BoundingBoxMin{axis}_update") for axis in "XYZ"],
                    "periodic": execution["boundary"] == "periodic"},
            }
            # Stream numeric arrays before Kratos deletes its model parts.
            write_state(output, self._particle_arrays(), **self.final_state)
            saved = store.state(source=output / "final_state", key=self.completed_steps, **self.final_state)
            store.boundary({**saved, "kind": "diagnostic" if self.protocol and self.protocol.failed else "final",
                            "phase": "end", "step": self.completed_steps,
                            "stage": self.protocol.path if self.protocol else None,
                            "accepted": False if self.protocol and self.protocol.failed else None})
            super().Finalize()

    parameters = KM.Parameters((inputs / "ProjectParametersDEM.json").read_text(encoding="utf-8"))
    analysis = JPGenAnalysis(KM.Model(), parameters)
    analysis.Run()
    atomic_json(output / "execution_report.json", {
        "steps": analysis.completed_steps,
        "stop_reason": (analysis.protocol.stop_reason if analysis.protocol.failed else "protocol_complete") if execution.get("protocol") else "end_time",
        "time": analysis.final_state["time"],
        "time_step": {"mode": "fixed", "value": execution["end_time"] / execution["steps"]},
        "completed_stages": analysis.protocol.completed_stages if analysis.protocol else 0,
        "accepted_targets": analysis.protocol.accepted_targets if analysis.protocol else 0,
        "diagnostics": analysis.protocol.diagnostics if analysis.protocol else {},
        "failed_stage": analysis.protocol.failed_stage if analysis.protocol else None,
        "observables": analysis.observables,
        "control": {"implementation": "jpgen_portable",
                    "actuators": ["cell_strain_rate", "symmetric_wall_velocity"],
                    "unbalanced_force_definition": "RMS particle force imbalance / RMS contact force; excludes moments; zero without contacts"},
        "versions": {
            "kratos": KM.Kernel.Version(),
            "kratos_source_revision": os.environ.get("JPGEN_KRATOS_REVISION"),
            "python": platform.python_version(),
        },
    })


if __name__ == "__main__":
    main()
