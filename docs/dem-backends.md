# Adding a DEM engine

The application owns the physical case, protocol and common results. Engines
translate that case, execute it and collect `DemState`; they must reject physics
they cannot represent. Adding an engine does not require editing the DEM wizard.

## Registration and optional imports

Add an adapter package under `jpgen/dem/backends/` and a lightweight description:

```python
from jpgen.dem.backends.base import DemCapabilities
from jpgen.dem.backends.registry import BackendDefinition

CAPABILITIES = DemCapabilities(
    boundaries=frozenset({"open"}),
    controls=frozenset({"free_evolution"}),
    observables=frozenset({"kinetic_energy"}),
    contact_models=frozenset({"hertz_viscous_coulomb"}),
    integration_schemes=frozenset({("symplectic_euler", "direct")}),
)

DEFINITION = BackendDefinition(
    label="Example engine",
    factory="my_engine.backend:Backend.from_config",
    capabilities=CAPABILITIES,
    wizard="my_engine.wizard:EngineWizard",
    physics="Describe the actual contact, integration and observable semantics here.",
)
```

Set `particle_snapshots=True` only when the backend exports the particle state
at every protocol boundary: entry and exit of each leaf stage and each repetition
of a sequence block. A backend without this capability is rejected for protocols
before execution. The snapshots are analysis outputs; this flag does not promise
solver restart or rollback. Kratos writes one `JPGen.dem.state` archive per unique
boundary step under `dem/native_results/snapshots/` and records all boundary
events in `snapshots.jsonl`. Other engines may use their own storage format but
must provide equivalent particle and box data and identify the associated events.

Pressure paths use the ordinary portable `stress_servo` command for each
resolved target. A backend advertising pressure control, pressure/energy/force
observables and particle snapshots can run the path; successful target exits
must be distinguishable from failed diagnostic boundaries. Kratos publishes
accepted exits through `accepted_states.jsonl`.

Density continuation additionally requires `state_restore`,
`contact_parameter_updates`, `contact_history_checkpoint`, `rollback`,
`target_publication` and `native_restart_export`. `DemContinuationPort` provides
checkpoint, restore, live-friction and publication operations. Kratos advertises
these only with the JPGen DEM restart patch: runtime preflight checks its
version marker. Its density checkpoint stores all DEM model parts, cell geometry,
active friction and portable controller state. A failed increment reloads a fresh
analysis from that checkpoint while keeping attempt counters in the worker.
Neighbour search runs every density step, and the derived contact measurement
mesh is rebuilt after reload. A checkpoint is also published for each accepted
target. Restarting the CLI from an earlier run is not implemented.

`native_restart_export` is a separate optional capability. Kratos advertises it
and writes the native `SpheresPart.rest` for every unique protocol boundary step,
using the same `FileSerializer` and pointer serialization flag as its restart
utility. `restart.json` stores the step, time, box and Kratos version. The
`snapshots.jsonl` event records the corresponding `.rest` path. This capability
only promises export of native solver files; it does not advertise a JPGen resume
or rollback operation on its own. A future backend may produce a different native format,
and a backend without this capability can still export particle snapshots.

These capabilities are illustrative: advertise them only if the engine actually
implements the requested physics. Register the definition in `DEM_BACKENDS`.
The description and package `__init__.py` must not import the engine runtime,
execution adapter or interactive dependencies. Factories and wizard providers
are imported only when used. The backend class should reuse `CAPABILITIES`.

Implement `DemBackend` (`to_config`, `validate`, `prepare`, `run`, `collect`).
`validate` checks runtime availability and any additional engine restrictions.
Portable capability validation runs during plan construction, before execution.
Programmatic callers can still inject a mapping of backend factories into
`DemApplication`/`build_dem_plan`; the interactive wizard needs descriptions.

An `EngineWizard` implements `questions(answers)` and `build(answers)` using the
existing `Question` API. Namespace its answer keys, e.g. `dem.example.python`.
`build` returns only `backend_options`. For an engine without special options,
return an empty question list and an empty options mapping. `DemStageWizard`
handles engine selection, material, contact, integration, gravity and protocols.
It filters engines by boundary, and choices by declared capabilities; final
validation also rejects unsupported options in imported protocols.

## Physics and configuration

`Material` currently represents one isotropic elastic material for all spheres.
`CONTACT_MODELS` registers each portable contact law separately: its configuration
factory, numeric wizard parameters and physical meaning. A specification implements
`Contact` (`model` and `to_config`) and can have its own fields; the common parser
no longer forces every law to accept Hertz viscous Coulomb parameters. The factory
must validate its model-specific fields. Registering another model makes it
available to engines that explicitly advertise it.

