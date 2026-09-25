# Building JPGen release wheels

JPGen release wheels contain both native components: the pybind11 C++ placement
extension and the pinned JPGen Kratos Core/DEM fork. The fork is based on Kratos
commit `66dbb226f80dc78d5ff3985351effb03798ad2b8`, plus
`vendor/kratos-dem-restart.patch`. The resulting commit is
`64c7b4eb9b5e70ce6fbfbc304715e2ece28f6790`. The build rejects another
revision or uncommitted Kratos source changes.

Build a separate wheel on every supported operating system, architecture and
CPython version. The current project metadata targets CPython 3.12. The
locally built and exercised artifact is Linux x86_64, CPython 3.12. macOS (Intel and Apple Silicon) and
Windows wheels must be built and checked on their own runners before release.
A Linux wheel cannot serve either of those systems.

## Source preparation

Install Git, CMake, a C++17 compiler, Python 3.12 development files, Boost,
Eigen, and the Python build dependencies from `pyproject.toml`. Kratos's
`INSTALL.md` documents platform-specific toolchain requirements. In
particular, its Windows build uses Visual Studio.

From the JPGen checkout:

```bash
python tools/prepare_kratos_source.py Kratos
python tools/build_release_wheel.py --source Kratos
```

The first command checks out the pinned Kratos base, applies the versioned
patch and verifies the exact fork commit. The second builds only Kratos Core
and DEM, installs them under `Kratos/bin/Release`, and creates the JPGen
wheel in `dist/`. If the pinned fork is already present at `Kratos/`, only
the second command is needed.

The wheel builder copies Kratos's Python modules as regular files, so the
absolute symlinks in a developer Kratos installation are not shipped. It
includes only the required Core/DEM shared libraries, license texts and the
source revision marker. It refuses to create a wheel if the C++ extension or
matching Kratos binaries cannot be built.

The Kratos install prefix can be supplied to a direct JPGen build with
`JPGEN_KRATOS_INSTALL`; its source checkout is set with
`JPGEN_KRATOS_SOURCE`. The source checkout must still be at the pinned
commit. Building from a JPGen source distribution requires preparing and
compiling this fork first.

## Release review

For each platform wheel, inspect the archive and install it in a clean
environment outside the source checkout. Confirm the native placement backend,
the `KRATOS-REVISION` marker, and a short DEM run using the bundled runtime.
Check binary library dependencies and platform compatibility tags. For broad
Linux compatibility, build in a suitable manylinux environment and repair
the wheel; for macOS and Windows, inspect and bundle the corresponding native
library dependencies. Ensure each uploaded file fits PyPI's size limit.

Publish only after Linux, macOS and Windows wheels for the advertised Python
version have passed these checks. Keep the Kratos Core and DEM license files
and `THIRD_PARTY_NOTICES.md` in every artifact.
