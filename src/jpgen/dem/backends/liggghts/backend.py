"""LIGGGHTS adapter executing in an isolated Python worker."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from zipfile import BadZipFile

from ....configuration_values import mapping, number, integer
from ....errors import ConfigurationError, DemExecutionError
from ....progress import DemProgress, emit
from ....packing.domain.box import Box
from ...domain import DemState
from ...state_exchange import read_state
from ...state_validation import validate_accepted_states
from ..base import ExecutionReport, PreparedDemCase
from .definition import CAPABILITIES
from .case_writer import write_case


@dataclass(frozen=True)
class LiggghtsBackend:
    library: str
    python: str
    timeout_seconds: float | None
    threads: int = 1
    name = "liggghts"
    capabilities = CAPABILITIES

    @classmethod
    def from_config(cls, raw):
        mapping(raw, "dem.backend_options", {"library", "python", "threads", "timeout_seconds"})
        library = raw.get("library", os.environ.get("JPGEN_LIGGGHTS_LIBRARY"))
        if library is None:
            library = ".deps/LIGGGHTS-PUBLIC/src/libliggghts_serial.so"
        if not isinstance(library, str) or not library.strip():
            raise ConfigurationError("LIGGGHTS library must be a shared-library path.")
        python = raw.get("python", sys.executable)
        if not isinstance(python, str) or not python.strip() or shutil.which(python) is None:
            raise ConfigurationError("LIGGGHTS python must name an available executable.")
        threads = integer(raw.get("threads", 1), "threads")
        if threads > 2**31 - 1:
            raise ConfigurationError("LIGGGHTS threads must fit a positive C int.")
        timeout = raw.get("timeout_seconds")
        if timeout is not None:
            timeout = number(timeout, "timeout_seconds", 0, strict_min=True)
        return cls(str(Path(library).expanduser().resolve()), str(Path(shutil.which(python)).absolute()), timeout, threads)

    def to_config(self):
        return {"library": self.library, "python": self.python,
                "threads": self.threads, "timeout_seconds": self.timeout_seconds}

    def validate(self, plan):
        if not Path(self.library).is_file():
            raise ConfigurationError(f"LIGGGHTS library not found: {self.library}. Build it with python tools/build_liggghts.py.")
        # Probe in a subprocess: native loader errors must never terminate the CLI.
        code = ("import sys\n"
                "if sys.version_info[:2] != (3,12): raise ValueError('LIGGGHTS worker requires Python 3.12')\n"
                "sys.path.insert(0,sys.argv[1])\n"
                "from library import Library,runtime_provenance\n"
                "runtime_provenance(sys.argv[2])\n"
                "runtime=Library(sys.argv[2],int(sys.argv[3]),log='none')\n"
                "runtime.close()\n")
        try:
            probe = subprocess.run([self.python, "-c", code, str(Path(__file__).parent),
                                    self.library, str(self.threads)], env=self.environment(),
                                   capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ConfigurationError(f"Cannot start LIGGGHTS runtime: {error}") from error
        if probe.returncode:
            raise ConfigurationError(f"LIGGGHTS JPGen runtime unavailable: {probe.stderr[-2000:]}")

    def environment(self):
        environment = os.environ.copy()
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            environment[name] = str(self.threads)
        return environment

    def prepare(self, case, directory, *, retention="full"):
        write_case(case, directory, self.to_config(), retention=retention)
        return PreparedDemCase(directory.resolve(), case)

    def run(self, prepared, observer=None):
        directory = prepared.directory
        inputs = directory / "backend/liggghts/input"
        native = directory / "backend/liggghts/native"
        command = [self.python, str(inputs / "run.py")]
        start = time.monotonic()
        with (directory / "logs/stdout.log").open("w") as stdout, (directory / "logs/stderr.log").open("w") as stderr:
            try:
                process = subprocess.Popen(command, cwd=native, stdout=stdout, stderr=stderr, env=self.environment())
                try:
                    last_progress = None
                    while process.poll() is None:
                        elapsed = time.monotonic() - start
                        if self.timeout_seconds is not None and elapsed >= self.timeout_seconds:
                            raise subprocess.TimeoutExpired(command, self.timeout_seconds)
                        progress = directory / "execution/progress.json"
                        if progress.exists():
                            record = json.loads(progress.read_text())
                            if record["step"] != last_progress:
                                emit(observer, DemProgress("liggghts", record["step"], record["time"], record["stage"]))
                                last_progress = record["step"]
                        remaining = self.timeout_seconds - elapsed if self.timeout_seconds is not None else 0.25
                        try:
                            process.wait(timeout=min(0.25, remaining))
                        except subprocess.TimeoutExpired:
                            pass
                    code = process.returncode
                    progress = directory / "execution/progress.json"
                    if progress.exists():
                        record = json.loads(progress.read_text())
                        if record["step"] != last_progress:
                            emit(observer, DemProgress("liggghts", record["step"], record["time"], record["stage"]))
                except BaseException:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise
            except (OSError, subprocess.TimeoutExpired) as error:
                raise DemExecutionError(f"Cannot execute LIGGGHTS: {error}; see {directory / 'logs'}.") from error
        if code:
            raise DemExecutionError(f"LIGGGHTS exited with code {code}; see {directory / 'logs'} and {native / 'liggghts.log'}.")
        try:
            result = json.loads((native / "execution_report.json").read_text())
            if prepared.case.protocol:
                validate_accepted_states(directory, result.get("accepted_targets", 0),
                                         prepared.case.protocol["stages"])
            return ExecutionReport(return_code=code, elapsed_seconds=time.monotonic() - start, **result)
        except (OSError, ValueError, TypeError, KeyError, IndexError, EOFError, BadZipFile) as error:
            raise DemExecutionError(f"Invalid LIGGGHTS execution report: {error}") from error

    def collect(self, prepared, report):
        try:
            raw = read_state(prepared.directory / "backend/liggghts/native")
            raw["box"] = Box(**raw["box"])
            if raw["box"].periodic:
                raw["positions"] = raw["box"].origin + (raw["positions"] - raw["box"].origin) % raw["box"].lengths
            return DemState(**raw)
        except (OSError, ValueError, TypeError, KeyError, EOFError, BadZipFile) as error:
            raise DemExecutionError(f"Invalid LIGGGHTS final state: {error}") from error
