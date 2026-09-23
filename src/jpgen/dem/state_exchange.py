"""Versioned NumPy exchange for standalone DEM workers; no solver imports."""

import json
from zipfile import ZipFile, ZIP_STORED

import numpy as np


SCHEMA = "JPGen.dem.state"
VERSION = "1.0"
ARRAYS = ("ids", "positions", "radii", "velocities", "angular_velocities")


def write_state(directory, arrays, *, time, box, stem="final_state"):
    """Write one array at a time, publishing metadata after the binary archive.

    ``arrays`` yields (name, array) pairs in ARRAYS order. Uncompressed NPY
    members avoid compression work and Python lists of particle values.
    """
    metadata_path = directory / f"{stem}.json"
    # A manually rerun case must not retain a previous completion marker.
    metadata_path.unlink(missing_ok=True)
    temporary = directory / f"{stem}.npz.tmp"
    names = []
    with ZipFile(temporary, "w", compression=ZIP_STORED, allowZip64=True) as archive:
        for name, array in arrays:
            names.append(name)
            with archive.open(name + ".npy", "w", force_zip64=True) as stream:
                np.lib.format.write_array(stream, array, allow_pickle=False)
            del array
    if tuple(names) != ARRAYS:
        raise ValueError("Invalid DEM state array names or order.")
    temporary.replace(directory / f"{stem}.npz")
    temporary = directory / f"{stem}.json.tmp"
    temporary.write_text(json.dumps({
        "schema": SCHEMA, "schema_version": VERSION, "units": "SI",
        "time": time, "box": box,
    }, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(metadata_path)


def read_state(directory, stem="final_state"):
    """Read numeric arrays without pickle; domain validation belongs to the caller."""
    metadata = json.loads((directory / f"{stem}.json").read_text(encoding="utf-8"))
    if (not isinstance(metadata, dict)
            or metadata.get("schema") != SCHEMA or metadata.get("schema_version") != VERSION
            or metadata.get("units") != "SI"):
        raise ValueError("Unsupported DEM state exchange schema or units.")
    with np.load(directory / f"{stem}.npz", allow_pickle=False) as archive:
        if len(archive.files) != len(ARRAYS) or set(archive.files) != set(ARRAYS):
            raise ValueError("Invalid state archive members.")
        arrays = {name: archive[name] for name in ARRAYS}
    for name, array in arrays.items():
        expected = np.dtype("int64" if name == "ids" else "float64")
        if array.dtype.kind != expected.kind or array.dtype.itemsize != expected.itemsize:
            raise ValueError(f"Invalid state dtype: {name}.")
    return dict(arrays, time=metadata["time"], box=metadata["box"])
