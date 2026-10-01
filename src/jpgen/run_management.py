"""Explicit recovery and non-destructive import of legacy run directories."""

import json
import shutil
from pathlib import Path

import yaml

from .run_reader import RunReader, read_jsonl
from .run_repository import (FileRunRepository, RunWorkspace, atomic_json, file_hash,
                             rebuild_catalog, relative_path, utc_now)


def recover_run(directory):
    """Called explicitly after the user has stopped the original process."""
    reader = RunReader(directory)
    workspace = RunWorkspace(reader.directory)
    manifest = reader.manifest
    integrity = reader.verify(deep=True)
    if integrity['errors']:
        raise ValueError(f"Recorded artifacts changed; recovery will not replace their hashes: {integrity['errors']}")
    if manifest['status'] == 'running':
        manifest.update(status='interrupted', finished_at=utc_now(), updated_at=utc_now(),
                        error={'type': 'InterruptedRun', 'message': 'Explicitly recovered after process exit.'})
        for stage in manifest['stages'].values():
            if stage['status'] in {'running', 'pending'}:
                stage['status'] = 'interrupted' if stage['status'] == 'running' else 'skipped'
                stage['finished_at'] = utc_now()
                path = relative_path(workspace.directory, stage['summary'])
                summary = json.loads(path.read_text())
                summary['status'] = stage['status']
                atomic_json(path, summary)
        atomic_json(workspace.directory / 'run.json', manifest)
    # Readback reconciles an atomic move interrupted before inventory publication.
    from .packing.persistence import Hdf5PackingStore
    from .dem.persistence import Hdf5DemResultStore
    for relative, role, store in (
        ('stages/packing/results/packing.h5', 'packing', Hdf5PackingStore()),
        ('stages/dem/results/final.h5', 'dem_final', Hdf5DemResultStore()),
    ):
        path = workspace.directory / relative
        if path.exists():
            store.load(path)
            workspace.register([(relative, role, 'validated')])
    workspace.finalize()
    return workspace.read_manifest()


def import_legacy(source, root, *, label=None):
    """Copy an old run, preserving original files and marking unknown provenance."""
    source, root = Path(source).resolve(), Path(root).resolve()
    if root == source or root.is_relative_to(source):
        raise ValueError('Import destination must be outside the source run.')
    if (source / 'run.json').exists():
        raise ValueError('This is already a versioned run; copy its directory instead.')
    configuration = yaml.safe_load((source / 'configuration.yaml').read_text(encoding='utf-8'))
    summary = json.loads((source / 'summary.json').read_text(encoding='utf-8'))
    def status(value):
        return 'completed' if value == 'complete' else 'interrupted' if value == 'running' else value
    summary['status'] = status(summary['status'])
    for name in ('packing', 'dem'):
        if name in summary:
            summary[name]['status'] = status(summary[name]['status'])
            if 'accepted_states_index' in summary[name]:
                summary[name]['accepted_states_index'] = 'stages/dem/results/states.jsonl'
    workspace = FileRunRepository(root).create(configuration, summary, requested=configuration,
                                               metadata={'label': label or 'imported-run'})
    try:
        archive = workspace.directory / 'provenance/legacy'
        # Do not follow external symlinks when importing an archived run.
        if any(path.is_symlink() for path in source.rglob('*')):
            raise ValueError('Legacy import requires regular files, without symbolic links.')
        shutil.copytree(source, archive)
        from .packing.persistence import Hdf5PackingStore
        from .dem.persistence import Hdf5DemResultStore
        files = {}
        with workspace.stage_outputs() as staging:
            if (source / 'packing.h5').exists():
                Hdf5PackingStore().load(source / 'packing.h5')
                shutil.copyfile(source / 'packing.h5', staging / 'packing.h5')
                files['packing.h5'] = ('stages/packing/results/packing.h5', 'packing')
            if (source / 'dem/results.h5').exists():
                Hdf5DemResultStore().load(source / 'dem/results.h5')
                shutil.copyfile(source / 'dem/results.h5', staging / 'final.h5')
                files['final.h5'] = ('stages/dem/results/final.h5', 'dem_final')
            for name in ('particles.vtp', 'particlesDEM.mdpa'):
                if (source / name).exists():
                    shutil.copyfile(source / name, staging / name)
                    files[name] = ('stages/packing/exports/' + name, 'export')
            if files:
                workspace.publish(staging, files)
        if 'packing_source' in configuration and (workspace.directory / 'stages/packing/results/packing.h5').exists():
            configuration['packing_source'].update(file='../stages/packing/results/packing.h5',
                sha256=file_hash(workspace.directory / 'stages/packing/results/packing.h5'))
            workspace.save_configuration(configuration)
        _import_legacy_dem(source, workspace)
        atomic_json(workspace.directory / 'provenance/sources.json', {'sources': [{
            'relationship': 'imported_legacy_run', 'original_path': str(source),
            'archive': 'provenance/legacy', 'unknown': ['original_run_id', 'execution_timestamps', 'branch_identity'],
        }]})
        manifest = workspace.read_manifest()
        manifest.update(imported_at=utc_now(), started_at=None, finished_at=None)
        for stage in manifest['stages'].values():
            stage.pop('started_at', None)
            stage.pop('finished_at', None)
        atomic_json(workspace.directory / 'run.json', manifest)
        workspace.finalize()
    except BaseException as error:
        workspace.save_summary({'status': 'failed', 'error': {'type': type(error).__name__, 'message': str(error), 'stage': 'import'}})
        raise
    return workspace.directory


