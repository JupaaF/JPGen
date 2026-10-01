"""Common particle arrays, SI units and geometry checks; no solver imports."""

import math

import numpy as np


UNITS = {"ids": "1", "positions": "m", "radii": "m", "velocities": "m/s",
         "angular_velocities": "rad/s"}
ARRAYS = tuple(UNITS)


def validate_particle_arrays(arrays, *, strict_dtype=False):
    if set(arrays) != set(ARRAYS):
        raise ValueError("Invalid particle array names.")
    ids = np.asarray(arrays["ids"])
    count = ids.shape[0] if ids.ndim == 1 else 0
    for name in ARRAYS:
        validate_particle_array(name, arrays[name], count, strict_dtype=strict_dtype)


def validate_particle_array(name, value, count, *, strict_dtype=False):
    array = np.asarray(value)
    shape = (count,) if name in {"ids", "radii"} else (count, 3)
    if name not in ARRAYS or count < 1 or array.shape != shape or array.dtype.kind not in "iuf":
        raise ValueError(f"Invalid particle array: {name}.")
    if strict_dtype:
        expected = np.dtype("int64" if name == "ids" else "float64")
        if array.dtype.kind != expected.kind or array.dtype.itemsize != expected.itemsize:
            raise ValueError(f"Invalid particle dtype: {name}.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"Nonfinite particle array: {name}.")
    if name == "ids" and (array.dtype.kind not in "iu" or np.any(array <= 0)
                          or np.any(array > np.iinfo(np.int64).max)
                          or len(np.unique(array)) != count):
        raise ValueError("Particle IDs must be unique positive int64 values.")
    if name == "radii" and np.any(array <= 0):
        raise ValueError("Particle radii must be positive.")


def validate_time(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError("Simulation time must be a finite nonnegative number.")
    if not math.isfinite(value) or value < 0:
        raise ValueError("Simulation time must be a finite nonnegative number.")


def validate_box_geometry(origin, lengths, periodic):
    origin, lengths = np.asarray(origin, dtype=float), np.asarray(lengths, dtype=float)
    if origin.shape != (3,) or lengths.shape != (3,):
        raise ValueError("Box origin and lengths must contain three values.")
    if not np.all(np.isfinite(origin)) or not np.all(np.isfinite(lengths)) or np.any(lengths <= 0):
        raise ValueError("Invalid box geometry.")
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        upper, volume = origin + lengths, float(np.prod(lengths))
    if not np.all(np.isfinite(upper)) or np.any(upper == origin):
        raise ValueError("Box bounds cannot be represented accurately in float64.")
    if not np.isfinite(volume) or volume <= 0:
        raise ValueError("Box volume must be finite and positive in float64.")
    if not isinstance(periodic, (bool, np.bool_)):
        raise ValueError("Box periodicity must be a boolean.")


def validate_state_metadata(time, box):
    validate_time(time)
    if not isinstance(box, dict) or set(box) != {"origin", "lengths", "periodic"}:
        raise ValueError("State box must contain origin, lengths and periodic.")
    validate_box_geometry(**box)
