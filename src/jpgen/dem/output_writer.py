"""Portable DEM result writer, also copied into standalone solver cases.

All index paths are relative to the run root. Array metadata is the state
commit marker; an index record is appended only after the state is published.
"""

import json
from pathlib import Path

if __package__:
    from .state_exchange import write_state, read_state
    from ..atomic_io import atomic_copy, atomic_json
else:
    from state_exchange import write_state, read_state
    from atomic_io import atomic_copy, atomic_json


class StageOutput:
    def __init__(self, stage):
        self.stage = Path(stage)
        self.root = self.stage.parent.parent
        self.results = self.stage / "results"
        self.execution = self.stage / "execution"
        self.sequence = 0
        self.state_serial = 0
        self.last_state_key = None
        self.last_state = None
        for directory in (self.results / "states", self.execution):
            directory.mkdir(parents=True, exist_ok=True)

    def relative(self, path):
        return Path(path).relative_to(self.root).as_posix()

    def append(self, path, record):
        self.sequence += 1
        record = {"schema": "JPGen.dem.record", "schema_version": "1.0",
                  "sequence": self.sequence, **record}
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
        return record

    def state(self, arrays=None, *, time, box, source=None, key=None):
        if key is not None and key == self.last_state_key:
            return dict(self.last_state)
        self.state_serial += 1
        state_id = f"state_{self.state_serial:08d}"
        stem = self.results / "states" / state_id
        if source is None:
            write_state(stem.parent, arrays, time=time, box=box, stem=stem.name)
        else:
            completed = read_state(Path(source).parent, Path(source).name)
            if completed["time"] != time or completed["box"] != box:
                raise ValueError("State source metadata does not match the published state.")
            del completed
            # Publish the completed array archive before its metadata.
            for suffix in (".npz", ".json"):
                atomic_copy(Path(str(source) + suffix), Path(str(stem) + suffix))
        self.last_state_key = key
        self.last_state = {"state_id": state_id, "state": self.relative(stem), "time": time,
                           "validation": "exchange_complete"}
        return dict(self.last_state)

    def density_state(self, arrays, box, metadata, *, accepted):
        saved = self.state(arrays, time=metadata['time'], box=box, key=metadata['step'])
        record = {**saved, 'path': metadata['stage'], 'step': metadata['step'],
                  'phase': 'end' if accepted else 'before_reset',
                  'kind': 'density_target' if accepted else 'density_checkpoint',
                  'cycles': metadata['cycles'], 'observables': metadata['observables'],
                  'static_friction': metadata['static_friction'],
                  'dynamic_friction': metadata['dynamic_friction']}
        if accepted:
            metadata = dict(metadata, schema='JPGen.dem.target', schema_version='1.1')
            path = self.results / 'states' / (saved['state_id'] + '.target.json')
            atomic_json(path, metadata)
            record.update(accepted=True, metadata=self.relative(path),
                          target={'observable': 'solid_fraction', 'index': 1,
                                  'value': metadata['target']})
        return self.boundary(record)

    def boundary(self, record):
        return self.append(self.results / "states.jsonl", record)

    def sample(self, record):
        return self.append(self.results / "observables.jsonl", record)
