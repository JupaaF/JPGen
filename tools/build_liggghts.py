#!/usr/bin/env python3
"""Build single-process LIGGGHTS with JPGen physics and OpenMP extensions."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

REVISION = "3d5c00f20519e6bb6eb6756f51f1ad36564e649d"

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(".deps/LIGGGHTS-PUBLIC"))
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    source = args.source.resolve()
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "https://github.com/CFDEMproject/LIGGGHTS-PUBLIC.git", str(source)], check=True)
        subprocess.run(["git", "checkout", REVISION], cwd=source, check=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if revision != REVISION:
        parser.error(f"Expected LIGGGHTS revision {REVISION}, got {revision}")
    if subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=source).returncode:
        parser.error("LIGGGHTS tracked sources have local changes; use a clean pinned checkout")
    extensions = Path(__file__).resolve().parents[1] / "vendor/liggghts"
    hashes = {}
    for path in sorted(extensions.iterdir()):
        if path.suffix in {".cpp", ".h"}:
            destination = source / "src" / path.name
            if not destination.exists() or destination.read_bytes() != path.read_bytes():
                shutil.copyfile(path, destination)
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (source / "src/style_contact_model_user.whitelist").write_text(
        "GRAN_MODEL(JPGEN_HERTZ, JPGEN_HISTORY, COHESION_OFF, ROLLING_OFF, SURFACE_DEFAULT)\n")
    makefile = (source / "src/MAKE/Makefile.serial").read_text()
    (source / "src/MAKE/Makefile.jpgen").write_text(
        makefile + "\nCCFLAGS += -fopenmp\nLINKFLAGS += -fopenmp\n")
    for command in (["bash", "Make.sh", "style"], ["bash", "Make.sh", "models"],
                    ["make", "stubs"], ["make", "makeshlib"],
                    ["make", "-f", "Makefile.shlib", f"-j{args.jobs}", "jpgen"]):
        subprocess.run(command, cwd=source / "src", check=True)
    library = source / "src/libliggghts_serial.so"
    temporary = library.with_suffix(".so.tmp")
    shutil.copyfile(source / "src/liblmp_jpgen.so", temporary)
    temporary.replace(library)
    metadata = {"revision": revision, "extensions": hashes,
                "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
                "mpi": False, "openmp": True, "jpgen_liggghts_api": 3}
    library.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"LIGGGHTS library: {library}")

if __name__ == "__main__":
    main()
