"""Command-line interface for the JPGen pipeline."""

import argparse
import sys

from .application import build_application
from .configuration import load_config


def main():
    parser = argparse.ArgumentParser(
        description="JPGen: particle packing and DEM simulation pipeline."
    )
    parser.add_argument("file_path", help="Path to the YAML configuration file")
    args = parser.parse_args()
    try:
        build_application().run(load_config(args.file_path))
    except (ValueError, OSError, KeyError, OverflowError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0
