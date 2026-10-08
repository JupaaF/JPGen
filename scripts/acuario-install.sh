#!/usr/bin/env bash
# Instalar el wheel nativo construido en Acuario.
set -euo pipefail
if [[ $# -ne 1 || ! -f $1 ]]; then
    echo "Uso: bash scripts/acuario-install.sh dist/acuario-ID/jpgen-*.whl" >&2
    exit 2
fi
wheel=$1
root=$(cd "$(dirname "$0")/.." && pwd)
source "$root/scripts/acuario-env.sh"
python3.12 -m venv "$HOME/jpgen-venv"
python="$HOME/jpgen-venv/bin/python"
"$python" -m pip install --no-index --find-links "$root/acuario-deps" --force-reinstall --no-deps "$wheel"
"$python" -m pip install --no-index --find-links "$root/acuario-deps" "$wheel"
"$python" -m pip check
"$python" - <<'PY'
import jpgen
from jpgen.kratos_runtime import bundled_revision
print(f"JPGen {jpgen.__version__}; Kratos {bundled_revision()}")
PY
