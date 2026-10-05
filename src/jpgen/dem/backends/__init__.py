"""Register engine metadata without importing optional execution dependencies."""
from .kratos.definition import DEFINITION as KRATOS
from .liggghts.definition import DEFINITION as LIGGGHTS

DEM_BACKENDS = {"kratos": KRATOS, "liggghts": LIGGGHTS}
