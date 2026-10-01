"""YAML rendering and recoverable publication of wizard output."""

import stat
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..atomic_io import atomic_write


class WizardYamlDumper(yaml.SafeDumper):
    """Render optional null settings as empty YAML values."""


def _represent_empty_none(dumper, _value):
    return dumper.represent_scalar("tag:yaml.org,2002:null", "")


WizardYamlDumper.add_representer(type(None), _represent_empty_none)


def render_yaml(configuration):
    return yaml.dump(
        configuration,
        Dumper=WizardYamlDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )


@dataclass
class GeneratedConfiguration:
    """A published YAML file that can restore the path's previous state."""

    path: Path
    original_content: bytes | None
    original_mode: int | None

    @classmethod
    def publish(cls, path, content):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        original_content = path.read_bytes() if path.exists() else None
        original_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
        atomic_write(path, content.encode("utf-8"), mode=original_mode)
        return cls(path, original_content, original_mode)

    def rollback(self):
        if self.original_content is None:
            self.path.unlink(missing_ok=True)
            return
        atomic_write(self.path, self.original_content, mode=self.original_mode)
