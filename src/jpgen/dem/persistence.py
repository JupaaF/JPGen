"""Versioned common DEM results, separate from packing and native checkpoints."""

import json
from dataclasses import asdict

import h5py
import numpy as np

from .domain import DemState


UNITS = {"ids": "1", "positions": "m", "radii": "m", "velocities": "m/s", "angular_velocities": "rad/s"}


class Hdf5DemResultStore:
    filename = "results.h5"

    def save(self, path, state, case, configuration, report):
        with h5py.File(path, "w") as file:
            file.attrs.update(schema="JPGen.dem", schema_version="1.0", units="SI",
                              time=state.time, time_units="s")
            particles = file.create_group("particles")
            for name, unit in UNITS.items():
                particles.create_dataset(name, data=getattr(state, name), compression="gzip", shuffle=True).attrs["units"] = unit
            particles.create_dataset("material_ids", data=np.ones(len(state.ids), dtype=np.int64)).attrs["units"] = "1"
            domain = file.create_group("initial_domain")
            for name in ("origin", "lengths"):
                domain.create_dataset(name, data=getattr(case.packing.box, name)).attrs["units"] = "m"
            domain.attrs["boundary"] = case.boundary
            for name, value in (("configuration", configuration), ("execution", asdict(report))):
                file.create_dataset(name + "_json", data=json.dumps(value, sort_keys=True), dtype=h5py.string_dtype())

    def load(self, path):
        with h5py.File(path, "r") as file:
            if (file.attrs.get("schema"), file.attrs.get("schema_version"), file.attrs.get("units")) != ("JPGen.dem", "1.0", "SI"):
                raise ValueError("Unsupported JPGen DEM result schema or units.")
            state = DemState(**{name: file[f"particles/{name}"][:] for name in UNITS}, time=float(file.attrs["time"]))
            return state, json.loads(file["configuration_json"].asstr()[()])
