# JPGen

Para ejecutar JPGen en el clúster Acuario de CIMNE, consulta la
[guía de Acuario](docs/acuario.md).

JPGen is a particle simulation pipeline. It creates reproducible packings of 3D spheres in axis-aligned rectangular boxes and optionally simulates them with a DEM engine. Kratos is the first implemented engine; the DEM stage uses an engine-independent case and backend contract. All physical quantities use SI units. Release wheels include the JPGen C++ placement kernels and the pinned, modified Kratos DEM runtime. No separate Kratos installation is needed.

The first release supports CPython 3.12 on Linux x86_64 and Windows x86_64.
The wheels contain the native placement module and the pinned Kratos fork.
After publication, install JPGen from PyPI:

```bash
python -m pip install jpgen
jpgen
```

Before publication, download the wheel for your platform from the
[GitHub Actions build](https://github.com/JupaaF/JPGen/actions/workflows/build-wheels.yml)
and install it with `python -m pip install /path/to/jpgen-0.5.0-*.whl`.
The [release process](docs/packaging.md#publishing-a-release) describes how
validated wheels are published. macOS and other Python versions are not covered
by this release.

In an interactive terminal, `jpgen` starts the configuration wizard and runs
the chosen pipeline. To use an existing YAML file, run `jpgen config.yaml`.
Results are written to `./runs/` by default; use
`jpgen config.yaml --output-dir /path/to/runs` to choose another location.
The CLI prints progress directly by default. Select standard-library logging or
disable progress output without changing the reproducible YAML configuration:

```bash
jpgen examples/fixed_count.yaml --progress logging
jpgen examples/fixed_count.yaml --progress none
```

The `logging` mode writes progress to standard error. Every run independently
records structured progress in `logs/events.jsonl` and a readable `logs/jpgen.log`,
including when console progress is disabled.

Programmatic callers can pass any `ProgressObserver` to
`JPGenApplication.run(..., observer=...)`; omitting it is silent. The CLI alone
chooses `ConsoleProgressObserver` as its default.

The wheel includes the C++17 placement kernels and uses them by default.
`JPGEN_PLACEMENT_BACKEND=python` selects the Python implementation for
comparison. `JPGEN_PLACEMENT_BACKEND=native` requires the compiled kernels.
Each wheel also contains the pinned JPGen Kratos fork and its license notices.
See building release wheels (`docs/packaging.md`) for source and platform details.

Run `jpgen` without a file in an interactive terminal to create a complete YAML
configuration with the guided wizard and immediately execute it. The wizard can
generate a new packing or reuse an existing `packing.h5`, asks which optional
packing formats to export, explains every value, accepts selectable input units,
converts physical values to SI, validates the complete configuration and shows a
preview before saving. It writes a timestamped `.yaml` file in the current
directory by default. If generation fails, a newly created file is removed or a
replaced file is restored.

The wizard uses Textual to display a full-screen interface with a section sidebar,
progress through the currently applicable questions, scrollable forms and a YAML
preview. In terminals with mouse support, click options and checkboxes, scroll
with the wheel, and use the Continue, Back and Cancel buttons. Clicking inside
a text field positions the cursor; typed text is always treated as input.
Keyboard navigation uses Tab, arrow keys, Space and Enter; Alt+Left goes back
and Ctrl+C cancels. The sidebar hides in narrow terminals to give forms more room.

Each invocation creates a versioned, self-contained run under `./runs/` or
`--output-dir`, named `2026-09-30_14-32-08Z__label__a7c92e31`. Its UUID is
independent of the directory name. Use `--label`, repeatable `--tag` and
`--experiment` to organize runs without changing their physical configuration.

```text
<run>/
  run.json                         # Identity, lifecycle, stage references and result availability
  artifacts.json                   # Published files, roles, validation and SHA-256 hashes
  config/{requested,effective}.yaml
  provenance/{environment,sources}.json
  stages/packing/
    summary.json
    results/packing.h5
    exports/                       # Optional VTK and MDPA exports
  stages/dem/                      # When DEM is configured
    summary.json
    results/final.h5
    results/observables.jsonl
    results/states.jsonl
    results/states/                 # Common particle states and target metadata
    execution/                     # Attempts and rollback events
    backend/kratos/{input,native,checkpoints}/
    logs/{stdout,stderr}.log
  logs/{events.jsonl,jpgen.log}
  view/                            # Regenerable JSON summaries, series and packing preview
```

`run.json` uses schema `JPGen.run`, version `1.0`. Packing and DEM share the
same lifecycle vocabulary: `pending`, `running`, `completed`, `failed`,
`cancelled`, `interrupted`, and `skipped` where applicable. Run success and
result availability are separate: failed protocols retain earlier states and
observables. Common scientific outputs live outside the engine directory.
All artifact and state references are relative to the run root.

Invalid configuration or an unavailable runtime fails before creating a run.
Packing and final DEM HDF5 outputs are published after validation and readback;
`artifacts.json` is their publication marker. Interrupted multi-file publication
may leave unlisted files; explicit recovery validates HDF5 before registering
it. State indices are appended only after their NPZ/JSON pair is complete.
A torn final JSONL record is ignored by the reader. Existing runs are never
overwritten. Replay with `jpgen runs/<run>/config/effective.yaml`; imported
packing references resolve to the run's own snapshot, even after moving it.

The default `--retention full` keeps native checkpoints. `--retention analysis`
keeps scientific states, logs and engine inputs, skips ordinary boundary
restart exports and removes internal rollback checkpoints after execution.
Density continuation still creates the checkpoints required for live rollback.
Neither policy enables CLI resume.

```bash
jpgen config.yaml --label compression --tag baseline --experiment pressure-sweep
jpgen runs list runs
jpgen runs show runs/<run>
jpgen runs compare runs/<first> runs/<second>
jpgen runs verify runs/<run>
jpgen runs export runs/<run>
jpgen runs index runs
jpgen runs import /path/to/old-run --output-dir runs
```

`catalog.json` is a rebuildable discovery cache. `RunReader` exposes metadata,
configuration differences, state loading, observables and browser projections.
Only after the executing process has stopped, use `jpgen runs recover <run>`
to mark an abandoned running run as interrupted and reconcile its outputs.
See [the run-format contract](docs/run-format.md) for schemas, partial results,
legacy import, comparison semantics and browser integration.

## Viewer prototypes

Three interactive HTML concepts are available in
[the viewer prototype gallery](prototypes/run-viewer/index.html): **Observatorio**
for comparing runs, **Atlas** for browsing samples, and **Protocolo** for inspecting
saved states. Open the gallery directly in a browser; no installation is needed.
The prototypes distinguish synthetic demonstration data from the included real
archived run, and can load exported `view/` folders locally. See the
[prototype guide](prototypes/run-viewer/README.md) for interactions and limitations.
These are design prototypes, separate from the simulation and persistence code.

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
| `jpgen/run_repository.py` | Versioned workspaces, manifests, inventories and publication |
| `jpgen/run_reader.py` | Backend-independent queries, comparison and browser projections |
| `jpgen/run_management.py` | Explicit recovery and non-destructive legacy import |
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
summary states. A successful DEM run means its time or protocol conditions were
met. Mechanical equilibrium requires explicitly chosen physical criteria.

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
    origin_mode: minimum_corner
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

The wizard offers `box.origin_mode: center` to place the center of the final box at
`(0, 0, 0)`, or `minimum_corner` to place its minimum X, Y and Z corner there.
For `variable_box_fraction`, centering uses the final scaled lengths. Existing
YAML files can still specify explicit `box.origin` coordinates instead of
`box.origin_mode`; the two fields cannot be combined.

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
- `variable_box_fraction`: requires `count`, `target_solid_fraction` and reference `box.lengths`; scales all lengths equally while preserving their ratios. An explicit origin or the minimum corner stays fixed; center mode centers the final scaled box.

The selected sizing and placement implementations are retained in `PackingPlan` and reused by `PackingGenerator`; execution does not consult either registry again. Add sizing methods through `PACKING_SIZING_STRATEGIES` and placement methods through `PLACEMENT_STRATEGIES`. A new placement statistics class declares its `method` and provides `to_dict`/`from_dict`; the domain registers it automatically for HDF5 restoration.

Solid fraction is `sum(4*pi*r**3/3) / box_volume`. Overlapping particle volumes are counted separately, so it is a nominal material fraction rather than a geometric union fraction. `solid_fraction_tolerance` defaults to `0.001` and is absolute. Generation makes a single attempt; placement failures stop the run.

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

The wizard asks only for maximum overlap and maximum relaxation iterations for
`overlap_relaxation` and `progressive_growth`, plus maximum growth stages for
`progressive_growth`. Other algorithm settings use their defaults and are included
in the generated YAML. Edit that YAML to customize the advanced settings.

## DEM simulation

Archived measurements are available in
Kratos profiling results (`docs/kratos-performance-results.json`).
The archived C++ optimization measurements remain under `docs/`; those
experimental changes are not part of the release.

`ParticlePacking` contains IDs, geometry, initial velocities, its box and `PackingMetadata`. It intentionally contains no material properties, masses, contact laws or solver state. Those belong to `jpgen.dem`. `DemState` represents the final state separately because particles may leave the initial packing box through open boundaries.

The release wheel uses its bundled Kratos runtime automatically. The
DEM example (`examples/packing_with_dem.yaml`) can be downloaded from the source
repository and run with `jpgen packing_with_dem.yaml`. Developers can override
the bundled runtime with `dem.backend_options.installation`; that directory
must contain `KratosMultiphysics/` and `libs/`. Without a bundled or explicit
installation, the worker uses the active environment. `python` selects an
alternative interpreter (defaults to the current interpreter); `threads` defaults
to 1; `timeout_seconds` defaults to null (no timeout). Paths are relative to the
launch directory and are normalized to absolute paths in the run configuration.
No shell activation script is executed by JPGen.

The supported first version uses one material assigned to all particles, spheres
with rotation and symplectic Euler translation with direct rotational integration.
The normalized configuration records this as
`integration: {translation: symplectic_euler, rotation: direct}`; supported pairs
are declared by each backend. With a fixed `time_step`, `end_time` must be a
positive integer multiple of it. `time_step` must be a finite positive number;
adaptive time-step configurations are not supported.

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
multiple materials, particle trajectories and automatic restart from saved states are not implemented.
Protocols support physical stopping criteria and deformation of periodic cells. Existing geometric overlaps are passed unchanged to DEM;
geometric relaxation is not mechanical equilibration.

The backend writes a standalone `stages/dem/backend/kratos/input/run.py`. It can be rerun manually
with the configured interpreter and environment, passing `--output-dir` with a
new stage directory. In-place reruns are rejected to preserve the original run.
It preserves particle IDs,
captures the state before Kratos deletes its model parts, and records the actual
solver version and resolved Kratos parameters. Failed runs retain diagnostic
artifacts; timeout and interruption terminate the worker. `final.h5` is only
published after successful execution and result validation. Periodic final
positions are mapped into the primary box, including crossings on the last step.

Reuse an existing packing by replacing the complete `packing` section with:

```yaml
packing_source:
  file: runs/<previous-run>/stages/packing/results/packing.h5
  exports: [vtk]
# dem: ... use the same DEM section as above
```

The source is validated before creating the run. Its absolute path and SHA-256
are recorded in provenance; replay validates the local snapshot hash. The new run also stores a packing
snapshot and only the fresh geometry exports selected by `packing_source.exports`;
the source run's export selection is ignored. This initializes a new DEM
simulation from the packing's velocities, not from a previous simulation's
contact history.

To add an engine, implement `DemBackend` (`validate`, `prepare`, `run`, `collect`,
`to_config`) and register a `BackendDefinition` in `DEM_BACKENDS`. Its metadata
declares capabilities and lazy references to the backend factory and its specific
wizard questions. The common wizard uses this registry to select the engine,
contact law and integration pair. Contact specifications have their own validators
in `CONTACT_MODELS`. Plans retain the resolved backend; backend objects never
cross into the particle domain or common result format. See the
engine extension guide (`docs/dem-backends.md`) for contracts and physics semantics.

The optional packing-only MDPA exporter writes `SphericParticle3D` elements and
free nodal velocities. Its empty `Properties 1` block is a structural
placeholder, not a material assignment. That file alone is not a runnable DEM
case. When `dem.engine: kratos` is selected, the backend always creates its own
`stages/dem/backend/kratos/input/particlesDEM.mdpa` regardless of `exports`; it also supplies
materials, contact laws, time stepping and domain behavior.

## ParaView

Open `particles.vtp`, apply a **Glyph** filter, choose **Sphere**, set **Scale Array** to `diameter`, **Scale Factor** to `1`, **Glyph Mode** to **All Points**, and source sphere radius to `0.5`. The file stores centers and attributes rather than tessellated sphere surfaces.
VTK ASCII arrays are streamed in blocks of 4096 particles, including derived
diameters and vertex indices, keeping temporary serialization memory bounded.

## Persistence and reproducibility

HDF5 schema `JPGen.packing`, version `4.0`, stores float64 positions, radii and velocities; int64 particle IDs; SI unit attributes; domain data; effective configuration; and `PackingMetadata`. Older schemas are rejected without conversion. Arrays are gzip-compressed and every export is produced from an HDF5 readback.

DEM results use schema `JPGen.dem`, version `1.1` (the reader also accepts `1.0`), with IDs, positions, radii,
linear and angular velocities, material IDs, final time, initial and final domains,
effective DEM configuration and execution provenance. Use
`Hdf5DemResultStore.load(path)` to read the common final state. These are results,
not restart checkpoints. The run summary includes final kinetic energy (J),
elapsed wall time, actual step count, stop reason (`end_time` or
`protocol_complete`), completed stage count and final measured observables.

Supply a nonnegative integer `seed`, or omit it to generate a 128-bit seed from the system random source. NumPy PCG64 streams derive from `SeedSequence(seed, spawn_key=(role,))`: radii=0, placement=1, speed=2, linear direction=3, angular speed=4 and angular direction=5. Run names do not influence generation.

Replay requires the same effective configuration, JPGen version and dependency versions recorded in the run. Identical numerical files across library versions or platforms are not guaranteed. Packing HDF5 files are not DEM restart checkpoints.

## DEM protocols

Use `dem.protocol` instead of `dem.end_time` to compose a simulation from stages.
Both forms remain supported, but cannot appear together. The interactive wizard
can build stages and nested repeat blocks, or import a protocol from YAML.
Imported protocols are embedded in the generated configuration, so replay does
not depend on the imported file. See dem_protocol.yaml (`examples/dem_protocol.yaml`)
for a complete free evolution → consolidation → pressure cycles → relaxation case.

```yaml
protocol:
  sample_every: 100
  stages:
    - name: relax
      control: {type: free_evolution}
      until:
        observable: kinetic_energy
        op: below
        value: 1.0e-8
        min_duration: 0.001
        hold_for: 0.001
      max_duration: 1.0
    - name: consolidate
      control:
        type: stress_servo
        mode: isotropic
        target_pressure: 100000.0
        max_velocity: 0.05
        loading_factor: 0.8
        update_every_steps: 50
      until:
        observable: pressure
        op: near
        value: 100000.0
        atol: 1000.0
        hold_for: 0.005
      max_duration: 2.0
```

A leaf stage requires `control`, `until` and `max_duration`; `name` is optional.
A sequence block has `stages` and optional `repeat` (positive integer, default 1)
and `name`. Blocks can nest up to 20 levels and are traversed lazily; repetitions
reset stage time, signal phase and condition history. Reorder stages to change the
experiment. Every stage runs on the same live solver, preserving contact history.

### Controllers and targets

| Controller | Parameters | Behavior |
| --- | --- | --- |
| `free_evolution` | None | Integrate particles with the current cell fixed |
| `stress_servo` | `mode: isotropic`, `target_pressure`, `max_velocity`, `loading_factor`, `update_every_steps` | Control mean normal contact stress |
| `stress_servo` | `mode: anisotropic`, `target_stress: [xx, yy, zz]`, `max_velocity`, `loading_factor`, `update_every_steps` | Independently control three normal stresses |
| `strain_rate` | `rate: [x, y, z]` | Prescribe logarithmic cell strain rates in 1/s; expansion positive |
| `density_continuation` | `targets`, confinement, friction, relaxation and limits | Reduce contact friction adaptively under pressure control; publish equilibrated density targets |

The portable JPGen servo uses Kratos' wall-velocity formula. For each controlled
axis it commands `(target - measured) * loading_factor * D50 /
(time_step * particle_Young_modulus)`, clipped by `max_velocity` (default
`0.05` m/s). `loading_factor` defaults to `0.8`, as in Kratos. `D50` is the median
particle diameter by count. Positive velocity moves both opposing faces inward;
negative velocity moves them outward. Isotropic control applies the same face
velocity on all axes. `update_every_steps` is a positive integer (default `1`):
JPGen updates the cell on every Nth step of each leaf stage, counting from one,
and leaves it fixed on the intervening steps. Kratos' native default is 50 steps.
Tune the loading factor, update interval, velocity limit and tolerances for the
material and sample; a target may be physically unreachable and convergence is
not guaranteed.

A target can be a nonnegative constant or a time signal:

```yaml
# Substitute for target_pressure, or for any target_stress component:
target_pressure: {type: ramp, start: 50000.0, end: 100000.0, duration: 0.1}
# Alternatively:
# target_pressure: {type: sine, mean: 75000.0, amplitude: 25000.0, frequency: 2.0, phase: 0.0}
```

Ramps hold their final target after `duration`. Sinusoidal frequency is in Hz
and optional phase in radians. Signals use stage time and are evaluated before
each integration step; for time-driven cycles use a `stage_time` stop condition.
A repeated pair of constant-target stages instead switches at measured stress
thresholds and has no imposed frequency.

Cell control currently requires periodic boundaries. The Kratos adapter receives
an explicit solver-independent actuator command, moves opposite faces
symmetrically and applies the corresponding affine displacement to particles,
without resetting their velocities or contact history. A following
free evolution stage preserves the attained cell. Deformation above 1% per step
or a cell width at most twice the largest particle diameter is rejected.
Walls and shear deformation are not provided by these controllers.

### Observables and conditions

| Observable | Meaning / units |
| --- | --- |
| `time` | Global simulation time, s |
| `stage_time` | Time since entry into this leaf stage, s |
| `kinetic_energy` | Total translational + rotational particle kinetic energy, J |
| `normalized_kinetic_energy` | `kinetic_energy / (pressure × cell volume)`, dimensionless; periodic cells with positive pressure |
| `unbalanced_force` | RMS total particle force / RMS contact force, dimensionless |
| `solid_fraction` | Sum of sphere volumes / current cell volume, dimensionless |
| `bulk_density` | Particle mass / current cell volume, kg/m³ |
| `pressure` | Trace of the contact stress tensor / 3, Pa, compression positive |
| `stress_xx`, `stress_yy`, `stress_zz`, `stress_xy`, `stress_xz`, `stress_yz` | Components of the contact stress tensor, Pa |
| `mean_coordination_number` | MCN = 2 × contact count / particle count, dimensionless |
| `fabric_tensor` | Mean outer product of contact directions, 3×3, dimensionless |
| `fabric_second_invariant` | Square root of the second invariant of 7.5 × (Fabric − I/3), dimensionless |
| `thermal_conductivity` | DEMGen contact geometry tensor, 3×3, dimensionless; periodic cells only |
| `thermal_conductivity_trace` | Tensor trace / 3, dimensionless |

MCN and Fabric are recorded from Kratos's contact mesh at protocol samples,
stage exits and the final DEM result, including runs with open boundaries.

`thermal_conductivity` follows DEMGen's geometric definition: each overlapping
contact contributes its intersection-circle area times its center distance times
the outer product of its unit branch direction; the sum is divided by the current
periodic cell volume. It uses neither contact forces nor temperatures and is not
a thermal conductivity in W/(m·K). The full tensor and its trace mean are
recorded at protocol samples and stage exits, and in the final DEM result.
Kratos's native DEM measurement is required. Runs with open boundaries omit
this cell-based measurement.

Stress is the contact-force/branch-vector contribution measured by Kratos,
without a kinetic stress contribution. Density, stress and normalized kinetic energy conditions require a
periodic cell; an open placement box does not define a material sample volume.
The normalized energy is unavailable while the measured pressure is zero or
negative, so its condition cannot pass and the field is omitted from samples.
It is recorded at samples in periodic protocols that measure pressure.
Particle material density remains constant. Sphere volume sums do not subtract
overlap volumes. `unbalanced_force` approaches zero as the force residual falls
relative to the contact-force scale; Kratos defines it as zero when there are no
contacts. Kinetic energy alone is not proof of mechanical equilibrium.

`above` means >= and `below` means <=. `near` means
`abs(value - target) <= atol + rtol * abs(target)` and requires at least one
tolerance. `all` and `any` combine nonempty lists of conditions and can nest:

```yaml
until:
  all:
    - {observable: pressure, op: near, value: 100000.0, atol: 1000.0}
    - {observable: kinetic_energy, op: below, value: 1.0e-8}
    - {observable: unbalanced_force, op: below, value: 1.0e-3}
  hold_for: 0.005
  min_duration: 0.01
```

`hold_for` requires consecutive successful observations; its timer resets after
any failed observation. `min_duration` prevents completing a stage too early.
Both can be applied to a leaf condition or a group. Conditions are evaluated
after every completed step, independent of the output sampling interval. A dwell
starts at the first matching observation. All thresholds are evaluated on
completed steps, not interpolated between them. A stage always executes at least
one step. A nonintegral `max_duration / time_step` is rounded up to a whole step.
If the condition becomes true on the last allowed step, it succeeds; otherwise
the run fails with `max_duration` diagnostics and does not start the next stage.

To stop a servo by density, change only its `until`:

```yaml
until: {observable: solid_fraction, op: above, value: 0.64}
# Or: {observable: bulk_density, op: above, value: 1600.0}
```

### Equilibrated pressure paths

A protocol piece may be a pressure path. It creates a sequence of constant
stress servo targets and advances only after pressure, kinetic energy and
force imbalance satisfy the acceptance condition continuously for `hold_for`.
Isotropic control adjusts all axes together to track mean pressure. Anisotropic
control tracks each normal stress independently and also requires all three
normal stresses to satisfy the target tolerance.
The starting and final targets are equilibrated and saved; `intermediate_states`
counts only targets strictly between `start` and `end`. The path applies the
same acceptance condition to the initial target before advancing. Both
pressures must be positive, and either increasing or decreasing paths are
allowed.

```yaml
dem:
  # engine, material, contact, boundary: periodic, time_step, ...
  protocol:
    sample_every: 100
    stages:
      - name: compression
        path:
          observable: pressure
          targets:
            start: 5000.0
            end: 200000.0
            intermediate_states: 20
            spacing: log
          control:
            type: stress_servo
            mode: isotropic
            max_velocity: 0.01
            loading_factor: 0.8
            update_every_steps: 50
          acceptance:
            target_rtol: 0.01
            kinetic_energy_below: 1.0e-8  # or normalized_kinetic_energy_below: 1.0e-6
            unbalanced_force_below: 1.0e-3
            hold_for: 0.005
          max_duration_per_target: 0.5
```

For an anisotropic path, set `control.mode: anisotropic` and
`control.stress_ratios: [0.5, 1.0, 1.5]`, for example. The three positive
ratios must sum to 3. Each target pressure is multiplied by these ratios to
produce the X, Y and Z stress targets while preserving their mean. Omitting
`mode` keeps existing paths isotropic.

`spacing` may be `log` or `linear`. For 20 intermediate states the path
attempts 22 targets, including the initial and final pressures. The targets
are calculated once from the effective configuration; successful targets continue in the same solver with contact
history intact. Each target has its own duration limit and hold timer. If any
target fails, later targets are not attempted.

Every target boundary is recorded in `stages/dem/results/states.jsonl`.
Successful targets have `accepted: true`, their requested target, measured
observables, time and a common particle-state reference. A failed target remains
a diagnostic boundary, never an accepted target. Earlier accepted targets remain
available after later failures. The same index is used for pressure and density
objectives. Native checkpoint references have explicit analysis/rollback/resume
capabilities; ordinary boundary restart files do not promise JPGen resume.

### Density continuation

Use `control.type: density_continuation` in a periodic leaf stage to reduce the
active static and dynamic friction by a common factor while an isotropic servo
maintains the configured pressure. Targets must be strictly increasing, with
a separation greater than twice `density_atol`. Acceptance requires the target
density, pressure tolerance, kinetic energy, force imbalance and density
stability to hold together. A transient crossing never publishes a target.
See the complete protocol (`docs/density-continuation-protocol.md`) and the
small runnable example (`examples/dem_density_continuation.yaml`).

A failed increment restores the preceding solver checkpoint and retries with a
smaller friction decrement. `max_duration` counts all integrated attempts,
including discarded branches. The physical time in the final state follows
only the accepted branch; `attempted_duration` reports total integrated work.
Each accepted target is published in `stages/dem/results/states/`, with a
common particle state and a `.target.json` file. Its native checkpoint stays in
`stages/dem/backend/kratos/checkpoints/` under full retention.
`stages/dem/execution/attempts.jsonl` records attempts, transient crossings,
discards and acceptances. Earlier targets remain available after later failures.
Kratos uses neighbour search on every step for this controller so restored
contact forces reproduce the uninterrupted trajectory.

Density rollback requires the JPGen Kratos DEM patch in
vendor/kratos-dem-restart.patch (`vendor/kratos-dem-restart.patch`).
The runtime checks for its version marker before creating a run. Apply the
patch to the matching Kratos source and rebuild `KratosDEMCore` and
`KratosDEMApplication`, or use the bundled wheel, which includes this modification.
The serialized checkpoint includes the portable controller state for audit;
CLI resume after a process exit is not implemented. Rollback is performed
inside the active worker run.

### Results and extension points

For DEM protocols, every leaf-stage and repeated-block boundary is indexed in
`stages/dem/results/states.jsonl`. Simultaneous boundaries share a `state_id`.
States contain IDs, positions, radii, velocities, angular velocities and box
geometry in a versioned NPZ/JSON pair. Native checkpoints remain separate.

`stages/dem/results/observables.jsonl` records sampled observables and geometry,
including stage exits. Records include an event sequence, branch and attempt
identity; physical time can decrease after rollback. `RunReader.series()`
excludes discarded and unresolved attempts by default; pass
`include_discarded=True` for diagnostic history. Final HDF5 retains the report,
observables and domain geometries. Failed protocols keep diagnostic states and
execution artifacts without publishing a successful `final.h5`.

`jpgen/dem/protocol.py` contains solver-independent validation, conditions,
signals, controller functions and the lazy `ProtocolRunner`. Controllers emit typed commands (`NoActuation`, `CellStrainRate` or
`SymmetricWallVelocity`) rather than calling solver APIs. Free evolution requires
no deformation actuator capability. To introduce a new controller, add its validator and
register its function in `CONTROLLERS`; a new actuator requires an explicit
adapter-contract extension. New observables need a name in the validator and a
measurement in the backend adapter.

Every backend declares contact models, supported integration pairs, boundaries,
controllers, observables and actuator commands through
`DemCapabilities`; unsupported protocols are
rejected before execution. The protocol and controller remain owned by JPGen so
their meaning is stable across engines. A backend may advertise native controls,
but using one requires an explicit backend-specific implementation rather than a
silent semantic change.

`backends/kratos/protocol_adapter.py` translates portable commands into Kratos
cell operations and measurements; `runner.py` connects these to solver lifecycle
hooks. The standalone case copies these modules alongside `run.py` and requires
no JPGen import at execution time.

Kratos measures total kinetic energy when required by the active condition or
output sample through its native
translational and rotational energy calculators (C++/OpenMP). The sum retains
the same stopping-criterion meaning. `sample_every` only controls output frequency. Active stopping conditions are
still evaluated on every completed step. Output samples and stage exits retain
kinetic energy, periodic density/fraction, and the stress tensor when requested
anywhere in the protocol. Between samples, only active-stage measurements are
computed. Contact data remain updated when stress output is enabled, so an
unscheduled stage exit can record current stress.

Cell deformation uses Kratos bulk position/displacement operations and NumPy
array arithmetic instead of a Python loop over particles. The maximum radius
and solid volume are cached for the fixed particle population.
