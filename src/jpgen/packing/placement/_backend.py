"""Select optional native kernels once, without changing the packing config."""

import importlib
import os


requested = os.environ.get("JPGEN_PLACEMENT_BACKEND", "auto")
if requested not in {"auto", "python", "native"}:
    raise ValueError("JPGEN_PLACEMENT_BACKEND must be auto, python or native.")

native = None
if requested != "python":
    module_name = f"{__package__}._kernels"
    try:
        native = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name != module_name:
            raise
        if requested == "native":
            raise ImportError("Native placement kernels are unavailable; rebuild JPGen with a C++ compiler.") from error

name = "native" if native is not None else "python"
