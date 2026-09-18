# JPGen

JPGen is a particle simulation pipeline. It creates reproducible packings of 3D spheres in axis-aligned rectangular boxes and optionally simulates them with a DEM engine. Kratos is the first implemented engine; the DEM stage uses an engine-independent case and backend contract. All physical quantities use SI units. Packing generation and export do not require a Kratos installation.

```bash
python -m pip install -e .
jpgen examples/fixed_count.yaml
```

The CLI prints progress directly by default. Select standard-library logging or
disable progress output without changing the reproducible YAML configuration:

```bash
jpgen examples/fixed_count.yaml --progress logging
jpgen examples/fixed_count.yaml --progress none
```

The `logging` mode writes to standard error and to `jpgen.log` inside the
created run directory. The file handler is closed when the run completes or
fails.

Programmatic callers can pass any `ProgressObserver` to
`JPGenApplication.run(..., observer=...)`; omitting it is silent. The CLI alone
chooses `ConsoleProgressObserver` as its default.

Installation builds optional C++17 placement kernels when a compiler is
available. They accelerate contact evaluation and sequential insertion while
keeping NumPy's random stream and the existing placement configuration. Without
the extension, JPGen uses the Python implementation. After editing the C++
source, rerun the installation command to rebuild it.

For an explicitly Python-only build, set `JPGEN_BUILD_NATIVE=0` when installing.
At runtime, `JPGEN_PLACEMENT_BACKEND=python` forces Python and
`JPGEN_PLACEMENT_BACKEND=native` requires the compiled extension; the default
`auto` uses it when installed. See the
[profiling study and dense packing captures](docs/placement-performance.md)
for measurements and reproducibility commands.

Run `jpgen` without a file in an interactive terminal to create a complete YAML
configuration with the guided wizard and immediately execute it. The wizard can
generate a new packing or reuse an existing `packing.h5`, asks which optional
packing formats to export, explains every value, accepts selectable input units,
converts physical values to SI, validates the complete configuration and shows a
preview before saving. It writes a timestamped `.yaml` file in the current
directory by default. If generation fails, a newly created file is removed or a
replaced file is restored.

Each invocation creates a unique directory under `runs/`:

- `configuration.yaml`: normalized pipeline configuration, defaults and actual seed; usable for replay.
- `summary.json`: run status, dependency versions, final box and packing statistics.
- `packing.h5`: versioned packing dataset with geometry, initial velocities, configuration and metadata.
- `particlesDEM.mdpa`: optional Kratos packing export, produced by `exports: [kratos]`.
- `particles.vtp`: optional VTK XML PolyData, produced by `exports: [vtk]`.

When DEM is enabled, `dem/input/` contains the runnable engine case,
`dem/logs/` captures the solver output, `dem/native_results/` retains native
artifacts and `dem/results.h5` stores the validated final particle state.

Invalid configuration or an unavailable DEM runtime fails before a run directory is created. Packing failures return a nonzero exit code and preserve the effective configuration, seed and error. Packing outputs are published only after generation and HDF5 readback succeed. A DEM failure preserves the completed packing, case inputs and solver logs, and marks only DEM as failed. Existing runs are never overwritten. Replay with `jpgen runs/<run>/configuration.yaml`.

## Pipeline boundaries

`src/` is the source root and `src/jpgen/` is the Python package. The package is organized around the complete pipeline rather than treating packing generation as the entire application:

