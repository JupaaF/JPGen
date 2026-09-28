#!/usr/bin/env bash
#SBATCH --job-name=jpgen
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=01:00:00
#SBATCH --output=jpgen-%j.out
#SBATCH --error=jpgen-%j.err

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Uso: sbatch [opciones] scripts/acuario.sbatch configuracion.yaml" >&2
    exit 2
fi

cd "${SLURM_SUBMIT_DIR:?Este script debe ejecutarse mediante sbatch}"

# El módulo boost/1.78.0 intenta cargar gcc/6.5.0. Usamos sus rutas
# directamente para conservar gcc/10.2.0 en compilación y ejecución.
export BOOST_ROOT=${BOOST_ROOT:-/globalfs/opt/boost/1.78.0}
if [[ ! -f $BOOST_ROOT/include/boost/version.hpp ]]; then
    echo "No se encuentran las cabeceras de Boost en $BOOST_ROOT" >&2
    exit 2
fi
export LD_LIBRARY_PATH="$BOOST_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
config=$1
python=${JPGEN_PYTHON:-"$HOME/jpgen-venv/bin/python"}
output_dir=${JPGEN_OUTPUT_DIR:-"$PWD/runs"}

if [[ ! -f $config ]]; then
    echo "No existe la configuración: $config" >&2
    exit 2
fi
if [[ ! -x $python ]]; then
    echo "No existe Python ejecutable: $python (define JPGEN_PYTHON)" >&2
    exit 2
fi

# Kratos usa dem.backend_options.threads; evitar exceder la reserva de Slurm.
"$python" - "$config" "${SLURM_CPUS_PER_TASK:-1}" <<'PY'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as stream:
    config = yaml.safe_load(stream)
if isinstance(config, dict) and isinstance(config.get("dem"), dict):
    options = config["dem"].get("backend_options") or {}
    if isinstance(options, dict):
        threads = options.get("threads", 1)
        if isinstance(threads, int) and threads > int(sys.argv[2]):
            sys.exit(
                f"dem.backend_options.threads={threads} excede los "
                f"{sys.argv[2]} CPU reservados; usa sbatch --cpus-per-task={threads}"
            )
PY

export PYTHONNOUSERSITE=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-1}

mkdir -p "$output_dir"
echo "JPGen: $("$python" --version), nodo ${SLURMD_NODENAME:-desconocido}, configuración $config"
echo "Resultados: $output_dir"
srun "$python" -m jpgen "$config" --output-dir "$output_dir" --progress logging
