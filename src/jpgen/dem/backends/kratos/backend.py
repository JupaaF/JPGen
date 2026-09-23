"""Kratos adapter using an isolated process and inspectable case files."""

import json
import os
import shutil
import subprocess
import sys
import time
from zipfile import BadZipFile
from dataclasses import dataclass
from pathlib import Path

from ....configuration_values import integer, mapping, number
from ....errors import ConfigurationError, DemExecutionError
from ...protocol import STRESS_OBSERVABLES, required_observables, control_types
from ...domain import DemState
from ...state_exchange import read_state
from ....packing.domain.box import Box
from ..base import ExecutionReport, PreparedDemCase
from .definition import CAPABILITIES
from .case_writer import CONTACT_LAWS, write_case


@dataclass(frozen=True)
class KratosBackend:
    python: str
    installation: str | None
    threads: int
    timeout_seconds: float | None

    name = "kratos"
    capabilities = CAPABILITIES

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
        self.capabilities.validate(plan)
        if plan.contact.model not in CONTACT_LAWS:
            raise ConfigurationError(f"Kratos contact model must be one of: {', '.join(CONTACT_LAWS)}.")
        probe_code = "import KratosMultiphysics\nfrom KratosMultiphysics.DEMApplication.DEM_analysis_stage import DEMAnalysisStage"
        if plan.protocol and self.capabilities.native_restart_export:
            probe_code += "\nassert hasattr(KratosMultiphysics, 'FileSerializer'), 'Kratos lacks native restart serialization'"
            probe_code += "\nassert hasattr(KratosMultiphysics.Serializer, 'SHALLOW_GLOBAL_POINTERS_SERIALIZATION'), 'Kratos lacks restart pointer serialization'"
        if plan.protocol:
            probe_code += "\nfrom KratosMultiphysics.DEMApplication import SphericElementGlobalPhysicsCalculator as Physics"
            for method in ("CalculateTranslationalKinematicEnergy", "CalculateRotationalKinematicEnergy", "CalculateTotalVolume"):
                probe_code += f"\nassert hasattr(Physics, '{method}'), 'Kratos lacks {method}'"
            if 'unbalanced_force' in required_observables(plan.protocol["stages"]):
                probe_code += "\nfrom KratosMultiphysics.DEMApplication import ContactElementGlobalPhysicsCalculator as ContactPhysics"
                probe_code += "\nassert hasattr(ContactPhysics, 'CalculateUnbalancedForceWithinSphere'), 'Kratos lacks unbalanced force measurement'"
        if plan.protocol:
            # These hooks are not available in every Kratos distribution.
            if control_types(plan.protocol["stages"]) - {"free_evolution"}:
                probe_code += "\nassert hasattr(DEMAnalysisStage, 'UpdateSearchStartegyAndCPlusPlusStrategy'), 'Kratos lacks periodic cell control'"
                probe_code += "\nfrom KratosMultiphysics import VariableUtils"
                for method in ("GetCurrentPositionsVector", "SetCurrentPositionsVector",
                               "GetSolutionStepValuesVector", "SetSolutionStepValuesVector"):
                    probe_code += f"\nassert hasattr(VariableUtils, '{method}'), 'Kratos lacks {method}'"
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
            return ExecutionReport(
                return_code=return_code, elapsed_seconds=elapsed, versions=result["versions"],
                steps=result["steps"], stop_reason=result["stop_reason"],
                completed_stages=result["completed_stages"],
                failed_stage=result.get("failed_stage"), observables=result["observables"],
                time=result.get("time"), time_step=result.get("time_step", {}),
                control=result.get("control", {}),
            )
        except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
            raise DemExecutionError(f"Invalid Kratos execution report: {error}") from error

    def collect(self, prepared, report):
        try:
            raw = read_state(prepared.directory / "native_results")
            raw["box"] = Box(**raw["box"])
            state = DemState(**raw)
            if prepared.case.boundary == "periodic":
                # Kratos wraps before integration; canonicalize a final-step crossing.
                positions = state.box.origin + (state.positions - state.box.origin) % state.box.lengths
                state = DemState(state.ids, positions, state.radii, state.velocities,
                                 state.angular_velocities, state.time, state.box)
            return state
        except (OSError, ValueError, TypeError, KeyError, EOFError, BadZipFile) as error:
            raise DemExecutionError(f"Invalid Kratos final state: {error}") from error
