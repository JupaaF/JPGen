"""Standalone Kratos worker; requires Kratos and NumPy.

Run a prepared case with its configured Python: python dem/input/run.py.
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
    output = inputs.parent / "native_results"
    os.chdir(output)
    execution = json.loads((inputs / "execution.json").read_text(encoding="utf-8"))

    from protocol import CONTACT_OBSERVABLES, ProtocolRunner, STRESS_OBSERVABLES, required_observables
    from protocol_adapter import KratosProtocolAdapter
    from state_exchange import write_state

    class JPGenAnalysis(DEMAnalysisStage):
        def __init__(self, model, parameters):
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
            previous_time = self.completed_steps * self.DEM_parameters["MaxTimeStep"].GetDouble()
            return self._GetSolver().AdvanceInTime(previous_time)

        def Initialize(self):
            try:
                super().Initialize()
                if execution.get("protocol"):
                    (output / "observables.jsonl").write_text("", encoding="utf-8")
                    (output / "snapshots.jsonl").write_text("", encoding="utf-8")
                    (output / "accepted_states.jsonl").write_text("", encoding="utf-8")
                    specification = execution['protocol']
                    self.protocol = ProtocolRunner(specification, self.DEM_parameters["MaxTimeStep"].GetDouble())
                    self.output_observables = {'kinetic_energy'}
                    if execution['boundary'] == 'periodic':
                        self.output_observables |= {'solid_fraction', 'bulk_density'}
                    requested = required_observables(specification['stages'])
                    self.needs_stress = bool(requested & STRESS_OBSERVABLES)
                    self.needs_contacts = bool(requested & CONTACT_OBSERVABLES)
                    if self.needs_stress:
                        self.output_observables |= STRESS_OBSERVABLES
                    if 'unbalanced_force' in requested:
                        self.output_observables.add('unbalanced_force')
                    self.adapter = KratosProtocolAdapter(self, execution)
                    self.observables = self.adapter.observe(self.protocol.observables)
                    self._save_boundaries(output)
            finally:
                (output / "resolved_parameters.json").write_text(
                    self.DEM_parameters.PrettyPrintJsonString(), encoding="utf-8")

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
                    with (output / "observables.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps({"step": self.completed_steps, "stage": stage_path, "observables": self.observables,
                                                 "box": self.adapter.box(),
                                                 "time_step": {"dt": self.protocol.dt}}, allow_nan=False) + "\n")
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

        def _save_native_restart(self, output, stem, box):
            directory = output / "restarts" / stem
            directory.mkdir(parents=True, exist_ok=True)
            model_part = self.spheres_model_part
            temporary_stem = directory / "SpheresPart.tmp"
            serializer = KM.FileSerializer(str(temporary_stem), KM.SerializerTraceType.SERIALIZER_NO_TRACE)
            serializer.Set(KM.Serializer.SHALLOW_GLOBAL_POINTERS_SERIALIZATION)
            serializer.Save(model_part.Name, model_part)
            del serializer
            (directory / "SpheresPart.tmp.rest").replace(directory / "SpheresPart.rest")
            metadata = {
                "schema": "JPGen.dem.kratos_restart", "schema_version": "1.0",
                "model_parts": ["SpheresPart"], "step": self.completed_steps,
                "time": self.protocol.time, "box": box,
                "kratos_version": KM.Kernel.Version(),
            }
            temporary = directory / "restart.json.tmp"
            temporary.write_text(json.dumps(metadata, allow_nan=False) + "\n", encoding="utf-8")
            temporary.replace(directory / "restart.json")
            return f"restarts/{stem}/SpheresPart.rest"

        def _save_boundaries(self, output):
            boundaries = self.protocol.take_boundaries()
            if not boundaries:
                return
            snapshots = output / "snapshots"
            snapshots.mkdir(exist_ok=True)
            stem = f"step_{self.completed_steps:012d}"
            box = self.adapter.box()
            write_state(snapshots, self._particle_arrays(), time=self.protocol.time,
                        box=box, stem=stem)
            restart = self._save_native_restart(output, stem, box)
            with (output / "snapshots.jsonl").open("a", encoding="utf-8") as stream, \
                    (output / "accepted_states.jsonl").open("a", encoding="utf-8") as accepted_stream:
                for boundary in boundaries:
                    record = {**boundary, "state": f"snapshots/{stem}", "restart": restart}
                    stream.write(json.dumps(record, allow_nan=False) + "\n")
                    if boundary.get("accepted") is True and "target" in boundary:
                        accepted_stream.write(json.dumps(record, allow_nan=False) + "\n")

        def Finalize(self):
            self.final_state = {
                "time": self.time,
                "box": self.adapter.box() if self.adapter else {
                    "origin": [getattr(self, f"BoundingBoxMin{axis}_update") for axis in "XYZ"],
                    "lengths": [getattr(self, f"BoundingBoxMax{axis}_update") - getattr(self, f"BoundingBoxMin{axis}_update") for axis in "XYZ"],
                    "periodic": execution["boundary"] == "periodic"},
            }
            # Stream numeric arrays before Kratos deletes its model parts.
            write_state(output, self._particle_arrays(), **self.final_state)
            super().Finalize()

    parameters = KM.Parameters((inputs / "ProjectParametersDEM.json").read_text(encoding="utf-8"))
    analysis = JPGenAnalysis(KM.Model(), parameters)
    analysis.Run()
    (output / "execution_report.json").write_text(json.dumps({
        "steps": analysis.completed_steps,
        "stop_reason": ("max_duration" if analysis.protocol.failed else "protocol_complete") if execution.get("protocol") else "end_time",
        "time": analysis.final_state["time"],
        "time_step": {"mode": "fixed", "value": execution["end_time"] / execution["steps"]},
        "completed_stages": analysis.protocol.completed_stages if analysis.protocol else 0,
        "accepted_targets": analysis.protocol.accepted_targets if analysis.protocol else 0,
        "failed_stage": analysis.protocol.failed_stage if analysis.protocol else None,
        "observables": analysis.observables,
        "control": {"implementation": "jpgen_portable",
                    "actuators": ["cell_strain_rate", "symmetric_wall_velocity"]},
        "versions": {"kratos": KM.Kernel.Version(), "python": platform.python_version()},
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
