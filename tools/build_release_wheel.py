"""Build the pinned Kratos DEM runtime, then package JPGen for this host."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command, *, env=None):
    print("+", *map(str, command), flush=True)
    subprocess.run([str(part) for part in command], check=True, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "Kratos")
    parser.add_argument("--parallel", type=int, default=max(1, os.cpu_count() or 1))
    parser.add_argument("--wheel-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    source = args.source.resolve()
    expected = (ROOT / "vendor/kratos-revision.txt").read_text().strip()
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != expected:
        raise SystemExit(f"Kratos revision mismatch: expected {expected}, got {actual}")
    build = source / "build" / "Release"
    install = source / "bin" / "Release"
    environment = os.environ.copy()
    environment.update(
        PYTHON_EXECUTABLE=sys.executable,
        KRATOS_APPLICATIONS=str(source / "applications" / "DEMApplication"),
        KRATOS_INSTALL_PYTHON_USING_LINKS="OFF",
        JPGEN_KRATOS_SOURCE=str(source),
        JPGEN_KRATOS_INSTALL=str(install),
    )
    cmake_command = [
        "cmake", "-S", source, "-B", build,
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_INSTALL_PREFIX={install}",
        "-DUSE_MPI=OFF", "-DUSE_EIGEN_MKL=OFF",
        "-DKRATOS_GENERATE_PYTHON_STUBS=OFF",
    ]
    if environment.get("CMAKE_TOOLCHAIN_FILE"):
        cmake_command.append(
            f"-DCMAKE_TOOLCHAIN_FILE={environment['CMAKE_TOOLCHAIN_FILE']}"
        )
    run(cmake_command, env=environment)
    run(
        ["cmake", "--build", build, "--config", "Release", "--target", "install",
         "--parallel", str(args.parallel)],
        env=environment,
    )
    run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "--wheel-dir", args.wheel_dir.resolve(), ROOT],
        env=environment,
    )


if __name__ == "__main__":
    main()
