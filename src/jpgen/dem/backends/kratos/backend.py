"""Kratos adapter using an isolated process and inspectable case files."""

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ....configuration_values import integer, mapping, number
from ....errors import ConfigurationError, DemExecutionError
from ...protocol import STRESS_OBSERVABLES, required_observables, iter_stages, control_types
from ...domain import DemState
from ....packing.domain.box import Box
from ..base import ExecutionReport, PreparedDemCase
from .case_writer import CONTACT_LAWS, write_case


@dataclass(frozen=True)
class KratosBackend:
    python: str
    installation: str | None
    threads: int
    timeout_seconds: float | None

    name = "kratos"

    @classmethod
    def from_config(cls, raw):
        mapping(raw, "dem.backend_options", {"python", "installation", "threads", "timeout_seconds"})
        python = raw.get("python", sys.executable)
        if not isinstance(python, str) or not python.strip():
            raise ConfigurationError("Kratos python must name an executable.")
        executable = shutil.which(python)
        if executable is None:
            raise ConfigurationError(f"Kratos Python executable not found: {python}.")
        installation = raw.get("installation")
        if installation is not None:
            if not isinstance(installation, str) or not installation.strip():
                raise ConfigurationError("Kratos installation must be a directory path.")
            installation = str(Path(installation).expanduser().resolve())
            if not (Path(installation) / "KratosMultiphysics" / "__init__.py").is_file():
                raise ConfigurationError(f"Kratos installation not found: {installation}.")
        timeout = raw.get("timeout_seconds")
        if timeout is not None:
            timeout = number(timeout, "timeout_seconds", 0, strict_min=True)
        return cls(str(Path(executable).absolute()), installation,
                   integer(raw.get("threads", 1), "threads"), timeout)

    def to_config(self):
        return {"python": self.python, "installation": self.installation,
                "threads": self.threads, "timeout_seconds": self.timeout_seconds}

    def environment(self):
        environment = os.environ.copy()
        environment["OMP_NUM_THREADS"] = str(self.threads)
        if self.installation:
            for key, path in (("PYTHONPATH", self.installation),
                              ("LD_LIBRARY_PATH", str(Path(self.installation) / "libs"))):
                environment[key] = path + (os.pathsep + environment[key] if environment.get(key) else "")
        return environment

    def validate(self, plan):
        if plan.contact.model not in CONTACT_LAWS:
            raise ConfigurationError(f"Kratos contact model must be one of: {', '.join(CONTACT_LAWS)}.")
        probe_code = "from KratosMultiphysics.DEMApplication.DEM_analysis_stage import DEMAnalysisStage"
        if plan.protocol:
            # These hooks are not available in every Kratos distribution.
            if control_types(plan.protocol["stages"]) - {"free_evolution"}:
                probe_code += "\nassert hasattr(DEMAnalysisStage, 'UpdateSearchStartegyAndCPlusPlusStrategy'), 'Kratos lacks periodic cell control'"
            if required_observables(plan.protocol["stages"]) & STRESS_OBSERVABLES:
                probe_code += "\nassert hasattr(DEMAnalysisStage, 'MeasureSphereForGettingGlobalStressTensor'), 'Kratos lacks contact stress measurement'"
        command = [self.python, "-c", probe_code]
        try:
            probe = subprocess.run(command, env=self.environment(), capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ConfigurationError(f"Cannot start Kratos runtime: {error}") from error
        if probe.returncode:
            raise ConfigurationError(f"Kratos DEM runtime is unavailable: {(probe.stderr or probe.stdout)[-4000:]}")

    def prepare(self, case, directory):
        write_case(case, directory)
        return PreparedDemCase(directory.resolve(), case)

    def run(self, prepared, observer=None):
        directory = prepared.directory
        command = [self.python, str(directory / "input" / "run.py")]
        (directory / "input" / "runtime.json").write_text(json.dumps({
            "command": command, "backend_options": self.to_config(),
        }, indent=2) + "\n", encoding="utf-8")
        start = time.monotonic()
        with (directory / "logs" / "stdout.log").open("w") as stdout, (directory / "logs" / "stderr.log").open("w") as stderr:
            try:
                process = subprocess.Popen(command, cwd=directory / "native_results", env=self.environment(),
                                           stdout=stdout, stderr=stderr)
                try:
                    return_code = process.wait(timeout=self.timeout_seconds)
                except BaseException:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise
            except subprocess.TimeoutExpired as error:
                raise DemExecutionError(f"Kratos exceeded timeout; see {directory / 'logs'}.") from error
            except OSError as error:
                raise DemExecutionError(f"Cannot execute Kratos: {error}") from error
        elapsed = time.monotonic() - start
        if return_code:
            raise DemExecutionError(f"Kratos exited with code {return_code}; see {directory / 'logs'}.")
        try:
            result = json.loads((directory / "native_results" / "execution_report.json").read_text())
            if type(result["steps"]) is not int:
                raise ValueError("Invalid completed step count.")
            if prepared.case.protocol is None:
                if result["steps"] != prepared.case.steps or result["stop_reason"] != "end_time":
                    raise ValueError("Kratos did not complete the requested steps.")
            else:
                if result["stop_reason"] == "max_duration":
                    stage = result["history"][-1]["path"]
                    raise DemExecutionError(f"Stage {stage} exhausted max_duration before its condition was met; see native_results/protocol_history.json.")
                if result["stop_reason"] != "protocol_complete" or not 0 < result["steps"] <= prepared.case.steps:
                    raise ValueError("Kratos did not complete the requested protocol.")
                expected = iter_stages(prepared.case.protocol["stages"])
                end_step = 0
                for entry in result["history"]:
                    item = next(expected, None)
                    if (item is None or entry["path"] != item[0] or entry["stop_reason"] != "condition_met"
                            or entry["start_step"] != end_step or entry["end_step"] <= end_step):
                        raise ValueError("Invalid protocol stage history.")
                    end_step = entry["end_step"]
                if next(expected, None) is not None or end_step != result["steps"]:
                    raise ValueError("Incomplete protocol history.")
            return ExecutionReport(return_code, elapsed, result["versions"], result["steps"],
                                   result["stop_reason"], result["history"], result["observables"])
        except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
            if isinstance(error, DemExecutionError):
                raise
            raise DemExecutionError(f"Invalid Kratos execution report: {error}") from error

    def collect(self, prepared, report):
        try:
            raw = json.loads((prepared.directory / "native_results" / "final_state.json").read_text())
            raw["box"] = Box(**raw["box"])
            state = DemState(**raw)
            if state.box.periodic != (prepared.case.boundary == "periodic"):
                raise ValueError("Kratos returned an inconsistent boundary type.")
            initial = prepared.case.packing
            order = np.argsort(initial.ids)
            if not np.array_equal(state.ids, initial.ids[order]):
                raise ValueError("Kratos changed particle IDs or particle count.")
            if not np.array_equal(state.radii, initial.radii[order]):
                raise ValueError("Kratos changed particle radii.")
            if abs(state.time - report.steps * prepared.case.time_step) > prepared.case.time_step * 1e-5:
                raise ValueError("Kratos did not reach the requested final time.")
            if prepared.case.boundary == "periodic":
                # Kratos wraps before integration; canonicalize a final-step crossing.
                positions = state.box.origin + (state.positions - state.box.origin) % state.box.lengths
                state = DemState(state.ids, positions, state.radii, state.velocities,
                                 state.angular_velocities, state.time, state.box)
            return state
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise DemExecutionError(f"Invalid Kratos final state: {error}") from error
