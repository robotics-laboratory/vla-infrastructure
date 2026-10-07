#!/usr/bin/env python3
"""Read-only checks of the declared Linux core and two frozen Isaac installations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from urllib.parse import unquote, urlparse

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
# Registered migration REPORT.md records the count of six retained incompatibilities;
# the exact isaac61 set below was observed read-only on 2026-10-07. Legacy's full
# baseline is configs/environments/isaac_release_3_0_0.yaml. These are metadata
# exceptions, not a claim of vendor ABI compatibility or new physical qualification.
# Compare complete uv diagnostics, including installed versions and marker clauses.
COMMON_CONFLICTS = {
    "numba requires numpy>=1.22,<2.5, but 2.5.1 is installed",
    "cmeel-boost requires numpy>=2.3,<2.4 ; python_full_version >= '3.11', but 2.5.1 is installed",
    "isaacsim-kernel requires numpy==2.3.1, but 2.5.1 is installed",
    "open3d requires ipywidgets>=8.0.4, but it's not installed",
}
EXPECTED_CONFLICTS = {
    "core": set(),
    "isaac61": COMMON_CONFLICTS
    | {
        "isaacsim-core requires newton[sim]==1.5.0, but 1.5.2 is installed",
        "isaacsim-robot requires onnxruntime-gpu==1.26.0, but it's not installed",
    },
    "legacy": COMMON_CONFLICTS
    | {
        "isaacsim-core requires mujoco==3.8.0, but 3.11.0 is installed",
        "isaacsim-core requires mujoco-warp==3.8.0.3, but 3.11.0 is installed",
        "isaacsim-core requires newton[sim]==1.2.1, but 1.5.1 is installed",
        "isaacsim-core requires newton-usd-schemas==0.2.0, but 0.4.1 is installed",
        "isaacsim-kernel requires websockets==12.0, but 16.1.1 is installed",
        "isaacsim-kernel requires typing-extensions==4.12.2, but 4.16.0 is installed",
        "isaacsim-kernel requires coverage==7.4.4, but 7.15.2 is installed",
    },
}
PROBE = """
import importlib.metadata as m,json,platform,sys
packages = {}
origins = {}
for d in m.distributions():
    name = d.metadata['Name'].lower().replace('_','-').replace('.','-')
    packages[name] = d.version
    direct = d.read_text('direct_url.json')
    if direct:
        origins[name] = json.loads(direct)
decoder = None
if sys.argv[1] == 'core':
    try:
        from torchcodec.decoders import VideoDecoder
        decoder = {'passed': True, 'class': VideoDecoder.__name__}
    except Exception as exc:
        decoder = {'passed': False, 'error': str(exc)}
print(json.dumps(dict(python=platform.python_version(), platform=sys.platform,
    machine=platform.machine(), prefix=sys.prefix, executable=sys.executable,
    packages=packages, origins=origins, decoder=decoder)))
