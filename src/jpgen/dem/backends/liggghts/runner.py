"""Standalone isolated LIGGGHTS worker; requires NumPy and the native library."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import numpy as np
from library import Library
from protocol import ProtocolRunner, STRESS_OBSERVABLES
from protocol_adapter import LiggghtsProtocolAdapter
from output_writer import StageOutput
from state_exchange import write_state
from atomic_io import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    inputs = Path(__file__).resolve().parent
    if args.output_dir:
        stage = args.output_dir.resolve()
        if stage.exists():
            raise FileExistsError("Standalone output directory must not already exist")
        copied = stage / "backend/liggghts/input"
        shutil.copytree(inputs, copied)
        inputs = copied
    stage = inputs.parents[2]
    native = stage / "backend/liggghts/native"
    native.mkdir(parents=True, exist_ok=True)
    with (native / ".worker-started").open("x") as marker:
        marker.write("Use --output-dir for a fresh standalone execution.\n")
    os.chdir(native)
    execution = json.loads((inputs / "execution.json").read_text())
    store = StageOutput(stage, execution["retention"], engine="liggghts")
    library = Library(execution["options"]["library"], execution["options"]["threads"])
    try:
        library.file(inputs / "in.liggghts")
        adapter = LiggghtsProtocolAdapter(library, execution, np.load(inputs / "particle_ids.npy", allow_pickle=False))
        runner = ProtocolRunner(execution["protocol"], execution["dt"]) if execution["protocol"] else None
        output_names = {"kinetic_energy", "mean_coordination_number", "fabric_tensor"}
        if adapter.periodic:
            output_names |= STRESS_OBSERVABLES | {"solid_fraction", "bulk_density", "unbalanced_force", "normalized_kinetic_energy", "thermal_conductivity"}
        steps = 0
        values = adapter.observe((runner.observables if runner else set()) | output_names)

        def boundaries():
            records = runner.take_boundaries() if runner else []
            if not records:
                return
            saved = store.state(adapter.arrays(), time=steps * execution["dt"], box=adapter.box(), key=steps)
            restart = None
            if store.retention == "full":
                path = store.checkpoints / (saved["state_id"] + ".restart")
                library.command(f'write_restart "{path}"')
                restart = store.relative(path)
            for record in records:
                store.boundary({**saved, **record, "step": steps, "physical_step": record["step"],
                    "restart": restart, "checkpoint_capabilities": {"analysis": True, "rollback": False, "resume": False}})

        if runner:
            runner.attach(adapter)
            boundaries()
        while (not runner.done if runner else steps < execution["steps"]):
            path = runner.path if runner else None
            if runner:
                adapter.apply(runner.act(values, adapter.control_context(execution["dt"])), execution["dt"])
            library.command("run 1 pre no post no")
            steps += 1
            requested = runner.observables if runner else set()
            values = adapter.observe(requested)
            if runner:
                values = runner.advance(values)
            sampled = (steps % execution["protocol"]["sample_every"] == 0 or runner.stage_exited
                       if runner else steps == execution["steps"])
            if sampled:
                values.update(adapter.observe(output_names - values.keys()))
                store.sample({"step": steps, "physical_step": steps, "stage": path, "observables": values,
                              "box": adapter.box(), "time_step": {"dt": execution["dt"]}})
            boundaries()
            if runner and runner.stage_exited and not runner.done:
                values.update(adapter.observe(runner.observables - values.keys()))
        final_time = steps * execution["dt"]
        values.update(adapter.observe(output_names - values.keys()))
        write_state(native, adapter.arrays(), time=final_time, box=adapter.box())
        saved = store.state(source=native / "final_state", time=final_time, box=adapter.box(), key=steps)
        store.boundary({**saved, "kind": "diagnostic" if runner and runner.failed else "final", "phase": "end",
                        "step": steps, "stage": runner.path if runner else None,
                        "accepted": False if runner and runner.failed else None})
        atomic_json(native / "execution_report.json", {"steps": steps, "time": final_time,
            "stop_reason": (runner.stop_reason if runner.failed else "protocol_complete") if runner else "end_time",
            "completed_stages": runner.completed_stages if runner else 0,
            "accepted_targets": runner.accepted_targets if runner else 0,
            "attempted_duration": steps * execution["dt"] if runner else 0.0,
            "diagnostics": runner.diagnostics if runner else {}, "failed_stage": runner.failed_stage if runner else None,
            "observables": values, "time_step": {"mode": "fixed", "value": execution["dt"]},
            "control": {"implementation": "jpgen_portable", "actuators": ["cell_strain_rate", "symmetric_wall_velocity"],
                "unbalanced_force_definition": "RMS particle total force / RMS contact force; zero without contacts"},
            "versions": {"liggghts": library.version, "jpgen_liggghts_api": 3,
                "openmp_threads": library.threads, "python": platform.python_version()}})
    finally:
        library.close()


if __name__ == "__main__":
    main()
