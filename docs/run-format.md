# Run format 1.0

A run is a portable scientific record. Directory names are for humans; the UUID
in `run.json` is its identity. Each invocation creates a new directory and never
resumes or overwrites an existing run. The layout and common indices belong to
JPGen, independently of the solver. Existing packing and DEM HDF5 schemas remain
unchanged; their locations have changed.

## Identity and lifecycle

`run.json` (`schema: JPGen.run`, `schema_version: "1.0"`) contains:

- `run_id`, editable `label`, `tags`, optional `experiment_id`.
- UTC `created_at`, `started_at`, `updated_at`, `finished_at` timestamps.
- `status`: `running`, `completed`, `failed`, `cancelled`, or `interrupted`.
- `stages`: per-stage status, timestamps and summary reference. Stages can also
  be `pending` or `skipped`. Unconfigured stages are absent.
- `configuration`, `artifacts`, `provenance`: root-relative references.
- `results`: availability of packing, validated final DEM, observables, number
  of distinct saved states and accepted targets, refreshed at finalization.
- Structured `error` when applicable.

A completed run has met its configured stop criteria, which do not necessarily
establish equilibrium. A failed or cancelled run can have useful validated
packing and accepted targets. Filesystem presence alone does not prove successful
DEM completion. A hard kill leaves `running` until explicitly recovered.

Use `jpgen runs label <run> "New name" --tag reference` to update presentation
metadata without renaming the directory or altering physics. `--tag` replaces
existing tags in this command; generation accepts repeatable `--tag` options.
`JPGenApplication.run` exposes `label`, `tags`, `experiment_id`
keyword arguments for programmatic callers.

## Configuration and provenance

`config/requested.yaml` is the parsed configuration received by the application
(comments and original formatting are not preserved). `config/effective.yaml`
contains resolved defaults and the actual seed. A reused packing points to
`../stages/packing/results/packing.h5`, with the hash of that snapshot. Loading
this file through `load_config` resolves the source relative to the config file;
ordinary user YAML files retain launch-directory path semantics.

`provenance/sources.json` records the original source path and hash, local
snapshot, source run UUID and artifact path when available. `uses_packing` does
not mean continuing the previous DEM solver. `environment.json` records dependency
versions, platform and selected placement implementation. Engine versions remain
in the DEM report. External interpreters/runtime installations must still exist
or be configured for the destination machine; portable data do not bundle an OS.

## Artifact publication and integrity

`artifacts.json` (`JPGen.artifacts`, version `1.0`) lists `artifact_id`, root-relative
`path`, `role`, `format`, `size_bytes`, `sha256`, `availability`, and `validation`.
Artifact IDs derive from run UUID and path. Scientific HDF5 outputs are read back
before atomic file moves and inventory publication; an error before inventory
commit rolls back moved outputs. A process kill between moves can leave unlisted
files. `recover` read-validates these HDF5 files before reconciling the inventory.

Native diagnostics, logs and complete state pairs are inventoried after process
exit. Their hashes establish byte integrity, not physical validity. `validated`
is reserved for outputs validated by the application. `not_validated` diagnostics
are still inspectable. Live readers can follow the common JSONL streams directly;
the closed-file inventory is not a live progress feed. `run.json` and the inventory
itself are not recursively hashed. `view/` is derived and excluded from inventory.

All index references are relative to the run root, regardless of the location of
the referencing JSON file. Reader path resolution rejects directory escape.
Published scientific outputs are immutable. Mutable lifecycle/summary files use
atomic replacement, and JSONL records commit on the terminating newline. An
incomplete final line is ignored; malformed complete lines are errors. Atomic
replacement protects against process interruption, not a guarantee of durability
across power loss on every filesystem.

`jpgen runs verify <run>` checks recorded file hashes and returns a nonzero exit
status for missing or changed files. Add `--deep` to validate HDF5 particle and
domain units, array invariants, NPZ/JSON state pairs, index identity and time,
checkpoint references and accepted density target metadata. Saved-state readers
perform these state checks too, and omit incomplete pairs from listings.
Recovery requires deep verification before reconciling outputs.
Before recovery, stop the original process:

```bash
jpgen runs recover runs/<run>
```

Recovery is explicit: it does not infer liveness from timestamps or another
machine's PID, and does not resume simulation. It updates abandoned stages,
reconciles HDF5 outputs, inventories partial diagnostics and rebuilds projections.

## States and events

`stages/dem/results/states.jsonl` uses the common `JPGen.dem.record` schema,
version `1.0`. Each event has a sequence, state identity and NPZ/JSON stem,
kind, phase, stage path, time and step. All paths are relative to the run root.
Simultaneous events reuse a scientific state rather than duplicating arrays.

Density stages save `density_checkpoint` events with `phase: before_reset`,
cycle, normal friction coefficients and stable observables. Accepted goals are
`density_target` events with `accepted: true`, a scalar target and `.target.json`
metadata (`JPGen.dem.target`, version `1.1`). Acceptance is one-sided:
`solid_fraction + density_atol >= target`, after normal-friction stabilization.
No native restart files or internal solver checkpoints are written. The former
`--retention` option is removed; scientific checkpoints are always preserved.

New NPZ/JSON snapshots use `JPGen.dem.state` version `1.1`. They retain the
particle arrays and add a per-contact table, including at protocol boundaries,
density checkpoints/targets and the final or diagnostic snapshot. Readers also
accept version `1.0`; absent contact data in those archives remain unavailable.
The JSON `contacts` mapping documents the engine, force evaluation time level,
geometry time level, vector conventions and units. NPZ members are:

