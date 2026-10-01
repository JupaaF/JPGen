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
    from state_exchange import write_state
    from output_writer import StageOutput
    store = StageOutput(stage, execution.get("retention", "full"), engine="kratos")

    class JPGenAnalysis(DEMAnalysisStage):
        def __init__(self, model, parameters, resume_runner=None, restart_checkpoint=None):
            self.output_store = store
            self.completed_steps = resume_runner.attempted_steps if resume_runner else 0
            self.final_state = None
            self.protocol = resume_runner
            self.restart_checkpoint = restart_checkpoint
            self.rollback_checkpoint = None
            self.adapter = None
            self.observables = {}
            super().__init__(model, parameters)
            self.mdpas_folder_path = str(inputs)

        def model_part_reader(self, modelpart, nodeid=0, elemid=0, condid=0):
            # Keep the original JPGen IDs, including nonconsecutive imported IDs.
            return KM.ModelPartIO(modelpart, KM.IO.READ | KM.IO.SKIP_TIMER)

        def KeepAdvancingSolutionLoop(self):
            if self.protocol is not None:
                return not self.protocol.done and self.rollback_checkpoint is None
            return self.completed_steps < execution["steps"]

        def _AdvanceTime(self):
            # Avoid cumulative rounding causing a spurious extra/missing step.
            previous_time = (self.protocol.time if self.protocol is not None else
                             self.completed_steps * self.DEM_parameters["MaxTimeStep"].GetDouble())
            return self._GetSolver().AdvanceInTime(previous_time)

        def ReadModelPartsFromRestartFile(self, settings):
            if self.restart_checkpoint is None:
                return super().ReadModelPartsFromRestartFile(settings)
            metadata = self.restart_checkpoint['metadata']
            if (metadata['schema'] != 'JPGen.dem.kratos_checkpoint' or
                    metadata['schema_version'] != '1.0' or
                    metadata['kratos_version'] != KM.Kernel.Version()):
                raise ValueError('Incompatible Kratos density checkpoint.')
            directory = Path(self.restart_checkpoint['directory'])
            for name in metadata['model_parts']:
                # ContactPart is a derived measurement mesh. Kratos rebuilds it
                # on the first completed step; loading it here duplicates one
                # generation of contact elements in the first stress sample.
                if name == 'ContactPart':
                    continue
                part = self.model.GetModelPart(name)
                serializer = KM.FileSerializer(str(directory / name),
                                               KM.SerializerTraceType.SERIALIZER_NO_TRACE)
                serializer.Set(KM.Serializer.SHALLOW_GLOBAL_POINTERS_SERIALIZATION)
                serializer.Load(name, part)
                del serializer
                part.ProcessInfo[KM.IS_RESTARTED] = True

        def Initialize(self):
            try:
                super().Initialize()
                if execution.get("protocol"):
                    specification = execution['protocol']
                    if self.protocol is None:
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
                    if self.restart_checkpoint is None:
                        self.protocol.attach(self.adapter)
                    else:
                        self.protocol.rebind(self.adapter)
                    if self.restart_checkpoint is None:
                        self.observables = self.adapter.observe(self.protocol.observables)
                        self._save_boundaries(output)
                    else:
                        # Contact stress is refreshed by the next solver step.
                        # Use the exact checkpoint measurement for the first actuation.
                        self.observables = dict(self.restart_checkpoint['metadata']['observables'])
                        if self.protocol.done:
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
                sample_context = store.context() if store.attempt_stage == stage_path else {"attempt_id": None, "branch_id": store.branch_id}
                self.observables = self.protocol.advance(self.adapter.observe(self.protocol.observables))
                if self.protocol.restored:
                    return
                stage_exited = self.protocol.stage_exited
                sampled = self.completed_steps % execution['protocol']['sample_every'] == 0
                if sampled or stage_exited:
                    missing = self.output_observables - self.observables.keys()
                    self.observables.update(self.adapter.observe(missing))
                # Boundary metadata sees the same completed-step measurements as
                # the observables log, including density and the stress tensor.
                self._save_boundaries(output)
                if sampled or stage_exited:
                    store.sample({"step": self.completed_steps, "physical_step": self.protocol.steps,
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

        def _save_native_restart(self, output, stem, box):
            if store.retention != "full":
                return None
            directory = store.checkpoints / stem
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
            return store.relative(directory / "SpheresPart.rest")

        def _save_boundaries(self, output):
            boundaries = self.protocol.take_boundaries()
            if not boundaries:
                return
            box = self.adapter.box()
            saved = store.state(self._particle_arrays(), time=self.protocol.time, box=box, key=self.completed_steps)
            restart = self._save_native_restart(output, saved["state_id"], box)
            for boundary in boundaries:
                store.boundary({**saved, **boundary, "physical_step": boundary["step"],
                                "step": self.completed_steps, "restart": restart,
                                "checkpoint_capabilities": {"analysis": True, "rollback": False, "resume": False}})

        def Finalize(self):
            if self.rollback_checkpoint is not None:
                super().Finalize()
                return
            if self.protocol is None:
                self.adapter = KratosProtocolAdapter(self, execution)
                final_observables = {'mean_coordination_number', 'fabric_tensor'}
                if execution['boundary'] == 'periodic':
                    final_observables.add('thermal_conductivity')
                self.observables = self.adapter.observe(final_observables)
                store.sample({"step": self.completed_steps, "physical_step": self.completed_steps,
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

    runner = None
    checkpoint = None
    while True:
        parameters = KM.Parameters((inputs / "ProjectParametersDEM.json").read_text(encoding="utf-8"))
        if checkpoint is not None:
            parameters["solver_settings"]["model_import_settings"]["input_type"].SetString("rest")
            box = checkpoint['metadata']['box']
            for axis, letter in enumerate('XYZ'):
                parameters[f'BoundingBoxMin{letter}'].SetDouble(box['origin'][axis])
                parameters[f'BoundingBoxMax{letter}'].SetDouble(box['origin'][axis] + box['lengths'][axis])
        analysis = JPGenAnalysis(KM.Model(), parameters, runner, checkpoint)
        analysis.Run()
        if analysis.rollback_checkpoint is None:
            break
        runner = analysis.protocol
        checkpoint = analysis.rollback_checkpoint
    (output / "execution_report.json").write_text(json.dumps({
        "steps": analysis.completed_steps,
        "stop_reason": (analysis.protocol.stop_reason if analysis.protocol.failed else "protocol_complete") if execution.get("protocol") else "end_time",
        "time": analysis.final_state["time"],
        "time_step": {"mode": "fixed", "value": execution["end_time"] / execution["steps"]},
        "completed_stages": analysis.protocol.completed_stages if analysis.protocol else 0,
        "accepted_targets": analysis.protocol.accepted_targets if analysis.protocol else 0,
        "attempted_duration": analysis.protocol.attempted_steps * analysis.protocol.dt if analysis.protocol else 0.0,
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
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
