"""Versioned common DEM results, separate from packing and native checkpoints."""

import json
from dataclasses import asdict
from typing import Protocol

import h5py
import numpy as np

from .domain import DemState
from ..packing.domain.box import Box
from ..particle_data import UNITS
from ..hdf5_io import read_particles, read_geometry


class DemResultStore(Protocol):
    filename: str

    def save(self, path, state, case, configuration, report) -> None: ...


class Hdf5DemResultStore:
    filename = "final.h5"

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
            if file.attrs.get("time_units") != "s":
                raise ValueError("Invalid DEM time units.")
            domain = file["final_domain"] if file.attrs["schema_version"] == "1.1" else file["initial_domain"]
            boundary = domain.attrs["boundary"]
            if boundary not in {"open", "periodic"} or file["initial_domain"].attrs["boundary"] != boundary:
                raise ValueError("Invalid or inconsistent DEM boundaries.")
            Box(*read_geometry(file["initial_domain"]), boundary == "periodic")
            box = Box(*read_geometry(domain), boundary == "periodic")
            state = DemState(**read_particles(file), time=file.attrs["time"], box=box)
            configuration = json.loads(file["configuration_json"].asstr()[()])
            execution = json.loads(file["execution_json"].asstr()[()])
            if not isinstance(configuration, dict) or not isinstance(execution, dict):
                raise ValueError("DEM configuration and execution report must be mappings.")
            return state, configuration
