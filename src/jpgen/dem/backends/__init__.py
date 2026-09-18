"""Backend factories; plans retain the selected adapter after validation."""

from .kratos.backend import KratosBackend

DEM_BACKENDS = {"kratos": KratosBackend.from_config}
