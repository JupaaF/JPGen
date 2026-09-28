#!/usr/bin/env bash
# Cargar con: source scripts/acuario-env.sh

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    echo "Este archivo debe cargarse con: source scripts/acuario-env.sh" >&2
    exit 2
fi

if ! type module >/dev/null 2>&1; then
    echo "No está disponible el comando module en esta sesión" >&2
    return 1
fi
module purge || return 1
module load gcc/10.2.0 || return 1
module load python/3.12.1 || return 1

# boost/1.78.0 intenta cargar gcc/6.5.0; basta con sus rutas.
export BOOST_ROOT=/globalfs/opt/boost/1.78.0
if [[ ! -f $BOOST_ROOT/include/boost/version.hpp ]]; then
    echo "No se encuentran las cabeceras de Boost en $BOOST_ROOT" >&2
    return 1
fi
export LD_LIBRARY_PATH="$BOOST_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# La instalación crea el comando en un venv que no está en el PATH del shell.
jpgen_bin=$(dirname "${JPGEN_PYTHON:-$HOME/jpgen-venv/bin/python}")
if [[ -x $jpgen_bin/jpgen ]]; then
    case ":$PATH:" in
        *":$jpgen_bin:"*) ;;
        *) export PATH="$jpgen_bin:$PATH" ;;
    esac
fi
unset jpgen_bin

module list
python3.12 --version
g++ --version | head -1
echo "Boost: $BOOST_ROOT"
