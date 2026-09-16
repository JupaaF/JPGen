"""Coordinate one run; preserve the effective seed even when generation fails."""

import json
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np
import yaml

from . import __version__
from .configuration import validate_config
from .exporters.kratos import write_mdpa
from .exporters.vtk import write_vtp
from .generation import generate
from .persistence import read_hdf5, write_hdf5

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run(raw, report=print):
    """Run from the particle-generation section and save a CLI-compatible document."""
    cfg = validate_config(raw)
    runs = PROJECT_ROOT / "runs"
    runs.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ_")
    directory = Path(tempfile.mkdtemp(prefix=stamp, dir=runs))
    effective = {"particle_generation": cfg}
    (directory / "configuration.yaml").write_text(yaml.safe_dump(effective, sort_keys=False), encoding="utf-8")
    versions = {"jpgen_particle_generation": __version__, "python": platform.python_version(),
                "numpy": np.__version__, "h5py": h5py.__version__, "pyyaml": yaml.__version__}
    status = {"status": "running", "seed": cfg["seed"], "versions": versions}
    status_path = directory / "summary.json"

    def save_status():
        temporary = directory / "summary.json.tmp"
        temporary.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        temporary.replace(status_path)

    save_status()
    report(f"Run directory: {directory}")
    report(f"Random seed: {cfg['seed']}")
    try:
        particles = generate(cfg, report)
        particles.metadata["versions"] = versions
        # Export from the persisted representation, exercising the reader on every run.
        with tempfile.TemporaryDirectory(prefix=".output-", dir=directory) as staging:
            staging = Path(staging)
            write_hdf5(staging / "particles.h5", particles, effective)
            restored, _ = read_hdf5(staging / "particles.h5")
            write_mdpa(staging / "particlesDEM.mdpa", restored)
            write_vtp(staging / "particles.vtp", restored)
            for name in ("particles.h5", "particlesDEM.mdpa", "particles.vtp"):
                (staging / name).replace(directory / name)
        status.update(particles.metadata)
        status.update(status="complete", box_origin=particles.box.origin.tolist(), box_lengths=particles.box.lengths.tolist(),
                      periodic=particles.box.periodic)
        save_status()
        report(f"Generated {len(particles.ids)} particles; solid fraction: {particles.solid_fraction:.9g}")
        report(f"Saved HDF5, Kratos MDPA and VTK PolyData to {directory}")
        return directory
    except Exception as error:
        status.update(status="failed", error=str(error))
        save_status()
        raise
