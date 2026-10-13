#!/usr/bin/env bash
# Submit a prepared pressure-cycle batch without copying JPGen again.
set -euo pipefail
if [[ $# -lt 1 ]]; then
    echo "Uso: bash scripts/acuario-submit-pressure-cycles.sh RUTA_LOTE [opciones sbatch]" >&2
    exit 2
fi
suite_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$suite_root"
batch=$1
shift
[[ -f $batch/batch.json ]] || { echo "No existe el lote: $batch" >&2; exit 2; }
if [[ -f SHA256SUMS ]]; then
    sha256sum -c SHA256SUMS >/dev/null
fi
export PYTHONPATH="$suite_root/src${PYTHONPATH:+:$PYTHONPATH}"
export JPGEN_PLACEMENT_BACKEND=native
export JPGEN_LIGGGHTS_LIBRARY=${JPGEN_LIGGGHTS_LIBRARY:-"$suite_root/.deps/LIGGGHTS-PUBLIC/src/libliggghts_serial.so"}
source scripts/acuario-env.sh
export JPGEN_ENV_READY=1
count=$("${JPGEN_PYTHON:-$HOME/jpgen-venv/bin/python}" - "$batch/batch.json" <<'PY'
import json, sys
with open(sys.argv[1]) as stream:
    count = json.load(stream)['count']
if type(count) is not int or count < 1:
    raise SystemExit('Invalid batch count')
print(count)
PY
)
sbatch --export=ALL --array="1-${count}%${count}" "$@" scripts/acuario-pressure-cycles.sbatch "$batch"
