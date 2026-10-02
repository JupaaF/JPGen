# LIGGGHTS backend

The optional `liggghts` engine uses LIGGGHTS-PUBLIC 3.8.0, revision
`3d5c00f20519e6bb6eb6756f51f1ad36564e649d`, with the versioned JPGen native
extensions in `vendor/liggghts/`. The engine runs in an isolated worker process;
packing generation and protocols remain owned by JPGen. The native runtime is
separate from the Kratos runtime included in release wheels.

## Build and select

On Linux, install a C++ compiler, GNU Make and Git, then run from the repository:

```bash
python tools/build_liggghts.py --jobs 4
```

The builder downloads the official source if needed, verifies its pinned
revision, installs the extensions and builds a single-process shared library
with OpenMP, without MPI or VTK dependencies. `libliggghts_serial.json` records the revision,
extension hashes and library hash. Native sources are licensed GPL-2.0-or-later;
their license is included separately. The library is not bundled into JPGen
wheels. Windows builds are not currently provided.

Change the DEM engine and options of an existing configuration:

```yaml
dem:
  engine: liggghts
  backend_options:
    library: .deps/LIGGGHTS-PUBLIC/src/libliggghts_serial.so
    threads: 1
    # python: /path/to/python
    # timeout_seconds: 3600
  # Keep material, contact, boundary, gravity, time_step and protocol here.
```

`library` defaults to `JPGEN_LIGGGHTS_LIBRARY` when set, otherwise the path
shown above. Normalized configurations store an absolute library path. The
runtime probe requires JPGen extension ABI 3; rebuild with the command above
when upgrading from ABI 2. A stock LIGGGHTS or LAMMPS
library cannot silently substitute different contact physics.

## Supported physics and protocols

Open and periodic spheres, one elastic material, fixed time stepping, free
evolution, periodic strain rate and isotropic/anisotropic stress servos are
supported. Nested sequences and pressure paths use the portable protocol
runner. Particle states are exported at all stage/block boundaries. Full
retention additionally exports native restart files; analysis retention keeps
scientific states without restart archives. Density continuation, rollback,
and CLI resume are not advertised.

Periodic samples, stage exits and final results include `thermal_conductivity`
(a full 3×3 tensor) and `thermal_conductivity_trace` (trace divided by three).
They use the same dimensionless contact-geometry definition as Kratos: sum
the intersection-circle area times center distance times the outer product of
the contact direction, then divide by the current cell volume. Periodic branches
use the minimum image; contacts without positive overlap contribute zero.
This observable does not use temperatures or material thermal properties and
is not a conductivity in W/(m·K). Open-boundary runs omit it.

A manual 40-step comparison with Kratos used the same 12-particle packing,
unequal radii, a contact crossing the periodic boundary, an oblique contact,
and two repeated anisotropic compression/rest sequences. The final tensor
relative Frobenius difference was 5.33e-8; trace means were
3.553796315705843e-6 (LIGGGHTS) and 3.5537963161102023e-6 (Kratos).
Both engines recorded the tensor and trace mean in all 20 samples and the
final HDF5. Additional manual runs checked zero tensors without contacts,
fixed-duration execution without a protocol, and omission for open boundaries.
Deep artifact verification passed for all five runs. This short comparison
validates the added observable, not equivalence for every packing or protocol.

The contact adapter supports distinct static and dynamic friction with
`mu = mu_dynamic + (mu_static - mu_dynamic) * exp(-friction_decay * slip_speed)`.
Restitution accepts the full [0, 1] range. The Thornton fit clamps values below
0.001 to 0.001 and disables damping above 0.999, matching Kratos. Poisson ratio
accepts (-1, 0.5), including auxetic materials. JPGen validates these physical
ranges before the native runtime loads them.

`threads` accepts positive integers (default 1). OpenMP parallelizes particle
integration and affine cell deformation for at least 256 particles; smaller
loops execute serially to avoid overhead. The actual OpenMP team size is checked
and recorded as `versions.openmp_threads`. Contact evaluation and neighbour
search remain sequential; this is not a fully parallel contact solver and no
speedup proportional to the thread count is promised. The historical
`libliggghts_serial.so` filename is retained for configuration compatibility.

