"""Optional native kernels; packaging metadata remains in pyproject.toml."""

import os
import sys

from pybind11.setup_helpers import Pybind11Extension
from setuptools import setup


extensions = []
if os.environ.get("JPGEN_BUILD_NATIVE", "1") != "0":
    extensions.append(Pybind11Extension(
        "jpgen.packing.placement._kernels",
        ["src/jpgen/packing/placement/_kernels.cpp"],
        cxx_std=17,
        # Keep NumPy's operation order: no reassociation or fused multiply-add.
        extra_compile_args=(["/O2", "/fp:strict"] if sys.platform == "win32"
                            else ["-O3", "-fno-fast-math", "-ffp-contract=off"]),
        optional=True,
    ))

setup(ext_modules=extensions)
