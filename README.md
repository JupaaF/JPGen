# JPGen

JPGen is a particle simulation pipeline. Its first implemented stage creates reproducible packings of 3D spheres in axis-aligned rectangular boxes; a DEM resolution stage will consume those packings in the future. All physical quantities use SI units. Packing generation and export do not require a Kratos installation.

```bash
python -m pip install -e .
jpgen examples/fixed_count.yaml
```

Run `jpgen` without a file in an interactive terminal to create a complete YAML
configuration with the guided wizard and immediately execute it. The wizard
explains every value, accepts selectable input units, converts physical values
to SI, validates the complete packing configuration and shows a preview before
saving. It writes a timestamped `.yaml` file in the current directory by
default. If generation fails, a newly created file is removed or a replaced
file is restored.

Each invocation creates a unique directory under `runs/`:

- `configuration.yaml`: normalized pipeline configuration, defaults and actual seed; usable for replay.
- `summary.json`: run status, dependency versions, final box and packing statistics.
- `packing.h5`: versioned packing dataset with geometry, initial velocities, configuration and metadata.
- `particlesDEM.mdpa`: Kratos DEM sphere model part with an empty properties placeholder.
- `particles.vtp`: VTK XML PolyData for visualization.

Invalid configuration fails before a run directory is created. Packing failures return a nonzero exit code and preserve the effective configuration, seed and error. Outputs are published only after generation and HDF5 readback succeed. Existing runs are never overwritten. Replay with `jpgen runs/<run>/configuration.yaml`.

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
| `jpgen/packing/application.py` | Packing stage orchestration and ports |
| `jpgen/packing/configuration.py` | Build a validated `PackingPlan` |
| `jpgen/packing/sizing.py` | Resolve the box and particle population |
| `jpgen/packing/placement/` | Particle placement contracts and algorithms |
| `jpgen/packing/domain/` | `ParticlePacking`, metadata, box, audits and placement statistics |
| `jpgen/packing/generator.py` | Restarts, random streams, placement audit and packing assembly |
| `jpgen/packing/persistence.py` | Versioned `Hdf5PackingStore` |
| `jpgen/packing/exporters/` | `PackingExporter` and the Kratos and VTK adapters |

`JPGenApplication.run` owns the complete run. It currently executes the packing stage; the future DEM stage will be added after it without redefining packing classes as application-level concepts. `RunStarted`, `RunCompleted` and `RunFailed` describe the whole pipeline. Events such as `PackingAttemptStarted` and `PackingCompleted` describe only the packing stage.

Configuration names are stage-specific and are consumed without aliases or migration logic.

## Configuration

The current root configuration requires `packing`. A future `dem` section may coexist at the same level.

```yaml
packing:
  sizing_method: fixed_count
  count: 8000
  seed: 20260916
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

Unknown options inside `packing` or `packing.placement` are rejected.

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

## DEM boundary

`ParticlePacking` contains IDs, geometry, initial velocities, its box and `PackingMetadata`. It intentionally contains no material properties, masses, contact laws or solver state. Those belong to the future `jpgen.dem` stage.

`examples/future/packing_with_dem.yaml` shows the intended top-level separation. Its `dem` section is currently ignored and is not persisted in run configuration.

The MDPA exporter writes `SphericParticle3D` elements and free nodal velocities. Its empty `Properties 1` block is a structural placeholder, not a material assignment. The exported file is not a runnable DEM case: materials, contact laws, time stepping, walls and periodic-domain behavior must be configured by the DEM stage.

## ParaView

Open `particles.vtp`, apply a **Glyph** filter, choose **Sphere**, set **Scale Array** to `diameter`, **Scale Factor** to `1`, **Glyph Mode** to **All Points**, and source sphere radius to `0.5`. The file stores centers and attributes rather than tessellated sphere surfaces.

## Persistence and reproducibility

HDF5 schema `JPGen.packing`, version `3.0`, stores float64 positions, radii and velocities; int64 particle IDs; SI unit attributes; domain data; effective configuration; and `PackingMetadata`. Older schemas are rejected without conversion. Arrays are gzip-compressed and every export is produced from an HDF5 readback.

Supply a nonnegative integer `seed`, or omit it to generate a 128-bit seed from the system random source. NumPy PCG64 streams derive from `SeedSequence(seed, spawn_key=(restart, role))`: radii=0, placement=1, speed=2, linear direction=3, angular speed=4 and angular direction=5. Run names do not influence generation.

Replay requires the same effective configuration, JPGen version and dependency versions recorded in the run. Identical numerical files across library versions or platforms are not guaranteed. Packing HDF5 files are not DEM restart checkpoints.
