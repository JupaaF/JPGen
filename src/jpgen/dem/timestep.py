"""Fixed DEM time-step validation."""
import math


def validate_time_step(raw):
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw <= 0:
        raise ValueError('dem.time_step must be a finite positive number specifying a fixed step.')
    return float(raw)