def _import_legacy_dem(source, workspace):
    from .dem.output_writer import StageOutput
    from .dem.state_exchange import read_state
    native = source / 'dem/native_results'
    if not native.exists():
        return
    store = StageOutput(workspace.directory / 'stages/dem', engine='legacy')
    converted = {}
    seen = set()
    for index in ('snapshots.jsonl', 'accepted_states.jsonl'):
        for item in read_jsonl(native / index):
            signature = json.dumps(item, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            origin = source / 'dem' if item.get('kind') == 'density_target' else native
            old = relative_path(origin, item['state'])
            if old not in converted:
                state = read_state(old.parent, old.name)
                converted[old] = store.state(source=old, time=state['time'], box=state['box'])
            record = {**item, **converted[old], 'branch_id': None, 'attempt_id': None,
                      'checkpoint_capabilities': {'analysis': True, 'rollback': False, 'resume': False}}
            for field in ('restart', 'metadata'):
                if item.get(field):
                    target = relative_path(origin, item[field]).relative_to(source)
                    record[field] = (Path('provenance/legacy') / target).as_posix()
            store.boundary(record)
    if (native / 'final_state.json').exists() and (native / 'final_state.npz').exists():
        state = read_state(native)
        saved = store.state(source=native / 'final_state', time=state['time'], box=state['box'])
        store.boundary({**saved, 'kind': 'legacy_final', 'phase': 'end', 'branch_id': None,
                        'attempt_id': None, 'validation': 'exchange_complete'})
    has_attempts = (native / 'density_attempts.jsonl').exists() and (native / 'density_attempts.jsonl').stat().st_size > 0
    for item in read_jsonl(native / 'observables.jsonl'):
        store.sample({**item, 'branch_id': None, 'attempt_id': None,
                      'legacy_branch_unknown': has_attempts})
    for item in read_jsonl(native / 'density_attempts.jsonl'):
        store.append(store.execution / 'attempts.jsonl', {**item, 'branch_id': None, 'attempt_id': None})


def main(argv):
    import argparse
    parser = argparse.ArgumentParser(prog='jpgen runs', description='Inspect and manage versioned runs')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('list', 'index'):
        command = commands.add_parser(name)
        command.add_argument('root', nargs='?', default='runs')
    for name in ('show', 'export', 'recover', 'verify'):
        command = commands.add_parser(name)
        command.add_argument('directory')
        if name == 'verify':
            command.add_argument('--deep', action='store_true', help='Validate scientific arrays, metadata and state references')
    command = commands.add_parser('compare')
    command.add_argument('left')
    command.add_argument('right')
    command = commands.add_parser('import')
    command.add_argument('source')
    command.add_argument('--output-dir', default='runs')
    command.add_argument('--label')
    command = commands.add_parser('label')
    command.add_argument('directory')
    command.add_argument('label')
    command.add_argument('--tag', action='append', default=None)
    args = parser.parse_args(argv)
    if args.command in {'list', 'index'}:
        result = rebuild_catalog(args.root)
    elif args.command == 'show':
        result = RunReader(args.directory).manifest
    elif args.command == 'verify':
        result = RunReader(args.directory).verify(deep=args.deep)
    elif args.command == 'compare':
        result = RunReader(args.left).compare(args.right)
    elif args.command == 'export':
        result = str(RunReader(args.directory).export_view())
    elif args.command == 'recover':
        result = recover_run(args.directory)
    elif args.command == 'import':
        result = str(import_legacy(args.source, args.output_dir, label=args.label))
    else:
        if not args.label.strip():
            raise ValueError('Label must not be empty.')
        reader = RunReader(args.directory)
        reader.manifest.update(label=args.label, updated_at=utc_now())
        if args.tag is not None:
            reader.manifest['tags'] = args.tag
        atomic_json(reader.directory / 'run.json', reader.manifest)
        reader.export_view()
        rebuild_catalog(reader.directory.parent)
        result = reader.manifest
    print(json.dumps(result, indent=2, allow_nan=False))
    return 1 if args.command == "verify" and result["errors"] else 0
