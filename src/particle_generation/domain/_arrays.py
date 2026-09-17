"""Internal NumPy normalization helpers for domain values."""

import numpy as np


def readonly_array(value, name, dtype=None):
    """Own a normalized array so callers cannot mutate domain state by aliasing it."""
    try:
        result = np.array(value, dtype=dtype, copy=True)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"Invalid particle array: {name}.") from error
    result.setflags(write=False)
    return result
