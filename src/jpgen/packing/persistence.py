"""Versioned, solver-independent HDF5 packing persistence."""

import json
from typing import Protocol

import h5py

from .domain import Box, PackingMetadata, ParticlePacking


SCHEMA_VERSION = "3.0"
ARRAYS = ("ids", "positions", "radii", "velocities", "angular_velocities")
UNITS = {"ids": "1", "positions": "m", "radii": "m", "velocities": "m/s", "angular_velocities": "rad/s"}


class PackingStore(Protocol):
    filename: str

    def save(self, path, packing, configuration) -> None:
        """Persist a packing and its effective configuration."""

    def load(self, path):
        """Restore a packing and its effective configuration."""


class Hdf5PackingStore:
    """Persistence adapter used by the application service."""

    filename = "packing.h5"

    def save(self, path, packing, configuration):
        packing.validate()
        with h5py.File(path, "w") as file:
            file.attrs.update(schema="JPGen.packing", schema_version=SCHEMA_VERSION, units="SI")
            group = file.create_group("particles")
            for name in ARRAYS:
                dataset = group.create_dataset(name, data=getattr(packing, name), compression="gzip", shuffle=True)
                dataset.attrs["units"] = UNITS[name]
            domain = file.create_group("domain")
            for name in ("origin", "lengths"):
                domain.create_dataset(name, data=getattr(packing.box, name)).attrs["units"] = "m"
            domain.attrs["periodic"] = packing.box.periodic
            packing_group = file.create_group("packing")
            packing_group.attrs["metadata_json"] = json.dumps(packing.metadata.to_dict(), sort_keys=True)
            packing_group.create_dataset(
                "configuration_json",
                data=json.dumps(configuration, sort_keys=True),
                dtype=h5py.string_dtype(),
            )

    def load(self, path):
        with h5py.File(path, "r") as file:
            if file.attrs.get("schema") != "JPGen.packing" or file.attrs.get("schema_version") != SCHEMA_VERSION or file.attrs.get("units") != "SI":
                raise ValueError("Unsupported JPGen HDF5 schema or units.")
            arrays = {name: file[f"particles/{name}"][:] for name in ARRAYS}
            domain = file["domain"]
            box = Box(domain["origin"][:], domain["lengths"][:], bool(domain.attrs["periodic"]))
            metadata = PackingMetadata.from_dict(json.loads(file["packing"].attrs["metadata_json"]))
            configuration = json.loads(file["packing/configuration_json"].asstr()[()])
        packing = ParticlePacking(**arrays, box=box, metadata=metadata)
        packing.validate()
        return packing, configuration
