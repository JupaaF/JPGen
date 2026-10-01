"""Common scientific particle datasets in JPGen HDF5 stores."""

from .particle_data import ARRAYS, UNITS, validate_particle_arrays


def read_particles(file):
    arrays = {}
    for name in ARRAYS:
        dataset = file[f"particles/{name}"]
        if dataset.attrs.get("units") != UNITS[name]:
            raise ValueError(f"Invalid HDF5 particle units: {name}.")
        arrays[name] = dataset[:]
    validate_particle_arrays(arrays)
    return arrays


def read_geometry(domain):
    for name in ("origin", "lengths"):
        if domain[name].attrs.get("units") != "m":
            raise ValueError(f"Invalid HDF5 domain units: {name}.")
    return domain["origin"][:], domain["lengths"][:]