| Member | Shape | Dtype | Meaning |
| --- | --- | --- | --- |
| `contact_ids` | M × 2 | int64 | Original particle IDs, first < second, unique sorted pairs |
| `contact_branches` | M × 3 | float64 | First center minus second center, minimum image for periodic cells (m) |
| `contact_normals` | M × 3 | float64 | Unit branch directions at the saved geometry |
| `contact_overlaps` | M | float64 | Radius sum minus center distance at the saved geometry (m) |
| `contact_forces` | M × 3 | float64 | Total contact force on the first particle by the second (N) |
| `contact_normal_forces` | M × 3 | float64 | Normal component of that force (N) |
| `contact_tangential_forces` | M × 3 | float64 | Tangential component of that force (N) |

All vectors use global Cartesian coordinates. Force components include the
constitutive elastic and viscous contributions after Coulomb limiting; their
sum is the total. The force on the second particle is the negative of the
stored force. Empty tables have the same shapes with M = 0. Readers validate
IDs, shapes, dtypes, finite values, force sums and agreement of contact geometry
with the particles and box.

Kratos exports native stored forces with `force_time_level: step_force_evaluation`.
These precede the completed-step position/velocity update, so their native
normal/tangential decomposition need not align exactly with the saved geometric
normal. Its table includes native contact elements with positive snapshot
overlap or nonzero stored force, retaining opening contacts that contributed
during the step. Initial Kratos boundaries use `initial_uncomputed`: native
forces have not yet been evaluated and zero values are initialization values.
LIGGGHTS uses `completed_step_reevaluation`: active native contacts and forces
are observed at completed-step geometry/velocities without advancing history.
Geometry always has `geometry_time_level: snapshot`.

`RunReader.load_state` returns the table as `state["contacts"]` and its
description as `state["contact_metadata"]` for version `1.1`. For example, to
remove a selected group from the instantaneous contact analysis:

```python
import numpy as np

state = run.load_state(accepted[0]["state_id"])
contacts = state["contacts"]
removed_ids = np.array([12, 34], dtype=np.int64)
keep = ~np.isin(contacts["ids"], removed_ids).any(axis=1)
remaining_contacts = {name: values[keep] for name, values in contacts.items()}
```

This preserves the recorded forces between retained particles; it does not
predict a new equilibrium after removal. No contact history or restart state
is serialized. The common `final.h5` schema remains unchanged; use the indexed
final NPZ/JSON snapshot for its per-contact data.

`results/observables.jsonl` contains sampled numeric measurements. Density samples
also include `density_phase` and `cycles` outside the numeric observables mapping.
Time and step increase monotonically; there are no rejected or restored branches.
Historical imported runs may still have unknown or discarded branch metadata,
which the reader preserves for analysis.

MCN, Fabric and periodic contact-geometry conductivity retain their previous
meaning and units. `thermal_conductivity` and its trace mean are dimensionless
geometry measures, not thermal transport coefficients in W/(m·K). Missing
observables remain missing. Stress is compression-positive contact stress and
solid fraction counts overlapping sphere volumes separately.

Standalone input `run.py` refuses in-place execution a second time. Use
`--output-dir /new/path` for a fresh standalone execution. This creates stage
artifacts; use the JPGen CLI with the effective YAML to create a complete run.

## Reader and browser data

```python
from jpgen.run_reader import RunReader

run = RunReader("runs/<run>")
manifest = run.manifest
changes = run.compare("runs/<other>")
accepted = run.states(accepted_only=True)
state = run.load_state(accepted[0]["state_id"])
samples = run.series()
run.export_view(max_points=2000)
```

Configuration differences include presence flags and categories (`physics`,
`packing`, `protocol`, `execution`, `exports`). They report actual normalized
configuration differences, not a claim of numerical equivalence. Large integer
seeds and particle IDs are strings in browser JSON to avoid JavaScript precision
loss; scientific arrays retain int64/float64.

`view/summary.json` contains manifest, summaries and metric definitions;
`view/states.json` contains the common state index; `view/series/observables.json`
contains an explicitly sampled series; `view/previews/packing.json` contains a
bounded initial-geometry preview. Series use uniform stride, retain endpoints,
and are not suitable for extrema detection. Use full scientific samples for
analysis. Missing or stale projections can be regenerated with `jpgen runs export`.
The format supplies data for a future HTML interface; no HTML application is
included. A local service can use the reader directly, or a static site generator
can consume these JSON projections without loading HDF5 in the browser.

`jpgen runs index <root>` rebuilds `catalog.json` from child manifests.
`jpgen runs list <root>` does the same and prints it. Catalogs are disposable
snapshots, not transactional databases; concurrent runs may leave a stale cache.
Readers can refresh it at discovery time. Unsupported or malformed manifests are
reported in the catalog's `errors` rather than silently hidden.

## Legacy import

```bash
jpgen runs import /old/run --output-dir runs --label archived-compression
```

Import creates a new UUID and never modifies the source. Original files are
copied to `provenance/legacy/`; supported HDF5 results and state pairs are validated
and exposed in the new layout. Old native checkpoint references point into the
preserved archive. Unsupported HDF5 schemas are rejected explicitly; no numerical
conversion is attempted. Imported creation time means import time; unavailable
execution timestamps and branch identities are marked unknown, never invented.
The old requested YAML is unavailable, so the legacy effective configuration is
preserved as the imported requested configuration. Historical density samples are preserved in the archive. Import may duplicate substantial
data to preserve the original byte record. Symlinks are rejected.
