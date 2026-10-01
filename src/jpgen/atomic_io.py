"""Atomic file publication shared with standalone DEM workers."""

import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_path(path, *, mode=None):
    """Publish a completed, flushed temporary file; clean up after failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(descriptor)
    temporary = Path(name)
    try:
        yield temporary
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write(path, content, *, mode=None):
    with atomic_path(path, mode=mode) as temporary:
        temporary.write_bytes(content)


def atomic_text(path, value):
    atomic_write(path, value.encode("utf-8"))


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, indent=2, allow_nan=False) + "\n")


def atomic_copy(source, destination):
    with atomic_path(destination) as temporary:
        shutil.copyfile(source, temporary)
