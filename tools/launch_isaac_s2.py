#!/usr/bin/env python3
"""Launch Gate S2 through the accepted Candidate B/S1 production path."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path("/data/vla-infrastructure")
QUALIFICATION = STORAGE / "isaaclab_candidate_qualification/20260907"
LAB = QUALIFICATION / "candidate_b_exact"
ENVIRONMENT = STORAGE / "envs/isaac-s1-candidate-b"
LAB_COMMIT = "913ac53f51b2f8d02c9e121caa4cbdd06262948e"
ASSET_COMMIT = "f6642ce0d7872c686f29c99e9e10cd23d1d49313"
LAB_PYPROJECT_SHA256 = "b691862409ab8ad58b074ac32ce7f071e3895ec10975444b9e62995741ace159"
LAB_LOCK_SHA256 = "80eb2c4e1155dd9e9736506d41cdbe327df74ee2b005bdecc0fb7c87c8b8bb84"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify() -> None:
    for checkout, expected in (
        (LAB, LAB_COMMIT),
        (STORAGE / "assets/agx_arm_urdf", ASSET_COMMIT),
    ):
        actual = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(checkout), "status", "--porcelain"], text=True
        )
        if actual != expected or dirty:
            raise RuntimeError(f"expected clean pinned checkout {expected}: {checkout}")
    for path, expected in (
        (LAB / "pyproject.toml", LAB_PYPROJECT_SHA256),
        (LAB / "uv.lock", LAB_LOCK_SHA256),
    ):
        if _sha256(path) != expected:
            raise RuntimeError(f"Candidate B frozen workspace hash mismatch: {path}")
    probe = subprocess.check_output(
        [
            str(ENVIRONMENT / "bin/python"),
            "-c",
            (
                "import importlib.metadata as m; "
                "print(m.version('isaacteleop')); print(m.version('isaaclab-teleop'))"
            ),
        ],
        text=True,
    ).splitlines()
    if probe != ["1.4.98rc1", "0.8.0"]:
        raise RuntimeError(f"Candidate B S2 teleop package mismatch: {probe}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a bounded standalone no-client smoke with a host reset.",
    )
    parser.add_argument(
        "--xr-smoke",
        action="store_true",
        help="Run a bounded no-client smoke through the Candidate B XR Kit experience.",
    )
    parser.add_argument("--max-control-steps", type=int, default=18000)
    arguments = parser.parse_args()
    if arguments.smoke and arguments.xr_smoke:
        parser.error("--smoke and --xr-smoke are mutually exclusive")
    _verify()
    if os.environ.get("OMNI_KIT_ACCEPT_EULA", "").upper() not in {"Y", "YES", "1"}:
        raise RuntimeError(
            "NVIDIA EULA acceptance is required: set OMNI_KIT_ACCEPT_EULA=Y after acceptance"
        )

    environment = os.environ.copy()
    environment.update(
        {
            "UV_CACHE_DIR": str(QUALIFICATION / "uv_cache"),
            "UV_PROJECT_ENVIRONMENT": str(ENVIRONMENT),
            "XDG_CACHE_HOME": str(STORAGE / "cache/isaac-s2/xdg"),
            "PYTHONPATH": str(LAB / "source/isaaclab"),
            "PYTHONNOUSERSITE": "1",
        }
    )
    environment.pop("PYTHONHOME", None)
    environment.pop("VIRTUAL_ENV", None)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = STORAGE / "cache/isaac-s2/runs" / stamp
    output_dir.mkdir(parents=True, exist_ok=False)
    bounded_smoke = arguments.smoke or arguments.xr_smoke
    max_steps = 60 if bounded_smoke else arguments.max_control_steps
    command = [
        "uv",
        "run",
        "--project",
        str(LAB),
        "--frozen",
        "--no-sync",
        "python",
        str(ROOT / "tools/run_isaac_s1.py"),
        "--s2-teleop",
        "--device",
        "cuda:0",
        "--report",
        str(output_dir / "result.json"),
        "--s2-max-control-steps",
        str(max_steps),
    ]
    if bounded_smoke:
        command.extend(
            [
                "--s2-cloudxr-profile",
                "cloudxrjs" if arguments.xr_smoke else "standalone",
                "--no-s2-require-session",
                "--s2-reset-step",
                "30",
            ]
        )
        if arguments.xr_smoke:
            command.append("--xr")
    else:
        command.extend(
            [
                "--xr",
                "--s2-cloudxr-profile",
                "cloudxrjs",
                "--s2-reset-step",
                "0",
                "--s2-require-tracking",
            ]
        )

    print(f"S2 evidence output: {output_dir}", flush=True)
    print(f"S2 command: {' '.join(command)}", flush=True)
    with (output_dir / "stdout.log").open("w", encoding="utf-8") as log:
        with subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
            return_code = process.wait()
    report_path = output_dir / "result.json"
    if not report_path.is_file():
        return return_code or 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["process"] = {
        "exit_code": return_code,
        "clean_shutdown": return_code == 0,
        "stdout_log": str(output_dir / "stdout.log"),
        "launcher": str(Path(__file__).resolve()),
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
