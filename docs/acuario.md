# Ejecutar JPGen en Acuario (CIMNE)

Acuario usa Slurm. Ejecuta las compilaciones y simulaciones en nodos de cálculo,
no en el nodo de acceso. Hemos comprobado que Acuario tiene glibc 2.17 y los
módulos `python/3.12.1` y `gcc/10.2.0`, además de Boost 1.78.0. El wheel Linux que se
ha construido en Ubuntu 24.04 (`manylinux_2_39_x86_64`) **no sirve** en
Acuario. Los pasos siguientes generan un wheel nativo para el
propio clúster. Incluye el Kratos modificado que requiere JPGen; el módulo
`kratos/daily` de Acuario no lo sustituye.

## 1. Copiar el código

Desde la raíz del repositorio local, empaqueta únicamente el código y los
scripts necesarios. No incluyas `Kratos/`, `.venv/`, `dist/` ni `runs/` locales:

```bash
mkdir -p dist
tar -czf dist/jpgen-source.tar.gz README.md pyproject.toml setup.py MANIFEST.in \
  LICENSE THIRD_PARTY_NOTICES.md src tools vendor scripts examples docs
scp dist/jpgen-source.tar.gz USUARIO@acuario.cimne.upc.edu:~/
bash scripts/acuario-download-deps.sh
scp -r dist/acuario-deps USUARIO@acuario.cimne.upc.edu:~/JPGen/
```

En Acuario:

```bash
mkdir -p ~/JPGen
tar -xzf ~/jpgen-source.tar.gz -C ~/JPGen
cd ~/JPGen
```

El Python 3.12 de Acuario no dispone del módulo `ssl`, por lo que sus comandos
`pip` no pueden acceder a PyPI. El script de descarga reúne los wheels para
CPython 3.12 y glibc 2.17 en una máquina con Internet. Si Git tampoco puede
acceder a GitHub desde Acuario, prepara el árbol `Kratos/` con
`tools/prepare_kratos_source.py` en otra máquina y transfiérelo incluyendo
su `.git`.

## 2. Preparar el entorno de compilación

En la sesión de Acuario, carga el entorno con el script incluido:

```bash
source scripts/acuario-env.sh
```

Deben aparecer `gcc/10.2.0` y `python/3.12.1` en `module list`, y `g++`
debe ser la versión 10.2.0. El módulo `boost/1.78.0` intenta cargar
`gcc/6.5.0` y provoca un conflicto; el script usa directamente las rutas que
declara ese modulefile. Si el script falla, detente y revisa su salida.

Solo entonces prepara el entorno y Kratos:

```bash
python3.12 -m venv ~/jpgen-build-venv
bash scripts/acuario-install-deps.sh
~/jpgen-build-venv/bin/python tools/prepare_kratos_source.py Kratos
```

El CMake publicado en Acuario es 3.13 y Kratos requiere 3.15 o superior; por
eso se instala CMake en el entorno virtual. La compilación necesita espacio de
disco para el checkout y los objetos C++: comprueba la cuota con `quota -s`
y el espacio con `df -h .`. El instalador usa `--no-index` y el directorio
`~/JPGen/acuario-deps/` copiado en el primer paso.

## 3. Compilar en un nodo

Con el entorno cargado mediante `source scripts/acuario-env.sh`, desde `~/JPGen`:

```bash
sbatch --partition=PARTICION scripts/acuario-build.sbatch
squeue -u "$USER"
```

Sustituye `PARTICION` por una partición de `sinfo`; omite la opción para la
predeterminada. Ajusta `--time`, `--mem` y `--cpus-per-task` si la compilación
lo necesita. El script usa cuatro CPU, 32 GB y seis horas por defecto. Los
mensajes aparecen en `jpgen-build-ID.out` y `jpgen-build-ID.err`. Si el trabajo
termina bien, deja el wheel en `dist/acuario-ID/`. Está construido para el
entorno de Acuario; no está preparado para distribuirlo como wheel `manylinux`
a otros sistemas.

## 4. Instalar y ejecutar

Tras una compilación correcta, desde `~/JPGen` instala el wheel nativo con
el script de instalación. Carga por sí mismo los módulos y usa el directorio de
wheels local, sin conexión a PyPI:

```bash
bash scripts/acuario-install.sh dist/acuario-ID/*.whl
```

Usa el ID real del trabajo de compilación. El instalador crea `~/jpgen-venv`,
comprueba dependencias y muestra las revisiones de JPGen y Kratos. Para usar
`jpgen` desde una terminal, carga el entorno después de instalar; el script
incluye `~/jpgen-venv/bin` en `PATH` cuando encuentra el ejecutable:

```bash
source scripts/acuario-env.sh
jpgen --help
```

Envía el ejemplo DEM corto al nodo de cálculo:

```bash
source scripts/acuario-env.sh
sbatch --time=00:10:00 scripts/acuario.sbatch examples/acuario_minimal.yaml
squeue -u "$USER"
```

El script [acuario.sbatch](../scripts/acuario.sbatch) ejecuta un proceso JPGen
en un nodo, deja `stdout`/`stderr` como `jpgen-ID.out` y `jpgen-ID.err`, y
escribe los resultados en `runs/` del directorio de envío. Los caminos
relativos del YAML también se resuelven desde ese directorio. Para DEM,
`dem.backend_options.threads` en el YAML controla los hilos de Kratos: reserva
al menos ese número con `--cpus-per-task`. El script aborta si el YAML pide más
CPU de las reservadas. JPGen no distribuye una simulación entre nodos.

```bash
sbatch --partition=PARTICION --time=04:00:00 --mem=16G --cpus-per-task=4 \
  scripts/acuario.sbatch mi_caso.yaml
```

El script usa `~/jpgen-venv/bin/python` por defecto. Si el entorno se instaló
en otro lugar, define `JPGEN_PYTHON` al enviar el trabajo; para otro directorio
de resultados define `JPGEN_OUTPUT_DIR`, por ejemplo:

```bash
sbatch --export=ALL,JPGEN_OUTPUT_DIR=/ruta/resultados \
  scripts/acuario.sbatch mi_caso.yaml
```

Revisa `jpgen-ID.out`, `jpgen-ID.err` y, para DEM,
`runs/<ejecución>/stages/dem/logs/`. El YAML efectivo queda en
`runs/<ejecución>/config/effective.yaml`, y el estado en `run.json`.

La [documentación de CIMNE](https://hpc.cimne.upc.edu/getting-started/) describe
el acceso, las particiones y las reservas de Slurm; comprueba con `sinfo` las
particiones actuales antes de enviar un trabajo.

## Verificación en Acuario

El 28 de septiembre de 2026 se ejecutó `examples/acuario_minimal.yaml` en el
nodo `pez045` (trabajo Slurm 267511). `summary.json` terminó con estado
`complete`: 2 partículas, 10 pasos DEM, tiempo final `0.0001 s`, y
`dem/results.h5` publicado. Se usó JPGen 0.5.0, Python 3.12.1 y la revisión
Kratos `64c7b4eb9b5e70ce6fbfbc304715e2ece28f6790`.