"""


def run(arguments: list[str], *, environment: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(arguments, env=environment, text=True, capture_output=True, check=False)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_identity(probe: dict, expected_prefix: Path | None = None) -> list[str]:
    errors = []
    if probe["python"] != "3.12.13":
        errors.append(f"Python differs: {probe['python']}")
    if probe["platform"] != "linux" or probe["machine"] not in ("x86_64", "AMD64"):
        errors.append("This checker requires the declared Linux x86_64 environment")
    if expected_prefix is not None and Path(probe["prefix"]).resolve() != expected_prefix.resolve():
        errors.append("Interpreter prefix differs from the selected Isaac installation")
    return errors


def check_core_versions(root: Path, probe: dict, with_teleop: bool) -> list[str]:
    project = tomllib.loads((root / "pyproject.toml").read_text())
    lock = tomllib.loads((root / "uv.lock").read_text())
    requirements = project["project"]["dependencies"] + project["dependency-groups"]["dev"]
    if with_teleop:
        requirements += project["dependency-groups"]["isaac-teleop"]
    names = {canonicalize_name(Requirement(item).name) for item in requirements}
    names.update(("numpy", "torch", "torchcodec"))
    errors = []
    for name in sorted(names):
        candidates = [
            p
            for p in lock["package"]
            if canonicalize_name(p["name"]) == name
            and (
                not p.get("resolution-markers")
                or any(Marker(marker).evaluate() for marker in p["resolution-markers"])
            )
        ]
        if len(candidates) != 1:
            errors.append(f"No unique current-platform lock version for {name}")
            continue
        package = candidates[0]
        if probe["packages"].get(name) != package["version"]:
            errors.append(
                f"{name}: installed {probe['packages'].get(name)!r}, locked {package['version']}"
            )
        editable = package["source"].get("editable")
        if editable is not None:
            origin = probe["origins"].get(name, {})
            url = urlparse(origin.get("url", ""))
            if (
                url.scheme != "file"
                or url.netloc not in ("", "localhost")
                or not origin.get("dir_info", {}).get("editable")
                or Path(unquote(url.path)).resolve() != (root / editable).resolve()
            ):
                errors.append(f"{name}: editable origin differs from this checkout")
    if not probe["decoder"] or not probe["decoder"]["passed"]:
        errors.append("torchcodec.decoders import failed")
    return errors


def parse_conflicts(result: subprocess.CompletedProcess) -> set[str]:
    output = result.stdout + result.stderr
    conflicts = {
        line.removeprefix("The package ").replace("`", "")
        for line in output.splitlines()
        if line.startswith("The package ")
    }
    if result.returncode not in (0, 1) or (result.returncode == 1 and not conflicts):
        raise RuntimeError(f"uv pip check failed without dependency diagnostics: {output}")
    return conflicts


def check_conflicts(name: str, observed: set[str]) -> list[str]:
    expected = EXPECTED_CONFLICTS[name]
    return [f"Unexpected metadata conflict: {item}" for item in sorted(observed - expected)] + [
        f"Retained metadata conflict changed/absent: {item}" for item in sorted(expected - observed)
    ]


def check(name: str, python: str, with_teleop: bool, root: Path = ROOT) -> dict:
    environment = os.environ.copy()
    environment.update(
        PYTHONDONTWRITEBYTECODE="1",
        UV_CACHE_DIR=environment.get("UV_CACHE_DIR", "/tmp/vla-dependency-check-uv-cache"),
    )
    fingerprints = {}
    stack = None
    if name != "core":
        from tools.isaac_demo_launch import verify_stack

        stack = verify_stack(name)
        python = str(stack["environment"] / "bin/python")
        fingerprints = {
            "sdk_commit": stack["commit"],
            "uv_lock_sha256": stack["lock"],
            "pyproject_sha256": stack["pyproject"],
        }
    result = run([python, "-I", "-c", PROBE, name], environment=environment)
    if result.returncode:
        raise RuntimeError(f"Interpreter probe failed: {result.stderr}")
    probe = json.loads(result.stdout)
    errors = check_identity(probe, stack["environment"] if stack else None)
    if name == "core":
        fingerprints = {
            "uv_lock_sha256": sha256(root / "uv.lock"),
            "pyproject_sha256": sha256(root / "pyproject.toml"),
        }
        errors += check_core_versions(root, probe, with_teleop)
        environment["UV_PROJECT_ENVIRONMENT"] = probe["prefix"]
        locked = run(
            [
                "uv",
                "lock",
                "--project",
                str(root),
                "--python",
                python,
                "--no-managed-python",
                "--check",
                "--offline",
            ],
            environment=environment,
        )
        if locked.returncode:
            errors.append(
                f"Core lock differs from project spec: {(locked.stdout + locked.stderr).strip()}"
            )
        frozen = run(
            [
                "uv",
                "sync",
                "--project",
                str(root),
                "--python",
                python,
                "--no-managed-python",
                "--frozen",
                "--offline",
                "--dry-run",
            ]
            + (["--group", "isaac-teleop"] if with_teleop else []),
            environment=environment,
        )
        output = frozen.stdout + frozen.stderr
        if frozen.returncode or "Would make no changes" not in output:
            errors.append(f"Core installed closure differs from frozen spec: {output.strip()}")
    conflicts = parse_conflicts(
        run(["uv", "pip", "check", "--python", python], environment=environment)
    )
    errors += check_conflicts(name, conflicts)
    fingerprints["checker_sha256"] = sha256(Path(__file__))
    return {
        "environment": name,
        "passed": not errors,
        "errors": errors,
        "scope": "Package/spec identity and metadata checks; no vendor ABI or physical qualification",
        "fingerprints": fingerprints,
        "installed": probe,
        "conflicts": sorted(conflicts),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=tuple(EXPECTED_CONFLICTS), default="core")
    parser.add_argument(
        "--python", default=sys.executable, help="Core interpreter; Isaac uses verified SDK"
    )
    parser.add_argument(
        "--with-teleop", action="store_true", help="Check the optional core Gate B group"
    )
    args = parser.parse_args()
    try:
        report = check(args.environment, args.python, args.with_teleop)
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        report = {"environment": args.environment, "passed": False, "errors": [str(exc)]}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
