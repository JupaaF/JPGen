"""Versioned NumPy exchange for standalone DEM workers; no solver imports."""

import json
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED

import numpy as np

if __package__:
    from ..atomic_io import atomic_path, atomic_json
    from ..particle_data import ARRAYS, validate_particle_arrays, validate_particle_array, validate_state_metadata
else:
    from atomic_io import atomic_path, atomic_json
    from particle_data import ARRAYS, validate_particle_arrays, validate_particle_array, validate_state_metadata


SCHEMA = "JPGen.dem.state"
VERSION = "1.0"


def write_state(directory, arrays, *, time, box, stem="final_state"):
    """Write one array at a time, publishing metadata after the binary archive.

    ``arrays`` yields (name, array) pairs in ARRAYS order. Uncompressed NPY
    members avoid compression work and Python lists of particle values.
    """
    directory = Path(directory)
    validate_state_metadata(time, box)
    metadata_path = directory / f"{stem}.json"
    # A manually rerun case must not retain a previous completion marker.
    metadata_path.unlink(missing_ok=True)
    with atomic_path(directory / f"{stem}.npz") as temporary:
        with ZipFile(temporary, "w", compression=ZIP_STORED, allowZip64=True) as archive:
            names = []
            count = 0
            for name, array in arrays:
                if len(names) >= len(ARRAYS) or name != ARRAYS[len(names)]:
                    raise ValueError("Invalid DEM state array names or order.")
                array = np.asarray(array)
                if name == "ids":
                    count = array.shape[0] if array.ndim == 1 else 0
                validate_particle_array(name, array, count, strict_dtype=True)
                names.append(name)
                with archive.open(name + ".npy", "w", force_zip64=True) as stream:
                    np.lib.format.write_array(stream, array, allow_pickle=False)
                del array
            if tuple(names) != ARRAYS:
                raise ValueError("Invalid DEM state array names or order.")
    atomic_json(metadata_path, {
        "schema": SCHEMA, "schema_version": VERSION, "units": "SI",
        "time": time, "box": box,
    })


def read_state(directory, stem="final_state"):
    """Read and validate a complete numeric state without pickle or solver imports."""
    directory = Path(directory)
    metadata = json.loads((directory / f"{stem}.json").read_text(encoding="utf-8"))
    if (not isinstance(metadata, dict)
            or metadata.get("schema") != SCHEMA or metadata.get("schema_version") != VERSION
            or metadata.get("units") != "SI"):
        raise ValueError("Unsupported DEM state exchange schema or units.")
    validate_state_metadata(metadata.get("time"), metadata.get("box"))
    with np.load(directory / f"{stem}.npz", allow_pickle=False) as archive:
        if len(archive.files) != len(ARRAYS) or set(archive.files) != set(ARRAYS):
            raise ValueError("Invalid state archive members.")
        arrays = {name: archive[name] for name in ARRAYS}
    validate_particle_arrays(arrays, strict_dtype=True)
    return dict(arrays, time=metadata["time"], box=metadata["box"])
