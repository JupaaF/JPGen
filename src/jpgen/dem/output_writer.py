"""Portable DEM result writer, also copied into standalone solver cases.

All index paths are relative to the run root. Array metadata is the state
commit marker; an index record is appended only after the state is published.
"""

import json
import shutil
from pathlib import Path

try:
    from .state_exchange import write_state
except ImportError:  # Standalone case.
    from state_exchange import write_state


class StageOutput:
    def __init__(self, stage, retention="full", *, engine):
        self.stage = Path(stage)
        self.root = self.stage.parent.parent
        self.results = self.stage / "results"
        self.execution = self.stage / "execution"
        self.checkpoints = self.stage / "backend" / engine / "checkpoints"
        self.retention = retention
        self.sequence = 0
        self.state_serial = 0
        self.last_state_key = None
        self.last_state = None
        self.branch_serial = 0
        self.branch_id = "branch_000000"
        self.attempt_id = None
        self.attempt_stage = None
        for directory in (self.results / "states", self.execution, self.checkpoints):
            directory.mkdir(parents=True, exist_ok=True)

    def relative(self, path):
        return Path(path).relative_to(self.root).as_posix()

    def context(self):
        return {"branch_id": self.branch_id, "attempt_id": self.attempt_id}

    def append(self, path, record):
        self.sequence += 1
        record = {"schema": "JPGen.dem.record", "schema_version": "1.0",
                  "sequence": self.sequence, **self.context(), **record}
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
        return record

    def attempt(self, record):
        if record.get("event") == "start":
            parent_branch = self.branch_id
            record = dict(record, parent_branch_id=parent_branch)
            self.branch_serial += 1
            self.branch_id = f"branch_{self.branch_serial:06d}"
            self.attempt_id = record["attempt"]
            self.attempt_stage = record["stage"]
        self.append(self.execution / "attempts.jsonl", {**record,
                    "attempt_id": record.get("attempt", self.attempt_id)})

    def state(self, arrays=None, *, time, box, source=None, key=None):
        if key is not None and key == self.last_state_key:
            return dict(self.last_state)
        self.state_serial += 1
        state_id = f"state_{self.state_serial:08d}"
        stem = self.results / "states" / state_id
        if source is None:
            write_state(stem.parent, arrays, time=time, box=box, stem=stem.name)
        else:
            # Source is a completed internal checkpoint. Publish arrays first.
            for suffix in (".npz", ".json"):
                temporary = Path(str(stem) + suffix + ".tmp")
                shutil.copyfile(Path(str(source) + suffix), temporary)
                temporary.replace(Path(str(stem) + suffix))
        self.last_state_key = key
        self.last_state = {"state_id": state_id, "state": self.relative(stem), "time": time,
                           "validation": "exchange_complete"}
        return dict(self.last_state)

    def boundary(self, record):
        if (record.get("path") or record.get("stage")) != self.attempt_stage:
            record = dict(record, attempt_id=None)
        return self.append(self.results / "states.jsonl", record)

    def sample(self, record):
        return self.append(self.results / "observables.jsonl", record)
