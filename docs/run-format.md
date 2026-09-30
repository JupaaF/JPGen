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
- Structured `error` when applicable; `retention` storage policy.

A completed run has met its configured stop criteria, which do not necessarily
establish equilibrium. A failed or cancelled run can have useful validated
packing and accepted targets. Filesystem presence alone does not prove successful
DEM completion. A hard kill leaves `running` until explicitly recovered.

Use `jpgen runs label <run> "New name" --tag reference` to update presentation
metadata without renaming the directory or altering physics. `--tag` replaces
existing tags in this command; generation accepts repeatable `--tag` options.
`JPGenApplication.run` exposes `label`, `tags`, `experiment_id`, and `retention`
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
status for missing or changed files. Before recovery, stop the original process:

```bash
jpgen runs recover runs/<run>
```

Recovery is explicit: it does not infer liveness from timestamps or another
machine's PID, and does not resume simulation. It updates abandoned stages,
reconciles HDF5 outputs, inventories partial diagnostics and rebuilds projections.

## States, events and branches

`stages/dem/results/states.jsonl` is the common state/event index. Records use
`schema: JPGen.dem.record`, `schema_version: "1.0"`, and contain:

- Monotonic worker `sequence`, `state_id`, `state` (NPZ/JSON stem).
- `kind`, `phase`, protocol `path` or `stage`, simulation `time`.
- `step` (total attempted steps); `physical_step` where available.
- `branch_id`, stage-local `attempt_id`, optional `target` and `accepted`.
- Optional `restart`, target `metadata`, and checkpoint capabilities.

Simultaneous boundaries, density acceptance and finalization reuse the same state
at the same attempted step. `exchange_complete` means the array/metadata pair has
been published, not that a physical acceptance condition passed. A target is
accepted only when its event says so. Diagnostic final states never substitute
for the application's validated `final.h5`.

`results/observables.jsonl` contains sample records. `execution/attempts.jsonl`
records attempt starts, acceptance, discard and target acceptance;
`execution/events.jsonl` records rollback destinations. The event sequence spans
these streams; branch IDs distinguish work after retry and attempt changes.
Attempt numbers are local to a protocol stage and must be paired with its path.
Physical time can go backwards, so neither time nor physical step identifies a
state uniquely. Parent-branch and rollback events preserve execution history.

`RunReader.series()` excludes discarded and pending attempts by default. Use
`include_discarded=True` to inspect all work, with a `disposition` on each sample.
Missing observables remain missing. The metrics dictionary records SI units and
physical meaning, including compression-positive contact pressure and nominal
solid fraction. Unknown legacy branch membership is never presented as accepted.

Checkpoints stay under `backend/kratos/checkpoints/`. Ordinary boundary restarts
support analysis only; complete density checkpoints support internal rollback.
Neither provides CLI resume. `--retention analysis` skips ordinary restarts and
removes internal checkpoints after execution, including after handled failure;
it preserves common states, target metadata, logs and native diagnostics. Full
retention is the default. Hard-killed runs apply retention during explicit recovery.
The backend's input `run.py` refuses in-place execution a second time. Pass
`--output-dir /new/path` to execute a copied case in a fresh standalone stage
folder. Standalone solver execution produces stage artifacts; it does not create
a new JPGen run manifest or publish validated HDF5 results. Use the JPGen CLI
with the effective YAML when a complete new run is wanted.

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
preserved as the imported requested configuration. Unknown density branches are
available through diagnostic series queries. Import may duplicate substantial
data to preserve the original byte record. Symlinks are rejected.
