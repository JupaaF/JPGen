# JPGen

JPGen currently provides a CLI module for reproducible random generation of 3D spheres in axis-aligned rectangular boxes. All physical quantities use SI units. No Kratos installation is needed for generation or export.

```bash
python -m pip install -r requirements.txt
python src/main.py examples/particles.yaml
```

Each invocation creates a unique directory under `runs/` in the project root:

- `configuration.yaml`: effective inputs, defaults and the actual seed; usable as input for replay.
- `summary.json`: status, dependency versions, achieved solid fraction, final box and generation statistics.
- `particles.h5`: complete versioned dataset, including geometry, initial velocities, domain, configuration and metadata.
- `particlesDEM.mdpa`: Kratos DEM sphere geometry, radii, linear and angular velocities, with an empty properties placeholder.
- `particles.vtp`: VTK XML PolyData for visualization.

Invalid configurations fail before creating a run. Generation failures return a nonzero exit code and preserve configuration, seed and error in the run directory. Particle outputs are written only after generation and serialization succeed. Existing runs are never overwritten. Replay with `python src/main.py runs/<run>/configuration.yaml`.

## Module boundaries

Everything specific to particle generation is contained in `src/particle_generation/`:

| Component | Responsibility |
| --- | --- |
| `domain.py` | Validated value objects, typed generation metadata, audits and packing statistics |
| `configuration.py` | Common input validation, defaults and dispatch to strategy validation |
| `configuration_values.py` | Shared scalar, vector and mapping checks |
| `distributions.py` | Polymorphic validation, sampling and serialization of scalar distributions |
| `sampling.py` | Independent random streams and isotropic vector construction |
| `strategies.py` | Abstract geometry strategy, mode registry and three box/radius preparation methods |
| `generation.py` | `ParticleGenerator`: retries, random streams, final packing audit and particle assembly |
| `packing/` | Abstract packing contract, insertion, geometric relaxation, growth and neighbor searches |
| `persistence.py` | `Hdf5ParticleStore`, the versioned particle persistence adapter |
| `progress.py` | Structured progress events, observer port and console presentation adapter |
| `exporters/` | `ParticleExporter` port and the Kratos and VTK adapters |
| `run_repository.py` | Filesystem adapter for run workspaces, summaries and atomic output staging |
| `application.py` | Injected application service and default CLI composition |

`src/main.py` handles CLI arguments and dispatch, passing only the `particle_generation` section to the composed `ParticleGenerationApplication`. The application coordinates injected generation, run repository, particle store, exporters, progress observer and version provider; concrete filesystem and file-format operations remain in their adapters. Configuration builds a `GenerationPlan` containing the normalized values and the exact geometry and packing strategy instances that will execute the run. `src/configuration.py` provides `load_config`, which reads YAML and checks that its root is a nonempty mapping. The module validates its own section without inspecting other modules' inputs. Saved configuration files retain the top-level `particle_generation` wrapper for CLI replay. There is no public Python API commitment.

Validation is divided by responsibility. Configuration checks input syntax and constructs domain values; `Box`, `ParticleSet`, `GenerationMetadata` and the statistics DTOs enforce their own invariants when constructed. Packing feasibility is an operation-specific precondition, while `audit_packing` independently checks an algorithm's final containment and overlap result. Persistence reconstructs the same domain objects instead of maintaining a separate set of structural rules.

Progress is emitted as typed events such as `GenerationAttemptStarted`, `RelaxationProgress` and `RunCompleted`. Algorithms do not format user-facing strings. The CLI installs `ConsoleProgressObserver`; other callers can inject an observer that records, translates or forwards events without parsing console text.

## Generation modes

`GeometryStrategy.prepare(config, rng)` returns a fresh `Box` and radius array for one attempt. `FixedCount`, `FixedBoxFraction` and `VariableBoxFraction` implement that contract and are selected through `GEOMETRY_STRATEGIES`. Strategies receive the validated section and the restart-specific radius stream; they do not place particles, manage retries, write files or create their own random generators. Box scaling belongs entirely to `VariableBoxFraction`.

The configuration coordinator first validates common inputs, then calls `strategy.validate_config(config)` on its private configuration copy. Each strategy validates and normalizes its own fields; no `super()` call is required. The selected geometry instance and the configured packing instance are retained in `GenerationPlan` and reused by `ParticleGenerator`; execution does not consult either strategy registry again. Shared value checks live in `configuration_values.py` to avoid circular dependencies.

To add a geometry method, implement `GeometryStrategy.validate_config` and `prepare`, declare its additional accepted fields in `config_options`, and register its class. Mode-specific rules belong to the strategy, so adding a mode does not require conditionals in `configuration.py`. The common orchestration and any packing strategy can then be reused. Placement is a separate concern handled by `PackingStrategy`. Existing YAML mode names and seed behavior are unchanged.

