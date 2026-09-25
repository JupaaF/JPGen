"""Locate the Kratos DEM runtime shipped with the JPGen wheel."""

from pathlib import Path


def bundled_installation() -> Path | None:
    directory = Path(__file__).resolve().parent / "_kratos_runtime"
    if (directory / "KratosMultiphysics" / "__init__.py").is_file() and (
        directory / "libs"
    ).is_dir():
        return directory
    return None


def bundled_revision() -> str | None:
    directory = bundled_installation()
    if directory is None:
        return None
    marker = directory / "KRATOS-REVISION"
    return marker.read_text(encoding="utf-8").strip() if marker.is_file() else None
