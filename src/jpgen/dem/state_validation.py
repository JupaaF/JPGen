"""Validate saved scientific states and their run-relative boundary references."""

import json
import math

import numpy as np

from ..particle_data import validate_time
from ..run_repository import relative_path
from .state_exchange import read_state
from .protocol import iter_stages


def validate_accepted_states(directory, expected_count, stages):
    """Check reported pressure/density acceptances against their saved states.

    Failed protocols may publish only a prefix of the configured targets.
    Successful completion and the total target count are checked separately
    by validate_execution_report.
    """
    from ..run_reader import read_jsonl

    if type(expected_count) is not int or expected_count < 0:
        raise ValueError("Invalid accepted target count.")
    records = []
    for item in read_jsonl(directory / "results/states.jsonl"):
        if (not isinstance(item, dict) or item.get("schema") != "JPGen.dem.record"
                or item.get("schema_version") != "1.0"):
            raise ValueError("Invalid accepted state index schema.")
        if item.get("accepted") is True and "target" in item:
            records.append(item)
    if len(records) != expected_count:
        raise ValueError("Accepted state index does not match the execution report.")

    def targets():
        for path, stage in iter_stages(stages):
            if '_path_target' in stage:
                yield path, stage['_path_target'], 'stage'
            elif stage['control']['type'] == 'density_continuation':
                yield path, {'observable': 'solid_fraction', 'index': 1,
                             'value': stage['control']['target']}, 'density_target'

    expected = targets()
    previous_step = -1
    validated = {}
    for item in records:
        target = next(expected, None)
        if target is None:
            raise ValueError("Accepted target count exceeds configured path targets.")
        path, target_spec, kind = target
        step = item["step"]
        if (item.get("phase") != "end" or item.get("kind") != kind
                or type(step) is not int or step <= previous_step
                or item.get("path") != path or item.get("target") != target_spec):
            raise ValueError("Invalid accepted state index entry.")
        previous_step = step
        validate_indexed_state(directory.parent.parent, item, validated)


def validate_indexed_state(root, record, validated=None):
    """Validate a boundary and return newly read arrays; cache only small metadata."""
    if validated is None:
        validated = {}
    loaded = None
    if not isinstance(record.get("state_id"), str) or not record["state_id"]:
        raise ValueError("State index requires a nonempty state_id.")
    stem = relative_path(root, record["state"])
    identity = ("state_id", record["state_id"])
    if identity in validated and validated[identity] != stem:
        raise ValueError("State ID refers to more than one saved state.")
    validated[identity] = stem
    if stem not in validated:
        loaded = read_state(stem.parent, stem.name)
        with np.errstate(over="ignore", invalid="ignore", under="ignore"):
            fraction = float(np.sum((4 * np.pi / 3) * loaded["radii"]**3)
                             / np.prod(loaded["box"]["lengths"]))
        validated[stem] = {"time": loaded["time"], "box": loaded["box"],
                           "state_id": record["state_id"], "solid_fraction": fraction}
    state = validated[stem]
    validate_time(record.get("time"))
    if (state["state_id"] != record["state_id"]
            or not math.isclose(record["time"], state["time"], rel_tol=1e-12, abs_tol=1e-15)):
        raise ValueError("State index identity or time does not match the saved state.")
    if "box" in record and record["box"] != state["box"]:
        raise ValueError("State index box does not match the saved state.")
    for field in ("metadata",):
        if record.get(field) is not None and not relative_path(root, record[field]).is_file():
            raise ValueError(f"State reference is missing: {field}.")
    if record.get("kind") == "density_target" and record.get("accepted") is True:
        metadata = json.loads(relative_path(root, record["metadata"]).read_text(encoding="utf-8"))
        if (not isinstance(metadata, dict)
                or metadata.get("schema") != "JPGen.dem.target" or metadata.get("schema_version") != "1.1"
                or metadata["target"] != record["target"]["value"]
                or metadata["index"] != record["target"]["index"]
                or metadata["stage"] != record.get("path", record.get("stage"))):
            raise ValueError("Density target metadata does not match its index.")
        validate_time(metadata["density_atol"])
        fraction = metadata["observables"]["solid_fraction"]
        validate_time(fraction)
        validate_time(metadata["target"])
        if not math.isclose(fraction, state["solid_fraction"], rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError("Density target fraction does not match its particle geometry.")
        if fraction + metadata["density_atol"] < metadata["target"]:
            raise ValueError("Accepted density target is outside its tolerance.")
        validate_time(metadata["time"])
        if not math.isclose(metadata["time"], state["time"], rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError("Density target time does not match its saved state.")

    return loaded
