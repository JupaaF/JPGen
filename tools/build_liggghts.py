#!/usr/bin/env python3
"""Build single-process LIGGGHTS with JPGen physics and OpenMP extensions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

REVISION = "3d5c00f20519e6bb6eb6756f51f1ad36564e649d"


def prepare_sources(source, workspace, extensions, environment):
    """Export pinned inputs without local extras, overlays or cached objects."""
    archive = workspace / "upstream.tar"
    subprocess.run(["git", "archive", "--format=tar", f"--output={archive}",
                    REVISION, "src"], cwd=source, check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(workspace, filter="data")
    build = workspace / "src"
    hashes = {}
    for path in sorted(extensions.iterdir()):
        if path.suffix in {".cpp", ".h"}:
            contents = path.read_bytes()
            (build / path.name).write_bytes(contents)
            hashes[path.name] = hashlib.sha256(contents).hexdigest()
    (build / "style_contact_model_user.whitelist").write_text(
        "GRAN_MODEL(JPGEN_HERTZ, JPGEN_HISTORY, COHESION_OFF, ROLLING_OFF, SURFACE_DEFAULT)\n")
    makefile = (build / "MAKE/Makefile.serial").read_text()
    (build / "MAKE/Makefile.jpgen").write_text(
        makefile + "\nCCFLAGS += -fopenmp\nLINKFLAGS += -fopenmp\n")
    for name in ("Makefile.package", "Makefile.package.settings"):
        if not (build / name).exists():
            shutil.copyfile(build / f"{name}.empty", build / name)
    for command in (["bash", "Make.sh", "style"], ["bash", "Make.sh", "models"],
                    ["make", "makeshlib"]):
        subprocess.run(command, cwd=build, env=environment, check=True)
    # The export has no .git directory; retain the actual revision in the binary.
    version = build / "version_liggghts.h"
    version.write_text(version.read_text().replace("git commit unknown", f"git commit {REVISION}"))
    return build, hashes


def source_manifest(build):
    """Hash source and generated configuration inputs before compilation."""
    return {path.relative_to(build).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(build.rglob("*")) if path.is_file()}


def publish_library(built, library, metadata):
    """Stage both outputs on their destination filesystem before publishing."""
    with tempfile.TemporaryDirectory(prefix=".jpgen-publish-", dir=library.parent) as temporary:
        staged = Path(temporary) / library.name
        shutil.copyfile(built, staged)
        manifest = staged.with_suffix(".json")
        manifest.write_text(json.dumps(metadata, indent=2) + "\n")
        staged.replace(library)
        manifest.replace(library.with_suffix(".json"))


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
    environment = os.environ.copy()
    # Inherited make overrides could change the source list or build flags.
    for name in ("MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKEOVERRIDES", "MAKEFILES"):
        environment.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="jpgen-liggghts-") as temporary:
        build, hashes = prepare_sources(source, Path(temporary), extensions, environment)
        inputs = source_manifest(build)
        compiled = sorted(path.name for path in build.glob("*cpp") if path.name != "main.cpp")
        compiled.append("STUBS/mpi.c")
        for command in (["make", "stubs"],
                        ["make", "-f", "Makefile.shlib", f"-j{args.jobs}", "jpgen"]):
            subprocess.run(command, cwd=build, env=environment, check=True)
        built = build / "liblmp_jpgen.so"
        library = source / "src/libliggghts_serial.so"
        metadata = {"revision": revision, "extensions": hashes,
                    "source_files": inputs, "compiled_sources": compiled,
                    "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
                    "compile_flags": "-O2 -fPIC -fopenmp", "link_flags": "-O2 -fPIC -shared -fopenmp",
                    "contact_history_version": 2,
                    "library_sha256": hashlib.sha256(built.read_bytes()).hexdigest(),
                    "mpi": False, "openmp": True, "jpgen_liggghts_api": 5}
        publish_library(built, library, metadata)
    print(f"LIGGGHTS library: {library}")


if __name__ == "__main__":
    main()
