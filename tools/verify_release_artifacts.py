"""Verify previously built and installed wheels before a manual release.

The caller downloads the two build artifacts and two validation reports from
specified Actions runs. This script checks their provenance and contents; it
never builds or uploads a distribution.
"""

import argparse
from email.parser import Parser
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


EXPECTED = {
    "linux": ("jpgen-linux-x86_64", r"jpgen-{version}-cp312-cp312-manylinux_.*_x86_64\.whl"),
    "windows": ("jpgen-windows-x86_64", r"jpgen-{version}-cp312-cp312-win_amd64\.whl"),
}
KRATOS_REVISION = (Path(__file__).resolve().parents[1] / "vendor/kratos-revision.txt").read_text().strip()


def github_json(path):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "JPGen-release-verification",
    }
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def resolve_tag(tag):
    ref = github_json(f"git/ref/tags/{tag}")
    obj = ref["object"]
    if obj["type"] == "tag":
        obj = github_json(f"git/tags/{obj['sha']}")["object"]
    require(obj["type"] == "commit", "Release tag must point to a commit")
    return obj["sha"]


def run(run_id, workflow):
    data = github_json(f"actions/runs/{run_id}")
    require(data["path"].split("@", 1)[0].endswith(f".github/workflows/{workflow}"),
            f"Run {run_id} is not from {workflow}")
    require(data["status"] == "completed" and data["conclusion"] == "success",
            f"Run {run_id} did not finish successfully")
    return data


def artifact(run_id, name):
    artifacts = github_json(f"actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    matches = [a for a in artifacts if a["name"] == name and not a["expired"]]
    require(len(matches) == 1, f"Expected one unexpired {name} artifact in run {run_id}")
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build-run", required=True, type=int)
    parser.add_argument("--validation-run", required=True, type=int)
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    require(os.environ["GITHUB_REPOSITORY"] == "JupaaF/JPGen", "Unexpected GitHub repository")
    require(os.environ.get("GITHUB_REF") == "refs/heads/master", "Release must run from master")
    require(args.build_run > 0 and args.validation_run > 0, "Run IDs must be positive")
    require(re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", args.tag), "Tag must be vMAJOR.MINOR.PATCH")
    version = args.tag[1:]
    source_version = re.search(
        r'^__version__\s*=\s*"([^"]+)"',
        (Path(__file__).resolve().parents[1] / "src/jpgen/__init__.py").read_text(),
        flags=re.MULTILINE,
    )
    require(source_version and source_version.group(1) == version,
            "Release tag must match the source package version")
    sha = resolve_tag(args.tag)
    require(sha == os.environ["GITHUB_SHA"], "Tag must point to the checked-out master commit")
    build = run(args.build_run, "build-wheels.yml")
    run(args.validation_run, "validate-wheels.yml")
    require(build["head_sha"] == sha, "Build commit does not match the release tag")

    manifest = {"tag": args.tag, "commit": sha, "build_run_id": args.build_run,
                "validation_run_id": args.validation_run, "kratos_revision": KRATOS_REVISION,
                "wheels": {}}
    expected_names = set()
    for platform, (artifact_name, name_pattern) in EXPECTED.items():
        wheel_artifact = artifact(args.build_run, artifact_name)
        report_artifact = artifact(args.validation_run, f"validation-{artifact_name}")
        wheels = list((args.wheel_dir / platform).glob("*.whl"))
        require(len(wheels) == 1, f"Expected one {platform} wheel")
        wheel = wheels[0]
        require(re.fullmatch(name_pattern.format(version=re.escape(version)), wheel.name),
                f"Unexpected {platform} wheel name: {wheel.name}")
        require(wheel.stat().st_size < 100_000_000, f"Wheel exceeds PyPI file limit: {wheel.name}")
        with zipfile.ZipFile(wheel) as archive:
            require(archive.testzip() is None, f"Corrupt wheel: {wheel.name}")
            names = set(archive.namelist())
            metadata = archive.read(f"jpgen-{version}.dist-info/METADATA").decode("utf-8")
            runtime = "jpgen/_kratos_runtime/"
            for name in ("KRATOS-REVISION", "KRATOS-CORE-LICENSE.txt",
                         "KRATOS-DEM-LICENSE.txt", "KRATOS-ZLIB-NOTICE.txt"):
                require(runtime + name in names, f"Missing {name} in {wheel.name}")
            require(archive.read(runtime + "KRATOS-REVISION").decode().strip() == KRATOS_REVISION,
                    f"Wrong Kratos revision in {wheel.name}")
            require(f"jpgen-{version}.dist-info/licenses/LICENSE" in names and
                    f"jpgen-{version}.dist-info/licenses/THIRD_PARTY_NOTICES.md" in names,
                    f"Missing project license files in {wheel.name}")
            native_suffix = ".pyd" if platform == "windows" else ".so"
            require(any(name.startswith("jpgen/packing/placement/_kernels.") and
                        name.endswith(native_suffix) for name in names),
                    f"Missing native placement module in {wheel.name}")
            for component in ("KratosCore", "KratosDEMCore"):
                require(any(name.startswith(runtime + "libs/") and component in name and
                            name.endswith(".dll" if platform == "windows" else ".so")
                            for name in names), f"Missing {component} in {wheel.name}")
        fields = Parser().parsestr(metadata)
        require(fields["Name"] == "jpgen" and fields["Version"] == version,
                f"Wheel metadata mismatch: {wheel.name}")
        report_path = args.report_dir / platform / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        checksum = hashlib.sha256(wheel.read_bytes()).hexdigest()
        require(str(report["build_run_id"]) == str(args.build_run), "Validation used another build")
        require(report["wheel"] == wheel.name and report["sha256"] == checksum,
                f"Validation does not match the {platform} wheel bytes")
        summary = report["summary"]
        require(summary["status"] == "completed" and summary["packing"]["status"] == "completed"
                and summary["dem"]["status"] == "completed", f"{platform} execution incomplete")
        require(summary["dem"]["versions"]["kratos_source_revision"] == KRATOS_REVISION,
                f"{platform} used a different Kratos fork")
        require(summary["packing"]["count"] == 2 and summary["dem"]["steps"] == 2,
                f"{platform} execution did not run the expected scenario")
        expected_names.add(wheel.name)
        manifest["wheels"][platform] = {
            "name": wheel.name, "sha256": checksum, "size": wheel.stat().st_size,
            "build_artifact_id": wheel_artifact["id"],
            "validation_artifact_id": report_artifact["id"],
        }
    all_wheels = {p.name for p in args.wheel_dir.rglob("*.whl")}
    require(all_wheels == expected_names, "Unverified wheel present")
    output = args.wheel_dir / "release-manifest.json"
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, urllib.error.HTTPError, zipfile.BadZipFile) as error:
        print(f"Release verification failed: {error}", file=sys.stderr)
        sys.exit(1)
