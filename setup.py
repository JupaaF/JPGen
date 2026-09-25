"""Build JPGen with its C++ placement kernels and pinned Kratos DEM runtime."""

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from pybind11.setup_helpers import Pybind11Extension
from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
KRATOS_REVISION = (ROOT / "vendor/kratos-revision.txt").read_text(encoding="utf-8").strip()


def _shared_library(source: Path, stem: str) -> Path:
    suffixes = (".so", ".dylib", ".dll")
    matches = [
        path for path in source.iterdir()
        if path.is_file() and path.name.startswith(stem + ".")
        and any(path.name.endswith(suffix) or suffix + "." in path.name for suffix in suffixes)
    ]
    if not matches:
        raise RuntimeError(f"Required Kratos library is missing: {stem}")
    return max(matches, key=lambda path: path.stat().st_size)


class BuildWithKratos(build_py):
    def run(self):
        super().run()
        source = Path(os.environ.get("JPGEN_KRATOS_SOURCE", ROOT / "Kratos")).resolve()
        install = Path(os.environ.get("JPGEN_KRATOS_INSTALL", source / "bin/Release")).resolve()
        try:
            revision = subprocess.check_output(
                ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
            ).strip()
        except (OSError, subprocess.CalledProcessError) as error:
            raise RuntimeError(
                "The pinned Kratos fork is required to build a JPGen wheel. "
                "See docs/packaging.md."
            ) from error
        if revision != KRATOS_REVISION:
            raise RuntimeError(
                f"Kratos revision {revision} does not match the pinned {KRATOS_REVISION}"
            )
        if subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain"], text=True
        ).strip():
            raise RuntimeError("Kratos has uncommitted source changes.")

        python_package = install / "KratosMultiphysics"
        libraries = install / "libs"
        if not (python_package / "__init__.py").is_file() or not libraries.is_dir():
            raise RuntimeError(f"Kratos DEM installation is incomplete: {install}")
        extension_suffix = sysconfig.get_config_var("EXT_SUFFIX")
        if not extension_suffix:
            raise RuntimeError("Cannot determine the current Python extension suffix.")

        destination = Path(self.build_lib) / "jpgen" / "_kratos_runtime"
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        shutil.copytree(
            python_package,
            destination / "KratosMultiphysics",
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        output_libraries = destination / "libs"
        output_libraries.mkdir()
        for stem in ("Kratos", "KratosDEMApplication"):
            candidates = (
                libraries / f"{stem}{extension_suffix}",
                libraries / f"{stem}.pyd",
                libraries / f"{stem}.so",
            )
            module = next((path for path in candidates if path.is_file()), None)
            if module is None:
                raise RuntimeError(
                    f"Kratos module is missing for this Python: {stem}{extension_suffix}"
                )
            shutil.copy2(module, output_libraries / module.name)
        for name in ("KratosCore", "KratosDEMCore"):
            stems = (f"lib{name}", name) if os.name == "nt" else (f"lib{name}",)
            library = None
            for stem in stems:
                try:
                    library = _shared_library(libraries, stem)
                    break
                except RuntimeError:
                    continue
            if library is None:
                raise RuntimeError(f"Required Kratos library is missing: {name}")
            shutil.copy2(library, output_libraries / library.name)
        for name, path in (
            ("KRATOS-CORE-LICENSE.txt", source / "kratos/license.txt"),
            ("KRATOS-DEM-LICENSE.txt", source / "applications/DEMApplication/license.txt"),
            ("KRATOS-ZLIB-NOTICE.txt", source / "external_libraries/zlib/README"),
        ):
            shutil.copy2(path, destination / name)
        (destination / "KRATOS-REVISION").write_text(revision + "\n", encoding="utf-8")
        if sys.platform.startswith("linux"):
            notice = Path("/usr/share/doc/libgomp1/copyright")
            gpl = Path("/usr/share/common-licenses/GPL-3")
            if notice.is_file() and gpl.is_file():
                shutil.copy2(notice, destination / "GCC-LIBGOMP-NOTICE.txt")
                shutil.copy2(gpl, destination / "GPL-3.0.txt")
        symlinks = [str(path) for path in destination.rglob("*") if path.is_symlink()]
        if symlinks:
            raise RuntimeError(f"Kratos runtime contains symlinks: {symlinks[:3]}")


extensions = [
    Pybind11Extension(
        "jpgen.packing.placement._kernels",
        ["src/jpgen/packing/placement/_kernels.cpp"],
        cxx_std=17,
        extra_compile_args=(
            ["/O2", "/fp:strict"]
            if sys.platform == "win32"
            else ["-O3", "-fno-fast-math", "-ffp-contract=off"]
        ),
    )
]

setup(ext_modules=extensions, cmdclass={"build_py": BuildWithKratos})
