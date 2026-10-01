"""Recreate the latest JPGen Kratos revision declared by the vendored patches."""

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/KratosMultiphysics/Kratos.git"


def git(*args, cwd=None):
    return subprocess.check_output(["git", *map(str, args)], cwd=cwd, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    destination = args.destination.resolve()
    base = (ROOT / "vendor/kratos-base-revision.txt").read_text().strip()
    expected = (ROOT / "vendor/kratos-revision.txt").read_text().strip()
    patches = [ROOT / "vendor/kratos-dem-restart.patch",
               ROOT / "vendor/kratos-neighbour-optimizations.patch"]
    if destination.exists():
        raise SystemExit(f"Destination already exists: {destination}")
    # Fetch the declared public base itself, even after its branch has advanced.
    # JPGen's latest fork is reconstructed locally; it need not be published.
    git("init", destination)
    git("remote", "add", "origin", UPSTREAM, cwd=destination)
    git("fetch", "--depth", "1", "origin", base, cwd=destination)
    git("checkout", "--detach", base, cwd=destination)
    subprocess.run(
        [
            "git", "-c", "user.name=Juan Pablo Fernandez",
            "-c", "user.email=jpfernandez@cimne.upc.edu",
            "am", "--committer-date-is-author-date", *map(str, patches),
        ],
        cwd=destination,
        check=True,
    )
    actual = git("rev-parse", "HEAD", cwd=destination)
    if actual != expected:
        raise SystemExit(f"Kratos revision mismatch: expected {expected}, got {actual}")
    print(f"Prepared Kratos {actual} at {destination}")


if __name__ == "__main__":
    main()