| Component | Responsibility |
| --- | --- |
| `jpgen/application.py` | Pipeline orchestration, run lifecycle and default dependency composition |
| `jpgen/configuration.py` | Load the complete YAML document |
| `jpgen/configuration_wizard/` | Interactive, extensible configuration collection and recoverable YAML publication |
| `jpgen/configuration_values.py` | Scalar, vector and mapping validation shared by stages |
| `jpgen/errors.py` | Pipeline and stage errors |
| `jpgen/progress.py` | Run-level and stage-level progress events |
| `jpgen/run_repository.py` | Run workspaces, summaries and atomic output publication |
| `jpgen/packing/application.py` | Packing stage orchestration |
| `jpgen/packing/configuration.py` | `PackingPlan`, `PackingSourcePlan` and packing configuration validation |
| `jpgen/packing/sizing.py` | Resolve the box and particle population |
| `jpgen/packing/placement/` | Particle placement contracts and algorithms |
| `jpgen/packing/domain/` | `ParticlePacking`, metadata, box, audits and placement statistics |
| `jpgen/packing/generator.py` | `PackingGenerationService` and its `PackingGenerator` implementation |
| `jpgen/packing/persistence.py` | `PackingStore` and its versioned `Hdf5PackingStore` implementation |
| `jpgen/packing/exporters/` | `PackingExporter` and the Kratos and VTK adapters |
| `jpgen/dem/application.py` | Prepare, execute, collect and persist a DEM stage |
| `jpgen/dem/configuration.py` | Validate physical inputs and retain the backend in a `DemPlan` |
| `jpgen/dem/domain.py` | Engine-independent material, contact, case and final state |
| `jpgen/dem/backends/base.py` | `DemBackend` and common execution records |
| `jpgen/dem/backends/kratos/` | Kratos case translation, isolated runtime and result collection |
| `jpgen/dem/persistence.py` | `DemResultStore` and its versioned `Hdf5DemResultStore` implementation |

`JPGenApplication.run` owns the complete run. It generates or imports a packing,
then executes DEM when configured. `RunStarted`, `RunCompleted` and `RunFailed`
describe the whole pipeline. Packing and DEM have separate progress events and
summary states. A successful DEM run means the requested time was reached, not
that mechanical equilibrium was established.

Configuration names are stage-specific and are consumed without aliases or migration logic.

## Configuration

The root configuration requires exactly one of `packing` or `packing_source`.
An optional `dem` section enables simulation; omitted or null means packing only.
Unknown root keys are rejected.

```yaml
packing:
  sizing_method: fixed_count
  count: 8000
  seed: 20260916
  exports: [vtk]
  box:
    origin: [0.0, 0.0, 0.0]
    lengths: [0.1, 0.1, 0.1]
    periodic: false
  radii:
    type: uniform
    min: 0.0005
    max: 0.001
  velocity: {type: constant, value: 0.0}
  angular_velocity: {type: constant, value: 0.0}
  placement:
    method: random_sequential
    max_overlap: 0.0
    position_attempts: 1000
```

`exports` is a list containing `vtk`, `kratos`, both, or neither. Names are
case-insensitive, duplicate values are removed while preserving their first
occurrence, and the normalized configuration records lowercase names. Omitting
the field is equivalent to `exports: []`; `packing.h5` is always produced and
does not embed this publication choice. Unknown formats are rejected with the
list of available formats. Unknown options inside `packing` or
`packing.placement` are rejected.

### Packing sizing

`PackingSizingStrategy.create_population(config, rng)` returns the final `Box` and radius array for one attempt. Sizing is independent of particle placement:

- `fixed_count`: requires `count` and fixed `box.lengths`; no target fraction.
- `fixed_box_fraction`: requires `target_solid_fraction` and fixed `box.lengths`; determines the particle count. Omit `count`.
- `variable_box_fraction`: requires `count`, `target_solid_fraction` and reference `box.lengths`; scales all lengths equally while preserving their ratios and origin.

The selected sizing and placement implementations are retained in `PackingPlan` and reused by `PackingGenerator`; execution does not consult either registry again. Add sizing methods through `PACKING_SIZING_STRATEGIES` and placement methods through `PLACEMENT_STRATEGIES`.

Solid fraction is `sum(4*pi*r**3/3) / box_volume`. Overlapping particle volumes are counted separately, so it is a nominal material fraction rather than a geometric union fraction. `solid_fraction_tolerance` defaults to `0.001` and is absolute. `restarts` defaults to 10 retries after the initial attempt, and `max_particles` defaults to 1,000,000.

### Radius and speed distributions

The same scalar distribution syntax applies to `radii`, `velocity` and `angular_velocity`; `explicit` is available only for radii:

