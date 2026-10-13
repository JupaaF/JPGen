#!/usr/bin/env bash
#SBATCH --job-name=jpgen-cycles
#SBATCH --partition=R640
#SBATCH --array=1-10%10
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=2-00:00:00
#SBATCH --output=jpgen-cycles-%A_%a.out
#SBATCH --error=jpgen-cycles-%A_%a.err

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Este script debe enviarse mediante sbatch}"
# The submission helper exports the loaded environment. Avoid calling the
# login node's exported module function on compute nodes lacking modulecmd.
if [[ ${JPGEN_ENV_READY:-0} != 1 ]]; then
    source scripts/acuario-env.sh
fi
if [[ $# -ne 1 ]]; then
    echo "Uso: sbatch scripts/acuario-pressure-cycles.sbatch RUTA_LOTE" >&2
    exit 2
fi
batch=$1
suite_python=${JPGEN_PYTHON:-"$HOME/jpgen-venv/bin/python"}
printf -v config '%s/configs/run_%04d.yaml' "$batch" "${SLURM_ARRAY_TASK_ID:?}"
printf -v output '%s/results/run_%04d' "$batch" "$SLURM_ARRAY_TASK_ID"
[[ -f $config ]] || { echo "No existe $config" >&2; exit 2; }
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1
export SLURM_CPU_BIND=cores
echo "Simulación $SLURM_ARRAY_TASK_ID en ${SLURMD_NODENAME:-desconocido}: $config"
exec srun --nodes=1 --ntasks=1 --cpus-per-task=1 \
    "$suite_python" -u -m jpgen "$config" --output-dir "$output" \
    --label "cycles_$SLURM_ARRAY_TASK_ID" --experiment pressure_cycles --progress logging