The current `hertz_viscous_coulomb` law requests Hertz normal elasticity,
restitution-derived viscous contact damping and elastic tangential response
limited by Coulomb friction. Friction transitions exponentially with slip speed
from static to dynamic using `friction_decay` in s/m. Rolling resistance and global
damping are disabled. A similar native law is not sufficient if it changes these
semantics: reject the case or introduce a separately named portable model.

Integration is an explicit pair, preserved in normalized configurations:

```yaml
integration:
  translation: symplectic_euler
  rotation: direct
```

Omitting it selects this pair for compatibility with existing configurations.
Capabilities declare supported pairs, rather than two independent lists that
could permit an unsupported combination. Kratos maps this pair to
`Symplectic_Euler` and `Direct_Integration`.

Document damping, integration and observable definitions in the engine's
`physics` description. Portable kinetic energy includes translation and rotation.
Stress is contact force/branch stress, compression positive, without kinetic
stress. Pressure is its trace divided by three. Different engines need not produce
identical trajectories, but must implement the requested meaning or reject it.
Time stepping is fixed; configurations must supply a finite positive scalar.

## Protocol actuation

Controllers return immutable commands from `dem/commands.py`:

- `NoActuation`: advance without changing the current cell; no actuator capability
  is required, including for open-boundary evolution.
- `CellStrainRate`: three logarithmic strain rates in 1/s, expansion positive;
  requires `cell_strain_rate`.
- `SymmetricWallVelocity`: three opposing-face velocities in m/s, compression
  positive; requires `symmetric_wall_velocity`.

The latter commands validate three finite values at construction. Adapters
translate these commands to their engine API and reject unknown commands.
`DemControlPort` documents the live interface. `time` and `stage_time` are supplied
by `ProtocolRunner`, so engines need not implement their measurement.

Kratos copies `protocol.py`, `commands.py` and its adapter into the
standalone case. Other process-based engines must also ship their required portable
modules, or arrange an explicit runtime dependency on JPGen.

Kratos also copies the solver-independent `dem/state_exchange.py` module. Its
`JPGen.dem.state` version `1.0` exchange consists of `final_state.npz` and a small
`final_state.json` metadata file (schema, version, SI units, time and box).
The NPZ archive stores `ids` as int64 and `positions`, `radii`, `velocities` and
`angular_velocities` as float64 NPY members, without compression or pickle.
`write_state` consumes arrays sequentially in that order and publishes metadata
after the archive; `read_state` checks the schema, member names and dtypes.
Adapters remain responsible for constructing `DemState` and normalizing native
results. `DemApplication` validates every execution report and final state against
the case through `dem/validation.py`, before publishing results. The shared checks
cover successful completion, step and completed stage counts, final time, boundary
type and preservation of particle IDs and radii. Particle ordering may differ
between engines; radii are compared by ID. An omitted final box means the initial
box; adapters that deform the domain must provide its final geometry. Other
workers can reuse this format without importing Kratos.
Old particle-valued JSON exchange files are not accepted by the new collector;
the public `results.h5` format is unchanged. Diagnostic final state on protocol
timeout uses the same binary exchange.

## Kratos observations

Each completed protocol step still evaluates stopping conditions. `observe` accepts
the set of requested observables; adapters must return current measurements for
those names. Controllers request only the measurements they use: pressure for
isotropic stress control, and normal stresses for anisotropic control. The adapter
uses `SphericElementGlobalPhysicsCalculator.CalculateTranslationalKinematicEnergy`
and `CalculateRotationalKinematicEnergy`, summed in joules. These run reductions
in Kratos C++/OpenMP rather than visiting nodes in Python. The runtime preflight
checks these methods. The fixed sphere volume is obtained once through
`CalculateTotalVolume`; current cases do not add/remove particles or change radii.
Any future support for those operations must invalidate that cached volume.
The dimensionless `unbalanced_force` observable uses Kratos'
`ContactElementGlobalPhysicsCalculator.CalculateUnbalancedForceWithinSphere`
over the complete particle assembly. It is the particle total-force RMS divided
by the contact-force RMS, and Kratos returns zero when the contact-force RMS is
zero. Protocols that request it keep contact elements current on every step.
`sample_every` controls output only; it does not reduce condition evaluation.

Energy, force-balance and stress reductions run only when required by the active
stage or by an output sample/stage exit. Contact updates remain enabled for
protocols with force-balance or stress conditions so exit measurements remain
current. Cell deformation uses
`VariableUtils` bulk reads/writes with NumPy array arithmetic. The maximum
particle radius is cached alongside solid volume; both require invalidation if
future features change radii or particle population.
