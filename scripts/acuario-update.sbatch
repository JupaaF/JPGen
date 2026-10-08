#!/usr/bin/env bash
#SBATCH --job-name=jpgen-update
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --output=jpgen-update-%j.out
#SBATCH --error=jpgen-update-%j.err

# Compilar el paquete preparado e instalarlo en el entorno habitual de Acuario.
set -euo pipefail
# Slurm copia el script a su spool; la raíz real es el directorio de envío.
root=${SLURM_SUBMIT_DIR:?Este script debe ejecutarse mediante sbatch}
cd "$root"
source scripts/acuario-env.sh

# Conservar una copia recuperable de la versión instalada antes de actualizar.
backup="$HOME/jpgen-venv-backup-${SLURM_JOB_ID}"
if [[ -d $HOME/jpgen-venv ]]; then
    cp -a "$HOME/jpgen-venv" "$backup"
    echo "Copia del entorno anterior: $backup"
fi

export JPGEN_BUILD_PYTHON="$root/build-venv/bin/python"
export JPGEN_WHEELHOUSE="$root/acuario-deps"
python3.12 -m venv "$root/build-venv"
bash scripts/acuario-install-deps.sh

# El Git antiguo de Acuario solo admite formato 0. Un repositorio SHA-1 sin
# extensiones puede usarlo sin cambiar sus objetos, su índice ni su revisión.
"$JPGEN_BUILD_PYTHON" - <<'PY'
import configparser
from pathlib import Path

path = Path("Kratos/.git/config")
config = configparser.RawConfigParser()
config.read_string(path.read_text())
version = config.getint("core", "repositoryformatversion")
if version == 1:
    if config.has_section("extensions"):
        raise SystemExit("Kratos usa extensiones de Git; no se puede convertir a formato 0.")
    config.set("core", "repositoryformatversion", "0")
    with path.open("w") as stream:
        config.write(stream)
    print("Metadatos de Kratos adaptados al Git de Acuario (formato 0).")
PY
bash scripts/acuario-build.sbatch

shopt -s nullglob
wheels=("$root/dist/acuario-${SLURM_JOB_ID}/"jpgen-*.whl)
if [[ ${#wheels[@]} -ne 1 ]]; then
    echo "Se esperaba exactamente un wheel después de compilar" >&2
    exit 1
fi
bash scripts/acuario-install.sh "${wheels[0]}"
"$HOME/jpgen-venv/bin/jpgen" --help
echo "Actualización completada; código y wheel conservados en $root"
