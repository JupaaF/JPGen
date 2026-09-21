"""Register engine metadata without importing optional execution dependencies."""
from .kratos.definition import DEFINITION

DEM_BACKENDS = {"kratos": DEFINITION}
