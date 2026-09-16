"""Versioned, solver-independent HDF5 persistence."""

import json

import h5py

from .domain import Box, ParticleSet
from .validation import validate_particles


SCHEMA_VERSION = "2.0"
ARRAYS = ("ids", "positions", "radii", "velocities", "angular_velocities")
UNITS = {"ids": "1", "positions": "m", "radii": "m", "velocities": "m/s", "angular_velocities": "rad/s"}


def write_hdf5(path, particles, configuration):
    validate_particles(particles)
    with h5py.File(path, "w") as file:
        file.attrs.update(schema="JPGen.particles", schema_version=SCHEMA_VERSION, units="SI")
        group = file.create_group("particles")
        for name in ARRAYS:
            dataset = group.create_dataset(name, data=getattr(particles, name), compression="gzip", shuffle=True)
            dataset.attrs["units"] = UNITS[name]
        domain = file.create_group("domain")
        for name in ("origin", "lengths"):
            domain.create_dataset(name, data=getattr(particles.box, name)).attrs["units"] = "m"
        domain.attrs["periodic"] = particles.box.periodic
        generation = file.create_group("generation")
        generation.attrs["metadata_json"] = json.dumps(particles.metadata, sort_keys=True)
        generation.create_dataset("configuration_json", data=json.dumps(configuration, sort_keys=True), dtype=h5py.string_dtype())


def read_hdf5(path):
    with h5py.File(path, "r") as file:
        if file.attrs.get("schema") != "JPGen.particles" or file.attrs.get("schema_version") != SCHEMA_VERSION or file.attrs.get("units") != "SI":
            raise ValueError("Unsupported JPGen HDF5 schema or units.")
        arrays = {name: file[f"particles/{name}"][:] for name in ARRAYS}
        domain = file["domain"]
        box = Box(domain["origin"][:], domain["lengths"][:], bool(domain.attrs["periodic"]))
        metadata = json.loads(file["generation"].attrs["metadata_json"])
        configuration = json.loads(file["generation/configuration_json"].asstr()[()])
    particles = ParticleSet(**arrays, box=box, metadata=metadata)
    validate_particles(particles)
    return particles, configuration
