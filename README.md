# JPGen

JPGen generates reproducible packings of 3D spheres in rectangular boxes and
optionally simulates them with a discrete element method (DEM) engine. Kratos
and LIGGGHTS are implemented backends; the physical case and protocol are owned by JPGen.
All physical quantities use SI units.

Release wheels include the C++17 placement kernels and the modified JPGen
Kratos Core/DEM runtime. No separate Kratos installation is needed. The current
release targets CPython 3.12 on Linux x86_64 and Windows x86_64.

LIGGGHTS is optional and installed separately. From a source checkout, build its
pinned Linux library with `python tools/build_liggghts.py --jobs 4`, then select
`dem.engine: liggghts`. The JPGen native extensions implement the portable
Hertz contact law and symplectic Euler integration; an ordinary upstream
LIGGGHTS library is rejected. See [LIGGGHTS setup and numerical comparison](docs/liggghts.md)
for configuration, capabilities and reproducible comparison commands.
The [14,089-particle comparison report](docs/liggghts-comparison-14089.md)
records measured differences against Kratos for the full 30 kPa protocol.

## Install and run

Before publication, download the wheel for your platform from the
[wheel build workflow](https://github.com/JupaaF/JPGen/actions/workflows/build-wheels.yml):

```bash
python -m pip install /path/to/jpgen-0.5.0-*.whl
jpgen
```

After publication, install with `python -m pip install jpgen`.
For the Acuario cluster at CIMNE, follow the [Acuario guide](docs/acuario.md).
For source builds and releases, see [packaging](docs/packaging.md).

In an interactive terminal, `jpgen` opens a Textual configuration wizard and
runs the selected pipeline. It can generate a packing or reuse a `packing.h5`,
collects physical inputs with selectable units, and previews the validated YAML
before saving it. If execution fails or is cancelled with Ctrl+C, a newly
created configuration is removed and a replaced configuration is restored.

To run an existing configuration:

```bash
jpgen config.yaml --output-dir runs
jpgen config.yaml --label compression --tag baseline --experiment pressure-sweep
jpgen config.yaml --progress logging
jpgen config.yaml --progress none
```

Console progress is enabled by default. Every run also records structured
events and a readable log. Programmatic callers use
`JPGenApplication.run(..., observer=...)`; omitting the observer is silent.

## Minimal configuration

Save this as `config.yaml` for a packing-only run:

```yaml
packing:
  sizing_method: fixed_count
  count: 100
  seed: 42
  exports: [vtk]
  box:
    origin_mode: minimum_corner
    lengths: [0.1, 0.1, 0.1]
    periodic: false
  radii: {type: uniform, min: 0.0005, max: 0.001}
  placement:
    method: random_sequential
    max_overlap: 0.0
    position_attempts: 1000
```

The root requires exactly one of `packing` or `packing_source`. Add `dem` to
enable simulation; omit it for packing only. Unknown options are rejected.
The [configuration reference](docs/configuration.md) describes distributions,
sizing, placement settings, DEM physics, stopping conditions and protocols.

## Supported features

- Fixed particle count, fixed-box solid fraction, or a box scaled to a target fraction.
- Constant, uniform, bounded normal and lognormal radii; explicit radii lists.
- Random sequential insertion, overlap relaxation and progressive growth.
- Open or periodic DEM boundaries, one particle material, Hertz viscous Coulomb contacts.
- Free evolution, strain-rate control, isotropic and anisotropic stress servos.
- Nested repeated protocols, equilibrated pressure paths and density continuation with rollback.
- HDF5 scientific outputs, optional VTK/MDPA packing exports, saved particle states and observables.

Geometric placement does not establish mechanical equilibrium. DEM success
means the configured stopping criteria were met. Walls, multiple materials,
adaptive time stepping and CLI resume are not implemented.

Wheels select the native placement kernels by default. Set
`JPGEN_PLACEMENT_BACKEND=python` for the Python implementation, or `native` to
require the compiled kernels. Both use the configured packing random streams.

## Results and run management

Each invocation creates a separate run under `runs/` or `--output-dir`:

```text
<run>/
  run.json                          # Identity, lifecycle and result availability
  artifacts.json                    # Published files and SHA-256 hashes
  config/{requested,effective}.yaml
  provenance/{environment,sources}.json
  stages/packing/{summary.json,results/packing.h5,exports/}
  stages/dem/                       # When DEM is configured
    summary.json
    results/{final.h5,observables.jsonl,states.jsonl,states/}
    execution/
    backend/<engine>/{input,native,checkpoints/}
    logs/
  logs/{events.jsonl,jpgen.log}
  view/                             # Regenerable JSON projections
```

Failed runs retain earlier results and diagnostic states. State readers validate
arrays, geometry, time and index references; incomplete state pairs are omitted
from listings. `--retention analysis` removes internal checkpoints after
execution while keeping scientific states, inputs and logs. The default
`--retention full` keeps checkpoints. Neither policy provides CLI resume.

```bash
jpgen runs list runs
jpgen runs show runs/<run>
jpgen runs compare runs/<first> runs/<second>
jpgen runs verify runs/<run> --deep
jpgen runs export runs/<run>
jpgen runs index runs
jpgen runs import /path/to/old-run --output-dir runs
```

Ordinary verification checks file hashes; `--deep` also validates HDF5 results,
NPZ/JSON states and their index references. After the original process has
stopped, `jpgen runs recover runs/<run>` reconciles an abandoned run.
Replay with `jpgen runs/<run>/config/effective.yaml`; imported packing references
resolve to the run's own snapshot. The [run-format contract](docs/run-format.md)
describes schemas, partial results, retention and comparison semantics.

## Development

The pipeline is composed in `src/jpgen/application.py`. Packing generation lives
in `src/jpgen/packing/`; solver-independent DEM physics and protocols live in
`src/jpgen/dem/`, with adapters under `dem/backends/{kratos,liggghts}/`.
`run_repository.py` publishes outputs, and `run_reader.py` provides queries and
browser projections. Shared particle and file-publication contracts are copied
into standalone Kratos cases, which run without importing JPGen.

See [backend extension contracts](docs/dem-backends.md),
[density continuation](docs/density-continuation-protocol.md), and
[building release wheels](docs/packaging.md). Source preparation reconstructs
the latest JPGen fork declared by the versioned base revision and patches; the
private fork does not need a public branch. Wheels record its exact revision.
