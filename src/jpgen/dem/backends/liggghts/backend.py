"""LIGGGHTS adapter executing in an isolated Python worker."""
from dataclasses import dataclass
import hashlib
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
from ....packing.domain.box import Box
from ...domain import DemState
from ...state_exchange import read_state
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
        code = ("import ctypes,sys,numpy; lib=ctypes.CDLL(sys.argv[1]); "
                "assert lib.jpgen_liggghts_api_version()==3, 'Rebuild LIGGGHTS with tools/build_liggghts.py (ABI 3 required)'; "
                "assert all(hasattr(lib,name) for name in "
                "('jpgen_liggghts_contact_rows','jpgen_liggghts_set_cell','jpgen_liggghts_refresh_ghosts',"
                "'jpgen_liggghts_set_threads','jpgen_liggghts_threads'))")
        try:
            probe = subprocess.run([self.python, "-c", code, self.library], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ConfigurationError(f"Cannot start LIGGGHTS runtime: {error}") from error
        if probe.returncode:
            raise ConfigurationError(f"LIGGGHTS JPGen runtime unavailable: {probe.stderr[-2000:]}")

    def prepare(self, case, directory, *, retention="full"):
        write_case(case, directory, self.to_config(), retention=retention)
        return PreparedDemCase(directory.resolve(), case)

    def run(self, prepared, observer=None):
        directory = prepared.directory
        inputs = directory / "backend/liggghts/input"
        native = directory / "backend/liggghts/native"
        command = [self.python, str(inputs / "run.py")]
        (inputs / "runtime.json").write_text(json.dumps({"command": command, "backend_options": self.to_config(),
            "library_sha256": hashlib.sha256(Path(self.library).read_bytes()).hexdigest()}, indent=2) + "\n")
        environment = os.environ.copy()
        environment["OMP_NUM_THREADS"] = str(self.threads)
        environment["OPENBLAS_NUM_THREADS"] = str(self.threads)
        environment["MKL_NUM_THREADS"] = str(self.threads)
        start = time.monotonic()
        with (directory / "logs/stdout.log").open("w") as stdout, (directory / "logs/stderr.log").open("w") as stderr:
            try:
                process = subprocess.Popen(command, cwd=native, stdout=stdout, stderr=stderr, env=environment)
                try:
                    code = process.wait(timeout=self.timeout_seconds)
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
            return ExecutionReport(return_code=code, elapsed_seconds=time.monotonic() - start, **result)
        except (OSError, ValueError, TypeError) as error:
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