The ABI 3 changes were checked with ten pairs of manual Kratos/LIGGGHTS
simulations covering distinct friction coefficients, zero friction, zero friction
decay, restitution 0/0.01/0.05/0.5/1, and Poisson ratios from -0.9 to 0.499.
The largest relative kinetic-energy difference was 0.00369%; the largest
conductivity-tensor relative difference was 7.64e-9. A separate 20-step run
with the original 14,089-particle packing produced exactly equal particle arrays
and observables with one and four OpenMP threads. Its kinetic-energy difference
from Kratos was 0.00252%. Deep artifact verification passed for all 23 runs.
Two additional runs with restitution zero, negative Poisson ratio and four
threads checked open-boundary output and a periodic cell without contacts;
their artifact verification also passed.
See [the recorded validation results](liggghts-parity-validation.json) for
parameters, runtime hashes and run IDs. These short comparisons do not replace
a full equilibrium comparison for each material and protocol.

JPGen's `jpgen_hertz` normal model uses effective Young/shear moduli, Hertz
normal force, Thornton restitution-derived damping and nonnegative total normal
force, matching the definitions used by Kratos. `jpgen_history` stores elastic
tangential force, reduces it on unloading and applies Coulomb clipping to the
combined elastic/viscous tangential force. `jpgen/sphere` evaluates forces before
a full velocity kick and position drift, with direct angular velocity integration
and solid-sphere inertia. Rolling resistance and global damping are absent.
The stock LIGGGHTS Hertz/history model and velocity Verlet integration have
different semantics and are not used by this adapter.

Cell actuation uses symmetric affine position remapping while preserving the
live solver and contact history. Stress is the contact force/branch tensor
divided by cell volume, compression positive, without kinetic stress. Pressure
is its trace divided by three. Kinetic energy includes translation and rotation.
Unbalanced force is particle total-force RMS divided by contact-force RMS,
and zero without contacts. Contact force observations use LIGGGHTS's local
contact compute, which reevaluates forces at the completed-step geometry and
velocities without advancing tangential history. Kratos stores forces evaluated
during that step; the small time-level difference is included in comparisons.

Portable int64 particle IDs are mapped to consecutive native IDs and restored
on export. Particles, radii, velocities and initial geometry are transferred with
17 significant digits. Periodic state positions are canonicalized. A particle
loss is an execution error.

## Artifacts and standalone execution

Inputs are under `stages/dem/backend/liggghts/input/`, native outputs under
`backend/liggghts/native/` and native restart archives under
`backend/liggghts/checkpoints/`. Common HDF5 results, state archives and JSONL
indices use the same contracts as Kratos. `runtime.json` records the actual
library SHA-256; the execution report records the engine version and extension ABI.
Readers do not need the LIGGGHTS runtime.

Prepared cases include the portable Python modules and can run independently:

```bash
python <run>/stages/dem/backend/liggghts/input/run.py --output-dir /path/to/fresh/stages/dem
```

The original library must remain available. In-place reruns are rejected.

## Numerical comparison

Run the requested 14,089-particle configuration using one initial packing:

```bash
PYTHONPATH=src .venv/bin/python scripts/compare_dem_backends.py \
  --config examples/characterization/particle_count_log/particles_14089.yaml \
  --kratos-installation Kratos/bin/Release \
  --output-dir runs/backend-comparison-14089
```

The source example omits the seed; the script uses seed 42 when creating a
packing. `--packing /path/to/packing.h5` instead reuses one immutable initial
state. `--kratos-run` and `--liggghts-run` accept completed existing runs, checking
that particle arrays, geometry and physical DEM configuration are identical.
The script preserves the full two-stage protocol, including the 0.001 force
imbalance threshold and 0.001 s hold, and uses analysis retention.

`comparison.json` records raw values, differences, engine versions, input
checks and explicit tolerances. Default relative margins are 0.5% for pressure,
0.1% for solid fraction/density, 0.5% for coordination, 1% for the stress tensor
Frobenius norm and 0.5% for the fabric tensor norm. These are acceptance limits,
not claims of achieved equivalence. Energy and force-balance residuals near zero
are reported in absolute terms. Particle displacement is also reported in metres
and relative to median diameter, using periodic fractional coordinates. Both
force-balance residuals must be below 0.001 and normalized kinetic energies must
differ by at most 1e-6 (relative to pressure times volume). A failed
margin produces a nonzero exit code and retains the numerical report.
