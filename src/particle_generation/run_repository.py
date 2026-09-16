"""Filesystem adapter for run configuration, status and atomic output staging."""

import json
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import yaml


@dataclass(frozen=True)
class RunWorkspace:
    directory: Path

    def save_configuration(self, configuration):
        path = self.directory / "configuration.yaml"
        path.write_text(yaml.safe_dump(configuration, sort_keys=False), encoding="utf-8")

    def save_summary(self, summary):
        path = self.directory / "summary.json"
        temporary = self.directory / "summary.json.tmp"
        temporary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    @contextmanager
    def stage_outputs(self):
        with tempfile.TemporaryDirectory(prefix=".output-", dir=self.directory) as staging:
            yield Path(staging)

    def publish(self, staging, filenames):
        for filename in filenames:
            (staging / filename).replace(self.directory / filename)


class RunRepository(Protocol):
    def create(self, configuration, initial_summary) -> RunWorkspace:
        """Create and initialize a unique workspace for one run."""


@dataclass(frozen=True)
class FileRunRepository:
    root: Path

    def create(self, configuration, initial_summary):
        self.root.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ_")
        directory = Path(tempfile.mkdtemp(prefix=stamp, dir=self.root))
        workspace = RunWorkspace(directory)
        workspace.save_configuration(configuration)
        workspace.save_summary(initial_summary)
        return workspace
