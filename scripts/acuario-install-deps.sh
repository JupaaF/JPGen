#!/usr/bin/env bash
# Instalar en Acuario sin acceso HTTPS desde Python.
set -euo pipefail
python=${JPGEN_BUILD_PYTHON:-"$HOME/jpgen-build-venv/bin/python"}
wheelhouse=${JPGEN_WHEELHOUSE:-"$HOME/JPGen/acuario-deps"}
if [[ ! -x $python ]]; then
    echo "No existe Python ejecutable: $python" >&2
    exit 2
fi
if [[ ! -d $wheelhouse ]]; then
    echo "No existe el directorio de wheels: $wheelhouse" >&2
    exit 2
fi
"$python" -m pip install --no-index --find-links "$wheelhouse" \
    --only-binary=:all: --upgrade \
    pip 'setuptools>=77' wheel 'pybind11>=2.12,<4' \
    'numpy>=1.24,<3' 'h5py>=3.8,<4' 'scipy>=1.10,<2' \
    'PyYAML>=6,<7' 'textual>=8.2.8,<9' 'cmake>=3.15,<4'
"$python" -m pip check
"$(dirname "$python")/cmake" --version
