"""Read a YAML document; module-specific validation belongs to each module."""

from pathlib import Path

import yaml


def load_config(file_path):
    path = Path(file_path)
    if path.suffix.lower() not in (".yaml", ".yml"):
        raise ValueError("Input file must be a YAML file.")
    try:
        with path.open(encoding="utf-8") as file:
            content = yaml.safe_load(file)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML: {error}") from error
    if not isinstance(content, dict) or not content:
        raise ValueError("YAML configuration must be a nonempty mapping.")
    return content
