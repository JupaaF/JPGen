# Building JPGen release wheels

The optional LIGGGHTS adapter is included as Python code. Its GPL native runtime
is built separately with `tools/build_liggghts.py` and is not copied into release
wheels. See [LIGGGHTS setup](liggghts.md).

JPGen release wheels contain both native components: the pybind11 C++ placement
extension and the pinned JPGen Kratos Core/DEM fork. The fork is based on Kratos
commit `66dbb226f80dc78d5ff3985351effb03798ad2b8`, plus
`vendor/kratos-dem-restart.patch` and `vendor/kratos-neighbour-optimizations.patch`.
The resulting commit is `b0bdba096f0cce09a0a520afb08e070cb1d4d33c`. The build rejects another
revision or uncommitted Kratos source changes.

Build a separate wheel on every supported operating system, architecture and
CPython version. The initial release targets Linux x86_64 and Windows x86_64
on CPython 3.12. Both wheels must be installed and exercised on their own
platform before release. A Linux wheel cannot serve Windows.

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

The first command fetches the declared Kratos base commit directly, applies the
versioned patches and verifies the latest JPGen fork revision recorded in
`vendor/kratos-revision.txt`. It does not follow a moving upstream branch or
require the JPGen fork to be public. Updating the JPGen fork means updating
the base revision, patch series and resulting revision together. The second builds only Kratos Core
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
the wheel. On Ubuntu 22.04, install `patchelf` 0.19.1.0 from PyPI for
`auditwheel` 6.8.2; the distribution package is too old. For Windows,
inspect and bundle the corresponding native library dependencies.
`delvewheel` must search `Kratos/bin/Release/libs` for Kratos Core/DEM DLLs.
Its repaired DLLs live in `jpgen.libs`; the bundled Kratos worker adds that
directory to its Windows DLL search path. Ensure each uploaded file fits PyPI's
size limit.

Publish only after Linux and Windows wheels for the advertised Python version
have passed these checks. Keep the Kratos Core and DEM license files
and `THIRD_PARTY_NOTICES.md` in every artifact.

## Validate existing Actions artifacts

The `Validate JPGen wheels` workflow downloads the artifacts from a successful
`Build JPGen wheels` run. It runs automatically after successful builds, and
can also be started from Actions with an optional build `run_id`. Leaving that
input empty selects the latest successful build on `master`. Changes to the
validation workflow on `master` also trigger validation of existing artifacts.

Each Linux/Windows runner creates a fresh Python 3.12 virtual environment,
installs the wheel with its dependencies, and runs `pip check`. It requires
the native C++ placement backend, reports the bundled Kratos revision, imports
the fork's density restart marker, and executes a two-particle packing and a
short DEM simulation. It does not check out JPGen or build Kratos; all native
code must come from the downloaded wheel.

Download the `validation-jpgen-linux-x86_64` and
`validation-jpgen-windows-x86_64` artifacts to review `report.json`, the input
configuration and execution outputs. The report records the source build run,
wheel SHA256, platform, Python version and execution summary. Check that both
validation jobs passed for the exact build being released. A successful wheel
build alone does not establish that the installed package works.

## Publishing a release

The initial PyPI publication contains **only Linux x86_64 and Windows x86_64
wheels for CPython 3.12**. No source distribution is uploaded: the current
`setup.py` needs a prepared, compiled copy of the pinned Kratos fork to build a
wheel, so an sdist would not provide the usual direct `pip install` experience.
The complete JPGen source, Kratos base revision and patch remain available in
the GitHub repository and its release tag. Unsupported platforms and Python
versions will receive no matching distribution from PyPI.

`Release JPGen` is a manually started workflow. It downloads the already built
wheels and their clean-install validation reports. It checks the release tag,
source commit, package version, artifact names, wheel hashes, bundled Kratos
revision, licenses and completed packing/DEM results. It uploads exactly those
wheel files to PyPI and then attaches the same files plus a SHA256 manifest to
a GitHub Release. The workflow does not rebuild them.

Prepare the first release as follows:

1. Push the release changes to `master` and wait for `Build JPGen wheels` and
   its subsequent `Validate JPGen wheels` run to succeed. Record both run IDs.
2. In GitHub repository Settings → Environments, create `pypi` and require a
   reviewer for deployments to it. Register a PyPI [pending trusted
   publisher](https://pypi.org/manage/account/publishing/) for project `jpgen`,
   owner `JupaaF`, repository `JPGen`, workflow `release.yml`, environment
   `pypi`. If `jpgen` is already registered to an account you control, add this
   publisher to that project's Publishing settings instead. The pending
   publisher does not reserve the name until the first upload.
3. Tag the **same commit as the successful build** with `v0.5.0`, then push the
   tag. For example, after checking `git rev-parse HEAD` against the build's
   `head_sha`, use `git tag -a v0.5.0 -m "JPGen 0.5.0"` and
   `git push origin v0.5.0`.
4. On GitHub Actions → `Release JPGen` → Run workflow, select `master` and enter
   `v0.5.0`, the build run ID and the validation run ID. Review the `verify`
   job and approve the `pypi` environment deployment. The later GitHub Release
   job runs only if PyPI publication succeeds.
5. Install from PyPI in fresh Linux and Windows Python 3.12 environments with
   `python -m pip install --only-binary=:all: jpgen==0.5.0` and check `jpgen`
   starts. Check that the two wheels and release manifest appear on GitHub
   Releases. Publication is irreversible for a given version and wheel
   filename; a fix requires a new version.

PyPI's default per-file limit is 100 MB. The build and release workflows reject
larger wheels. A pending publisher or GitHub environment must be configured by
an account owner before this workflow can publish. GitHub Actions artifacts
expire; GitHub Releases and PyPI are the permanent download locations.
