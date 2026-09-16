#!/usr/bin/env python3
"""Launch the accepted Candidate B Gate S1 runtime and retain process evidence."""

from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path("/data/vla-infrastructure")
QUALIFICATION = STORAGE / "isaaclab_candidate_qualification/20260907"
LAB = QUALIFICATION / "candidate_b_exact"
ENVIRONMENT = STORAGE / "envs/isaac-s1-candidate-b"
RUNTIME_ROOT = STORAGE / "cache/isaac-s1"
USER_CACHE_ROOT = RUNTIME_ROOT / "users" / f"uid-{os.getuid()}"
KIT_PORTABLE_ROOT = USER_CACHE_ROOT / "kit"
TEMP_ROOT = USER_CACHE_ROOT / "tmp"
LAB_COMMIT = "913ac53f51b2f8d02c9e121caa4cbdd06262948e"
ASSET_COMMIT = "f6642ce0d7872c686f29c99e9e10cd23d1d49313"
LAB_PYPROJECT_SHA256 = "b691862409ab8ad58b074ac32ce7f071e3895ec10975444b9e62995741ace159"
LAB_LOCK_SHA256 = "80eb2c4e1155dd9e9736506d41cdbe327df74ee2b005bdecc0fb7c87c8b8bb84"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-socket", type=Path)
    parser.add_argument("--eval-run-manifest", type=Path)
    args = parser.parse_args()
    if (args.eval_socket is None) != (args.eval_run_manifest is None):
        parser.error("--eval-socket and --eval-run-manifest must be provided together")
    return args


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    args = _arguments()
    for checkout, expected in ((LAB, LAB_COMMIT), (STORAGE / "assets/agx_arm_urdf", ASSET_COMMIT)):
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
    if os.environ.get("OMNI_KIT_ACCEPT_EULA", "").upper() not in {"Y", "YES", "1"}:
        raise RuntimeError(
            "NVIDIA EULA acceptance is required: set OMNI_KIT_ACCEPT_EULA=Y after acceptance"
        )
    if not (ENVIRONMENT / "bin/python").exists():
        raise RuntimeError(f"materialize the checked-in S1 uv project at {ENVIRONMENT} first")
    KIT_PORTABLE_ROOT.mkdir(parents=True, exist_ok=True)
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "UV_CACHE_DIR": str(QUALIFICATION / "uv_cache"),
            "UV_PROJECT_ENVIRONMENT": str(ENVIRONMENT),
            "XDG_CACHE_HOME": str(USER_CACHE_ROOT / "xdg"),
            "TMPDIR": str(TEMP_ROOT),
            "PYTHONPATH": str(LAB / "source/isaaclab"),
            "PYTHONNOUSERSITE": "1",
        }
    )
    environment.pop("PYTHONHOME", None)
    environment.pop("VIRTUAL_ENV", None)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = RUNTIME_ROOT / "runs" / stamp
    output_dir.mkdir(parents=True, exist_ok=False)
    command = [
        "uv",
        "run",
        "--project",
        str(LAB),
        "--frozen",
        "--no-sync",
        "python",
        str(ROOT / "tools/run_isaac_s1.py"),
        "--device",
        "cuda:0",
        "--kit_args",
        f"--portable-root {KIT_PORTABLE_ROOT}",
        "--report",
        str(output_dir / "result.json"),
    ]
    if args.eval_socket is not None:
        command.extend(
            [
                "--eval-socket",
                str(args.eval_socket),
                "--eval-run-manifest",
                str(args.eval_run_manifest),
            ]
        )
    print(f"S1 evidence output: {output_dir}", flush=True)
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
            result = process.wait()
    report_path = output_dir / "result.json"
    if not report_path.is_file():
        return result or 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["process"] = {
        "exit_code": result,
        "clean_shutdown": result == 0,
        "stdout_log": str(output_dir / "stdout.log"),
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