Configurations include a top-level `particle_generation` mapping. Other top-level sections may coexist for future modules; the current CLI only executes particle generation. See `examples/particles.yaml` for a complete working input, and `examples/fixed_box_fraction.yaml` and `examples/variable_box_fraction.yaml` for the other modes. Unknown options within the particle-generation section are rejected to catch spelling errors.

- `fixed_count`: requires `count` and `box.lengths`; generates positions in that fixed box. No target fraction.
- `fixed_box_fraction`: requires `target_solid_fraction` and `box.lengths`; determines the number of particles. Omit `count`.
- `variable_box_fraction`: requires `count`, `target_solid_fraction` and `box.lengths`; scales all three lengths equally, preserving their ratios and the origin. Input lengths describe the reference proportions; final dimensions are recorded in outputs.

For example, change the example to `mode: fixed_box_fraction`, remove `count` and add `target_solid_fraction: 0.05`. For the variable box mode, retain `count` and add the target.

Solid fraction is `sum(4*pi*r**3/3) / box_volume`, including overlapping particle volumes separately. It is a nominal material-volume fraction, not the geometric union fraction when overlaps exist. Material density and mass calculation belong to DEM setup, not particle generation. Fractions above one are allowed when overlap permits them; geometric feasibility is still checked by the selected packing strategy.

`solid_fraction_tolerance` defaults to `0.001` and is an absolute fraction tolerance, not a relative percentage. For fixed boxes, sample an unmodified prefix of radii and choose the particle count immediately below or above the target, whichever is closest (prefer fewer particles on a tie). Never resize a sphere to force the target. If neither meets tolerance, restart. An explicit list fixes all radii and count; its resulting fraction must meet tolerance. Exact targets may be impossible due to discrete volumes.

## Radius and speed distributions

The same distribution syntax applies to `radii`, `velocity` and `angular_velocity`, except that `explicit` is only supported for radii.

```yaml
# Choose one mapping for each field:
{type: constant, value: 0.001}
{type: uniform, min: 0.0005, max: 0.001}
{type: normal, mean: 0.001, std: 0.0002, min: 0.0005, max: 0.0015}
{type: lognormal, median: 0.001, sigma: 0.2, min: 0.0005, max: 0.002}
{type: explicit, values: [0.001, 0.0015, 0.002]}
```

Radii must be strictly positive. Normal and lognormal bounds are mandatory, and values outside the interval are rejected, never clipped. `mean` and `std` describe the underlying normal before truncation; `median` and dimensionless `sigma` describe the underlying lognormal (`sigma` is the standard deviation of the logarithm). Truncation changes the resulting statistics. Rejection has a safety limit of 1000 draws per value; extremely unlikely intervals fail with an explanatory message. Each distribution class owns its validation, sampling and normalized serialization, and is selected once through `DISTRIBUTIONS`. Distributions represent particle number, not mass fractions.

Velocity distributions specify nonnegative **magnitudes** in m/s and rad/s respectively. Each particle receives independent directions uniformly distributed over the sphere, for both linear and angular velocity. These directions are statistically isotropic; the finite sample is not adjusted to have exactly zero net momentum. Both fields default to `{type: constant, value: 0}`. Explicit radii must match `count` where provided.

## Placement and periodicity

`box.origin` defaults to `[0, 0, 0]`. `box.lengths` contains three positive lengths. `box.periodic` is one boolean for all three axes and defaults to false. Nonperiodic spheres remain entirely inside the box. Periodic centers lie in the primary box and spheres may cross its boundaries. Minimum-image distances are used, including a check against each sphere's own periodic images.

`max_overlap` is in `[0, 1]` and defaults to zero. For radii `ri`, `rj` and center distance `d`, the overlap measure is:

```text
min(1, max(0, ri + rj - d) / (2 * min(ri, rj)))
```

Zero prohibits penetration; one permits complete containment/coincidence. A value of 0.1 allows penetration equal to 10% of the smaller sphere's diameter. Tangency is allowed. There is no extra surface gap.

By default, positions use random sequential insertion, with larger spheres inserted first and original radius/ID ordering retained in outputs. A spatial hash checks only neighboring cells. `packing.position_attempts` defaults to 1000 per particle and is owned by the random sequential strategy. `restarts` defaults to 10 full restarts **after** the initial attempt (11 total attempts). Each restart draws new radii and positions. Exhaustion fails the run without exporting partial particle sets. `max_particles` defaults to 1,000,000 as a resource guard for target-based generation.

Random insertion cannot achieve all geometrically possible dense packings. It does not relax, compact or run DEM. Broad size distributions and dense configurations can increase runtime significantly.

## Packing strategies

