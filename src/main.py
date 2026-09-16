"""JPGen command-line entry point."""

import argparse
import sys

from configuration import load_config
from particle_generation.application import build_application


def main():
    parser = argparse.ArgumentParser(description="JPGen: reproducible particle generation.")
    parser.add_argument("file_path", help="Path to the YAML configuration file")
    args = parser.parse_args()
    try:
        config = load_config(args.file_path)
        if "particle_generation" not in config:
            raise ValueError("Missing required configuration section: particle_generation.")
        build_application().run(config["particle_generation"])
    except (ValueError, OSError, KeyError, OverflowError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
