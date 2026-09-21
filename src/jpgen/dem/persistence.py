"""Versioned common DEM results, separate from packing and native checkpoints."""

import json
from dataclasses import asdict
from typing import Protocol

import h5py
import numpy as np

from .domain import DemState
from ..packing.domain.box import Box


UNITS = {"ids": "1", "positions": "m", "radii": "m", "velocities": "m/s", "angular_velocities": "rad/s"}


class DemResultStore(Protocol):
    filename: str

    def save(self, path, state, case, configuration, report) -> None: ...


class Hdf5DemResultStore:
    filename = "results.h5"

    def save(self, path, state, case, configuration, report):
        with h5py.File(path, "w") as file:
            file.attrs.update(schema="JPGen.dem", schema_version="1.1", units="SI",
                              time=state.time, time_units="s")
            particles = file.create_group("particles")
            for name, unit in UNITS.items():
                particles.create_dataset(name, data=getattr(state, name), compression="gzip", shuffle=True).attrs["units"] = unit
            particles.create_dataset("material_ids", data=np.ones(len(state.ids), dtype=np.int64)).attrs["units"] = "1"
            domain = file.create_group("initial_domain")
            for name in ("origin", "lengths"):
                domain.create_dataset(name, data=getattr(case.packing.box, name)).attrs["units"] = "m"
            domain.attrs["boundary"] = case.boundary
            current = file.create_group("final_domain")
            box = state.box or case.packing.box
            for name in ("origin", "lengths"):
                current.create_dataset(name, data=getattr(box, name)).attrs["units"] = "m"
            current.attrs["boundary"] = case.boundary
            for name, value in (("configuration", configuration), ("execution", asdict(report))):
                file.create_dataset(name + "_json", data=json.dumps(value, sort_keys=True), dtype=h5py.string_dtype())

    def load(self, path):
        with h5py.File(path, "r") as file:
            if file.attrs.get("schema") != "JPGen.dem" or file.attrs.get("schema_version") not in ("1.0", "1.1") or file.attrs.get("units") != "SI":
                raise ValueError("Unsupported JPGen DEM result schema or units.")
            domain = file["final_domain"] if file.attrs["schema_version"] == "1.1" else file["initial_domain"]
            box = Box(domain["origin"][:], domain["lengths"][:], domain.attrs["boundary"] == "periodic")
            state = DemState(**{name: file[f"particles/{name}"][:] for name in UNITS}, time=float(file.attrs["time"]), box=box)
            return state, json.loads(file["configuration_json"].asstr()[()])
