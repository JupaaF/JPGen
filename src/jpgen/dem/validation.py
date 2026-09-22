"""Solver-independent validation of execution reports and final particle states."""

import math

import numpy as np

from ..errors import DemExecutionError
from .backends.base import ExecutionReport
from .domain import DemCase, DemState
from .protocol import iter_stages


def validate_execution_report(case: DemCase, report: ExecutionReport) -> None:
    """Reject unsuccessful or incomplete execution before collecting results."""
    if not isinstance(report, ExecutionReport):
        raise DemExecutionError("DEM backend must return an ExecutionReport.")
    try:
        if type(report.return_code) is not int or report.return_code != 0:
            raise ValueError(f"DEM execution failed with return code {report.return_code}.")
        if type(report.steps) is not int:
            raise ValueError("Invalid completed step count.")
        final_time = report.time if report.time is not None else report.steps * case.time_step
        if not math.isfinite(final_time) or final_time <= 0 or report.steps <= 0:
            raise ValueError("Invalid final simulation time or completed step count.")
        if case.protocol is None:
            time_matches = math.isclose(final_time, case.end_time, rel_tol=1e-12,
                                        abs_tol=case.time_step * 1e-7)
            if ((report.steps != case.steps)
                    or not time_matches or report.stop_reason != "end_time"):
                raise ValueError("DEM did not complete the requested steps.")
        else:
            if report.stop_reason == "max_duration":
                stage = report.history[-1]["path"]
                raise DemExecutionError(f"Stage {stage} exhausted max_duration before its condition was met.")
            if (report.stop_reason != "protocol_complete"
                    or (report.steps > case.steps)
                    or final_time > case.end_time + case.time_step * 1e-7):
                raise ValueError("DEM did not complete the requested protocol.")
            expected = iter_stages(case.protocol["stages"])
            end_step = 0
            end_time = 0.0
            for entry in report.history:
                item = next(expected, None)
                if (item is None or entry["path"] != item[0] or entry["stop_reason"] != "condition_met"
                        or entry["start_step"] != end_step or entry["end_step"] <= end_step):
                    raise ValueError("Invalid protocol stage history.")
                if (not math.isclose(entry['start_time'], end_time, rel_tol=1e-12, abs_tol=1e-15)
                        or not math.isfinite(entry['end_time']) or entry['end_time'] <= end_time):
                    raise ValueError("Invalid physical times in protocol history.")
                end_step = entry["end_step"]
                end_time = entry['end_time']
            if (next(expected, None) is not None or end_step != report.steps
                    or not math.isclose(end_time, final_time, rel_tol=1e-12, abs_tol=1e-15)):
                raise ValueError("Incomplete protocol history.")
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
        if isinstance(error, DemExecutionError):
            raise
        raise DemExecutionError(f"Invalid DEM execution report: {error}") from error


def validate_final_state(case: DemCase, report: ExecutionReport, state: DemState) -> None:
    """Compare particle identity, geometry, boundary and time against the case.

    Particle order is adapter-defined; radii are compared by particle ID.
    An omitted final box denotes the initial box, as in common persistence.
    """
    if not isinstance(state, DemState):
        raise DemExecutionError("DEM backend must return a DemState.")
    initial = case.packing
    box = state.box or initial.box
    if box.periodic != (case.boundary == "periodic"):
        raise DemExecutionError("DEM returned an inconsistent boundary type.")
    initial_order = np.argsort(initial.ids)
    final_order = np.argsort(state.ids)
    if not np.array_equal(state.ids[final_order], initial.ids[initial_order]):
        raise DemExecutionError("DEM changed particle IDs or particle count.")
    if not np.array_equal(state.radii[final_order], initial.radii[initial_order]):
        raise DemExecutionError("DEM changed particle radii.")
    expected_time = report.time if report.time is not None else report.steps * case.time_step
    if not math.isclose(state.time, expected_time, rel_tol=1e-12, abs_tol=case.time_step * 1e-7):
        raise DemExecutionError("DEM did not reach the requested final time.")
