"""Command-line interface for the JPGen pipeline."""

import argparse
import logging
import sys

from .application import build_application
from .configuration import load_config
from .configuration_wizard import build_configuration_wizard
from .progress import ConsoleProgressObserver, LoggingProgressObserver

MISSING_FILE_MESSAGE = (
    "Error: a YAML configuration file is required when JPGen is not running in "
    "an interactive terminal. Provide one with 'jpgen FILE.yaml', or run 'jpgen' "
    "from an interactive terminal to start the configuration wizard."
)


def _progress_observer(mode):
    if mode == "console":
        return ConsoleProgressObserver()
    if mode == "logging":
        logging.basicConfig(level=logging.INFO)
        return LoggingProgressObserver()
    return None


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "runs":
        from .run_management import main as runs_main
        try:
            return runs_main(sys.argv[2:])
        except (ValueError, OSError, KeyError) as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser(
        description="JPGen: particle packing and DEM simulation pipeline."
    )
    parser.add_argument("file_path", nargs="?", help="Path to the YAML configuration file")
    parser.add_argument(
        "--progress",
        choices=("console", "logging", "none"),
        default="console",
        help="Progress destination (default: console)",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory for run results (default: ./runs)",
    )
    parser.add_argument("--label", help="Human-readable run label")
    parser.add_argument("--tag", action="append", default=[], help="Run tag (repeatable)")
    parser.add_argument("--experiment", help="Experiment identifier for grouping runs")
    parser.add_argument("--retention", choices=("full", "analysis"), default="full",
                        help="Retain native checkpoints (full) or analysis results only")
    args = parser.parse_args()
    generated = None
    try:
        if args.file_path is None:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                print(MISSING_FILE_MESSAGE, file=sys.stderr)
                return 2
            generated = build_configuration_wizard().run()
            if generated is None:
                return 0
            args.file_path = generated.path
        build_application(args.output_dir).run(
            load_config(args.file_path),
            observer=_progress_observer(args.progress),
            label=args.label, tags=args.tag, experiment_id=args.experiment, retention=args.retention,
        )
    except (ValueError, OSError, KeyError, OverflowError) as error:
        _rollback(generated)
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if generated is None:
            raise
        return 130
    except Exception:
        _rollback(generated)
        raise
    return 0


def _rollback(generated):
    if generated is None:
        return
    try:
        generated.rollback()
    except OSError as error:
        print(f"Error restoring configuration file: {error}", file=sys.stderr)
