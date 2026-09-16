#!/usr/bin/env bash

# Source this file to activate the project venv and its local Kratos build:
#   source ./activate_kratos.sh

_jpgen_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export KRATOS_ROOT="${_jpgen_root}/Kratos"
export KRATOS_INSTALL="${KRATOS_ROOT}/bin/Release"

if [[ ! -f "${_jpgen_root}/.venv/bin/activate" ]]; then
    echo "Project virtual environment not found at ${_jpgen_root}/.venv" >&2
    unset _jpgen_root
    return 1 2>/dev/null || exit 1
fi

if [[ ! -f "${KRATOS_INSTALL}/KratosMultiphysics/__init__.py" ]]; then
    echo "Local Kratos installation not found at ${KRATOS_INSTALL}" >&2
    unset _jpgen_root
    return 1 2>/dev/null || exit 1
fi

source "${_jpgen_root}/.venv/bin/activate"
export PYTHONPATH="${KRATOS_INSTALL}${PYTHONPATH:+:${PYTHONPATH}}"
export LD_LIBRARY_PATH="${KRATOS_INSTALL}/libs${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

unset _jpgen_root