```yaml
{type: constant, value: 0.001}
{type: uniform, min: 0.0005, max: 0.001}
{type: normal, mean: 0.001, std: 0.0002, min: 0.0005, max: 0.0015}
{type: lognormal, median: 0.001, sigma: 0.2, min: 0.0005, max: 0.002}
{type: explicit, values: [0.001, 0.0015, 0.002]}
```

Radii are strictly positive. Normal and lognormal samples outside their mandatory bounds are rejected rather than clipped. Rejection stops after 1000 draws per value. Velocity values are nonnegative magnitudes; independent isotropic directions are generated for linear and angular velocity. Both velocity distributions default to zero.

## Particle placement

`box.periodic` is a single boolean for all axes. Nonperiodic spheres remain entirely inside the box. Periodic centers remain in the primary box, use minimum-image distances and are checked against their own periodic images.

`placement.max_overlap` is in `[0, 1]` and defaults to zero. For radii `ri`, `rj` and center distance `d`, overlap is:

```text
min(1, max(0, ri + rj - d) / (2 * min(ri, rj)))
```

`PlacementStrategy.place` receives a `PlacementRequest` containing the final box, radii, constraints and random stream. It returns a `PlacementResult`; it never changes the supplied box or radii.

Available methods:

- `random_sequential`: inserts larger particles first while preserving output ID/radius order. `position_attempts` defaults to 1000 per particle.
- `overlap_relaxation`: begins from random centers and iteratively removes overlap using bounded displacements and optional seeded perturbations.
- `progressive_growth`: places reduced temporary radii, relaxes them, and grows toward the final radii with rollback and adaptive increments.

The relaxation-based methods accept `max_iterations`, `step_size`, `max_displacement`, `overlap_tolerance`, `stagnation_iterations`, `improvement_tolerance`, `max_perturbations`, `perturbation` and `relax_all_overlaps`. The last option defaults to `true`: while any pair exceeds `max_overlap`, every overlapping pair contributes a correction toward zero overlap. Set it to `false` to correct only the portion of overlap above `max_overlap`. In both modes relaxation stops as soon as all pairs satisfy `max_overlap` within `overlap_tolerance`. Progressive growth additionally accepts `initial_scale`, `initial_increment`, `min_increment`, `max_increment` and `max_stages`.

These methods are geometric heuristics. They do not guarantee convergence, calculate forces, establish mechanical equilibrium or run DEM.

## DEM simulation

`ParticlePacking` contains IDs, geometry, initial velocities, its box and `PackingMetadata`. It intentionally contains no material properties, masses, contact laws or solver state. Those belong to `jpgen.dem`. `DemState` represents the final state separately because particles may leave the initial packing box through open boundaries.

Run the complete example with the local Kratos build:

```bash
source ./activate_kratos.sh
jpgen examples/packing_with_dem.yaml
```

Alternatively set `dem.backend_options.installation: Kratos/bin/Release`.
This directory must contain `KratosMultiphysics/` and the build's `libs/`.
Without it, the worker inherits the current environment. `python` selects an
alternative interpreter (defaults to the current interpreter); `threads` defaults
to 1; `timeout_seconds` defaults to null (no timeout). Paths are relative to the
launch directory and are normalized to absolute paths in the run configuration.
No shell activation script is executed by JPGen.

The supported first version uses one material assigned to all particles, spheres
with rotation, fixed time steps, and symplectic Euler translation with direct
rotational integration. `end_time` must be a positive integer multiple of
`time_step`. The user selects a step small enough to resolve contact dynamics;
JPGen does not estimate a stable step automatically.

```yaml
dem:
  engine: kratos
  material:
    density: 2500.0       # kg/m³
    young_modulus: 1.0e+7 # Pa
    poisson_ratio: 0.25
  contact:
    model: hertz_viscous_coulomb
    static_friction: 0.5
    dynamic_friction: 0.4
    friction_decay: 500.0 # s/m; default 500
    restitution: 0.8
  boundary: open
  gravity: [0.0, 0.0, -9.81] # m/s²; default zero
  time_step: 1.0e-6
  end_time: 0.001
```