Geometry `mode` and `packing.method` are independent choices: all three geometry modes work with all three packing methods. The coordinator determines final radii and box once per restart, builds a `PackingRequest` with the shared geometry, overlap constraint and random stream, and passes it to `PackingStrategy.pack`. Each strategy owns immutable typed options, constructs them with `from_config`, and emits its normalized effective mapping with `to_config`. Add a subclass and register it in `PACKING_STRATEGIES` to add a method. Packing never receives the global generation dictionary or modifies the supplied box or radii.

Omitting `packing` selects the existing method and preserves its positional random sequence:

```yaml
particle_generation:
  # Other geometry, distribution and seed inputs...
  packing:
    method: random_sequential
    position_attempts: 1000
```

Choose `method: overlap_relaxation` or `method: progressive_growth` for the new algorithms. Complete runnable configurations are provided in `examples/overlap_relaxation.yaml` and `examples/progressive_growth.yaml`.

### Overlap relaxation

All centers start at random positions and may initially violate overlap constraints. For each nearby pair, the solver computes the excess distance violation `e = max(0, ri + rj - 2*max_overlap*min(ri,rj) - distance)`. Each pair proposes equal and opposite separation displacements. The solver averages accumulated displacements by each particle's active neighbor count, multiplies by `step_size`, and caps each displacement relative to its radius. These are numerical displacements, not physical velocities or forces.

After each update, nonperiodic centers are projected into `[radius, box_length-radius]`; periodic centers wrap into the primary box. A SciPy cKDTree is rebuilt after every move. Neighbor queries are processed in blocks to limit memory use, with deterministic pair ordering. Coincident centers receive seeded isotropic separation directions. If progress stalls, bounded seeded perturbations restart relaxation from its best-energy configuration; exhaustion returns failure to the outer restart coordinator.

The diagnostic objective is the sum of squared distance excesses normalized by the smaller diameter. Updates are a damped geometric heuristic, not an exact energy-minimization solver; energy need not decrease on every iteration. Success requires the **maximum normalized excess** to be at most `overlap_tolerance`, not merely a small total energy. `max_overlap: 1` disables pair separation entirely, including containment of unequal spheres.

### Progressive growth

Final radii `R` are retained unchanged, while working radii start at `initial_scale * R`. The final box stays fixed throughout, including for `variable_box_fraction`. Initial centers are random and the first stage is relaxed. Growth then increases the common scale and calls the same relaxation function by composition. Scaling all radii together preserves their ratios; the temporary nominal fraction equals `scale**3 * final_fraction`.

Only converged stages are accepted. On failure, positions revert to the previous accepted stage and the attempted scale increment is halved. Stages that converge within one quarter of the iteration budget allow a 1.25x increment increase, capped by `max_increment`. The random stream is not rewound on rollback. Walls use the current working radii at each stage. Reaching the stage limit or falling below `min_increment` fails the attempt. The last step is clamped to exactly `1.0`; a packing at smaller radii is never exported as success.

### Controls and diagnostics

All controls below live inside `packing`. Unknown or method-inapplicable keys are rejected. The two relaxation-based methods share:

| Option | Default | Meaning |
| --- | --- | --- |
| `max_iterations` | 3000 | Update limit per relaxation call; per stage for growth |
| `step_size` | 1.0 | Multiplier for averaged pair corrections, in `(0, 1]` |
| `max_displacement` | 0.2 | Maximum displacement per update as a fraction of each working radius |
| `overlap_tolerance` | 1e-8 | Numerical excess allowed above `max_overlap`, normalized by the smaller diameter |
| `stagnation_iterations` | 200 | Updates without a sufficient energy improvement before perturbing |
| `improvement_tolerance` | 1e-6 | Required relative energy decrease to reset stagnation detection |
| `max_perturbations` | 3 | Maximum stagnation perturbations per relaxation call; zero disables them |
| `perturbation` | 0.01 | Perturbation magnitude as a fraction of each working radius |

Growth additionally accepts:

| Option | Default | Meaning |
| --- | --- | --- |
| `initial_scale` | 0.25 | Initial radius multiplier, strictly between zero and one |
| `initial_increment` | 0.05 | Initial increment of radius scale |
| `min_increment` | 0.0001 | Smallest increment allowed after a failed stage |
| `max_increment` | 0.1 | Maximum adaptive increment |
| `max_stages` | 200 | Total stage attempts, including initialization and rejected stages |

`min_increment <= initial_increment <= max_increment` is required. `restarts` and the shared `max_overlap` constraint remain at the `particle_generation` level; every algorithm-specific control lives inside `packing`. Full restart limits apply to all methods. Successful runs record the method, iteration counts, perturbations, final overlap audit and growth stage history in `summary.json` and HDF5 metadata. Failed runs preserve the effective controls and seed, but never export an unfinished packing.

With the default numerical tolerance, `max_overlap: 0` can leave residual penetrations up to `1e-8` of the smaller diameter for relaxation-based methods. This tolerance is independent of the solid-fraction tolerance. The final audit adds a small float64 roundoff allowance. The insertion method continues to reject candidates with any positive overlap.

