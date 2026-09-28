#!/usr/bin/env bash
#SBATCH --job-name=jpgen-build
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --output=jpgen-build-%j.out
#SBATCH --error=jpgen-build-%j.err

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Este script debe ejecutarse mediante sbatch}"

# El módulo boost/1.78.0 intenta cargar gcc/6.5.0. Usamos sus rutas
# directamente para conservar gcc/10.2.0 en compilación y ejecución.
export BOOST_ROOT=${BOOST_ROOT:-/globalfs/opt/boost/1.78.0}
if [[ ! -f $BOOST_ROOT/include/boost/version.hpp ]]; then
    echo "No se encuentran las cabeceras de Boost en $BOOST_ROOT" >&2
    exit 2
fi
export LD_LIBRARY_PATH="$BOOST_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

python=${JPGEN_BUILD_PYTHON:-"$HOME/jpgen-build-venv/bin/python"}
source_dir=${JPGEN_KRATOS_SOURCE:-"$PWD/Kratos"}
if [[ ! -x $python ]]; then
    echo "No existe Python ejecutable: $python (define JPGEN_BUILD_PYTHON)" >&2
    exit 2
fi
if [[ ! -d $source_dir/.git ]]; then
    echo "No existe el código preparado de Kratos: $source_dir" >&2
    exit 2
fi

export PATH="$(dirname "$python"):$PATH"
wheel_dir="$PWD/dist/acuario-${SLURM_JOB_ID}"
mkdir -p "$wheel_dir"

"$python" tools/build_release_wheel.py \
    --source "$source_dir" \
    --parallel "${SLURM_CPUS_PER_TASK:-4}" \
    --wheel-dir "$wheel_dir"
printf 'Wheel para Acuario: %s\n' "$wheel_dir"/*.whl
