#!/usr/bin/env bash
# Ejecutar en una máquina Linux con Internet y Python 3.12.
set -euo pipefail
cd "$(dirname "$0")/.."
python3.12 -m pip download \
    --only-binary=:all: \
    --platform manylinux_2_17_x86_64 \
    --platform manylinux2014_x86_64 \
    --python-version 3.12 \
    --implementation cp \
    --abi cp312 --abi abi3 --abi none \
    --dest dist/acuario-deps \
    pip 'setuptools>=77' wheel 'pybind11>=2.12,<4' \
    'numpy>=1.24,<3' 'h5py>=3.8,<4' 'scipy>=1.10,<2' \
    'PyYAML>=6,<7' 'questionary>=2.1.1,<3' 'cmake>=3.15,<4'
