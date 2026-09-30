"""Read the pipeline configuration; each stage validates its own section."""

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
    # Run configurations resolve their portable packing snapshot relative to themselves.
    # User YAML files retain the historical launch-directory path semantics.
    if path.name == "effective.yaml" and (path.parent.parent / "run.json").is_file():
        source = content.get("packing_source")
        if source and not Path(source["file"]).is_absolute():
            source["file"] = str((path.parent / source["file"]).resolve())
    return content
