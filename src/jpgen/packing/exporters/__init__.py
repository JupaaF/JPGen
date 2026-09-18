"""Packing output adapters and the available user-facing formats."""

from .kratos import KratosExporter
from .vtk import VtkExporter


PACKING_EXPORTER_TYPES = {
    "vtk": VtkExporter,
    "kratos": KratosExporter,
}


def build_packing_exporters():
    return {name: exporter_type() for name, exporter_type in PACKING_EXPORTER_TYPES.items()}