`hertz_viscous_coulomb` maps to Kratos `DEM_D_Hertz_viscous_Coulomb`:
Hertz normal elasticity, viscous contact damping derived from restitution,
and tangential elasticity limited by Coulomb friction. The friction coefficient
transitions exponentially from static to dynamic with slip speed and the
specified decay coefficient. Global damping and rolling resistance are disabled.
This mapping does not promise identical behavior in future engines; another
adapter must implement and document the requested physics or reject the case.

`boundary: periodic` uses the packing's final box and requires
`packing.box.periodic: true`. `boundary: open` requires a nonperiodic packing;
the placement box creates no physical walls and particles may leave it. Walls,
multiple materials, equilibrium stopping, trajectories and restart checkpoints
are not implemented. Existing geometric overlaps are passed unchanged to DEM;
geometric relaxation is not mechanical equilibration.

The backend writes a standalone `dem/input/run.py`. It can be rerun manually
with the configured interpreter and environment. It preserves particle IDs,
captures the state before Kratos deletes its model parts, and records the actual
solver version and resolved Kratos parameters. Failed runs retain diagnostic
artifacts; timeout and interruption terminate the worker. `results.h5` is only
published after successful execution and result validation. Periodic final
positions are mapped into the primary box, including crossings on the last step.

Reuse an existing packing by replacing the complete `packing` section with:

```yaml
packing_source:
  file: runs/<previous-run>/packing.h5
  exports: [vtk]
# dem: ... use the same DEM section as above
```

The source is validated before creating the run. Its absolute path and SHA-256
are recorded; replay rejects a changed source. The new run also stores a packing
snapshot and only the fresh geometry exports selected by `packing_source.exports`;
the source run's export selection is ignored. This initializes a new DEM
simulation from the packing's velocities, not from a previous simulation's
contact history.

To add an engine, implement `DemBackend` (`validate`, `prepare`, `run`, `collect`,
`to_config`) and register its configuration factory in `DEM_BACKENDS`. Plans
retain the resolved backend, following the packing strategy pattern. Backend
objects never cross into the particle domain or common result format.

The optional packing-only MDPA exporter writes `SphericParticle3D` elements and
free nodal velocities. Its empty `Properties 1` block is a structural
placeholder, not a material assignment. That file alone is not a runnable DEM
case. When `dem.engine: kratos` is selected, the backend always creates its own
`dem/input/particlesDEM.mdpa` regardless of `exports`; it also supplies
materials, contact laws, time stepping and domain behavior.

## ParaView

Open `particles.vtp`, apply a **Glyph** filter, choose **Sphere**, set **Scale Array** to `diameter`, **Scale Factor** to `1`, **Glyph Mode** to **All Points**, and source sphere radius to `0.5`. The file stores centers and attributes rather than tessellated sphere surfaces.

## Persistence and reproducibility

HDF5 schema `JPGen.packing`, version `3.0`, stores float64 positions, radii and velocities; int64 particle IDs; SI unit attributes; domain data; effective configuration; and `PackingMetadata`. Older schemas are rejected without conversion. Arrays are gzip-compressed and every export is produced from an HDF5 readback.

DEM results use schema `JPGen.dem`, version `1.0`, with IDs, positions, radii,
linear and angular velocities, material IDs, final time, initial domain,
effective DEM configuration and execution provenance. Use
`Hdf5DemResultStore.load(path)` to read the common final state. These are results,
not restart checkpoints. The run summary includes final kinetic energy (J),
elapsed wall time, step count and the `end_time` stop reason.

Supply a nonnegative integer `seed`, or omit it to generate a 128-bit seed from the system random source. NumPy PCG64 streams derive from `SeedSequence(seed, spawn_key=(restart, role))`: radii=0, placement=1, speed=2, linear direction=3, angular speed=4 and angular direction=5. Run names do not influence generation.

Replay requires the same effective configuration, JPGen version and dependency versions recorded in the run. Identical numerical files across library versions or platforms are not guaranteed. Packing HDF5 files are not DEM restart checkpoints.