These algorithms do not guarantee convergence at arbitrary target fractions, and do not establish mechanical equilibrium. Dense or broadly polydisperse systems can be expensive. Velocities are sampled independently after packing; material properties and DEM contact laws are never used.

## DEM separation and Kratos export

Particle generation takes no material properties, material IDs or contact law. `ParticleSet` contains only IDs, geometry, initial velocities, domain and generation metadata. Material assignment, mass/inertia calculation and contact-model selection belong to the future DEM module. The current CLI does not execute DEM or validate a `dem` section.

MDPA uses `SphericParticle3D` elements and free (not prescribed/fixed) nodal velocities. Its elements reference an **empty `Properties 1` block**, required to provide a valid Kratos model-part structure. This is an exporter-local placeholder, not a material assignment in the particle dataset. Assign physical properties and contact laws when preparing the DEM case, before simulation. The generator does not choose or export a default contact law.

The exported MDPA is a particle model part, **not a runnable DEM case**. Configure materials, contact laws, time stepping, walls and periodic domain in your Kratos case. Box lengths and periodicity are preserved in HDF5, VTK field data and the run summary; the MDPA alone does not activate periodic boundaries or create walls. A case's initialization may override imported velocities.

Older YAML configurations containing `particle_generation.material` must remove that entry or move it outside the particle-generation section. For example, a top-level `dem` section may preserve future simulation inputs, but it is not processed or saved in the generation run. The standard examples need no DEM settings; `particles_jugar.yaml` preserves its previous material values separately under `dem.material`.

## ParaView

Open `particles.vtp` and click Apply. Add a **Glyph** filter, choose **Sphere**, set **Scale Array** to `diameter`, **Scale Factor** to `1`, and **Glyph Mode** to **All Points**. Use a source sphere radius of `0.5` (unit diameter), with no orientation. The resulting glyphs have physical particle diameters. Color by `radius`, `id`, or velocity magnitude. The file stores centers and attributes, not tessellated sphere surfaces. Periodic copies are not duplicated in the visualization.

## Persistence and reproducibility

HDF5 schema `JPGen.particles`, version `2.0`, stores float64 positions/radii/velocities, int64 particle IDs, SI unit attributes, domain and generation metadata. Materials and contact laws are not part of this schema. Version `1.0` files are rejected explicitly; existing run files are left untouched. To regenerate them, remove or relocate the material section in their saved YAML and run the CLI again. Arrays are gzip compressed. The internal reader validates the schema and restores the same dataset; all runs export from the HDF5 readback.

Supply a nonnegative integer `seed`, or omit it to generate a 128-bit seed using the system random source. The actual seed is saved **before** generation. NumPy PCG64 streams derive from `SeedSequence(seed, spawn_key=(restart, role))`: radii=0, packing=1, speed=2, linear direction=3, angular speed=4, angular direction=5. The packing stream includes initialization, coincident-center separation and stagnation perturbations; algorithm iterations and failed growth stages consume this same deterministic stream. Changing speed settings does not consume positional randomness. Run names are unique filesystem identifiers and do not influence particle generation.

Replay requires the same effective configuration, generator version and dependency versions, which are saved per run. Numerical results are reproducible within that environment; identical files across library versions or platforms are not guaranteed. HDF5 files are not restart checkpoints of an evolving DEM simulation: contact history is outside this module's scope.

## Dense-packing benchmark

Run a bounded experiment with exactly 8,000 particles, nominal solid fraction 0.62, periodic boundaries, uniform radii from 0.5 to 1 mm, zero permitted geometric overlap and seed 20260916:

```bash
.venv/bin/python scripts/benchmark_dense_packing.py --method overlap_relaxation
.venv/bin/python scripts/benchmark_dense_packing.py --method progressive_growth
.venv/bin/python scripts/benchmark_dense_packing.py --method random_sequential
```

Each experiment uses `variable_box_fraction`, disables full restarts to measure one reproducible attempt, and defaults to a 300-second generation limit and 3,000 iterations per relaxation call. Override `--seconds`, `--iterations`, `--seed`, `--count`, `--overlap`, or `--fraction` as needed. For example, add `--overlap 0.15` to allow penetration up to 15% of the smaller sphere diameter. The benchmark uses POSIX interval timers (Linux/macOS). A timeout is an experiment limit, not proof that the requested geometry is impossible.

The run directory contains `benchmark.log` with timestamped progress and `benchmark.json` with elapsed time and completion/failure status, alongside the usual effective configuration and summary. Successful output is checked independently with an all-pairs overlap calculation and a recomputed volume fraction. Failed or timed-out generation does not export particle datasets. Wall-clock timings depend on competing system load; run methods sequentially for a controlled performance comparison.
