#!/usr/bin/env python3
"""Launch the isolated RoboSyn-inspired PIPER-X Quest demo."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

import yaml

from launch_isaac_s2 import ENVIRONMENT, LAB, QUALIFICATION, STORAGE, _verify


ROOT = Path(__file__).resolve().parents[1]
DEMO_CONFIG = ROOT / "configs/experiments/robosyn_vr_demo.yaml"
ASSET_MANIFEST = ROOT / "configs/experiments/robosyn_test_assets.yaml"
RUNTIME_ROOT = STORAGE / "cache/robosyn-vr-demo"
USER_CACHE_ROOT = RUNTIME_ROOT / "users" / f"uid-{os.getuid()}"
KIT_PORTABLE_ROOT = USER_CACHE_ROOT / "kit"
TEMP_ROOT = USER_CACHE_ROOT / "tmp"


def _verify_demo_inputs() -> None:
    _verify()
    config = yaml.safe_load(DEMO_CONFIG.read_text(encoding="utf-8"))
    manifest = yaml.safe_load(ASSET_MANIFEST.read_text(encoding="utf-8"))
    checkout = Path(manifest["source_checkout"])
    commit = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(checkout), "status", "--porcelain"], text=True
    )
    if commit != manifest["source_commit"] or dirty:
        raise RuntimeError(f"RoboSyn test checkout is not clean/pinned: {checkout}")
    for item in manifest["assets"]:
        path = checkout / item["source_path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise RuntimeError(f"RoboSyn test asset hash mismatch: {path}")
    if config["status"] != "EXPERIMENTAL_TEST_ONLY_NOT_A_GATE":
        raise RuntimeError("demo config lost its experimental classification")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("dual_cube_to_matching_plates", "robosyn_asset_lab"),
        default="dual_cube_to_matching_plates",
    )
    parser.add_argument("--smoke", action="store_true", help="Bounded standalone no-client run.")
    parser.add_argument(
        "--xr-smoke", action="store_true", help="Bounded no-client run with XR Kit enabled."
    )
    parser.add_argument(
        "--hud-on-start",
        action="store_true",
        help="Start the upstream left/right wrist PiP visible for measurement.",
    )
    parser.add_argument("--scene-preview", type=Path, help="Optional scene-camera PNG output.")
    parser.add_argument("--max-control-steps", type=int, default=18000)
    parser.add_argument(
        "--performance-window-steps",
        type=int,
        default=30,
        help="Control steps per live summary; JSONL retains every control step.",
    )
    parser.add_argument(
        "--performance-warmup-steps",
        type=int,
        default=30,
        help="Initial control steps excluded from aggregate performance statistics.",
    )
    args = parser.parse_args()
    if args.smoke and args.xr_smoke:
        parser.error("--smoke and --xr-smoke are mutually exclusive")
    if args.hud_on_start and args.smoke:
        parser.error("HUD measurement requires --xr-smoke or the default physical XR run")
    _verify_demo_inputs()
    if os.environ.get("OMNI_KIT_ACCEPT_EULA", "").upper() not in {"Y", "YES", "1"}:
        raise RuntimeError("NVIDIA EULA acceptance is required: set OMNI_KIT_ACCEPT_EULA=Y")

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
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    hud_name = "hud-on" if args.hud_on_start else "hud-off"
    output_dir = RUNTIME_ROOT / "runs" / f"{stamp}-{args.profile}-{hud_name}"
    output_dir.mkdir(parents=True, exist_ok=False)
    bounded = args.smoke or args.xr_smoke
    max_steps = 60 if bounded else args.max_control_steps
    command = [
        "uv",
        "run",
        "--project",
        str(LAB),
        "--frozen",
        "--no-sync",
        "python",
        str(ROOT / "tools/run_isaac_s1.py"),
        "--robosyn-vr-demo",
        "--s2-teleop",
        "--demo-profile",
        args.profile,
        "--device",
        "cuda:0",
        "--kit_args",
        f"--portable-root {KIT_PORTABLE_ROOT}",
        "--report",
        str(output_dir / "result.json"),
        "--s2-max-control-steps",
        str(max_steps),
        "--s2-performance-log",
        str(output_dir / "performance.jsonl"),
        "--s2-performance-window-steps",
        str(args.performance_window_steps),
        "--s2-performance-warmup-steps",
        str(args.performance_warmup_steps),
    ]
    if args.hud_on_start:
        command.append("--demo-hud-on-start")
    if args.scene_preview is not None:
        command.extend(["--demo-scene-preview", str(args.scene_preview.resolve())])
    if bounded:
        command.extend(
            [
                "--s2-cloudxr-profile",
                "cloudxrjs" if args.xr_smoke else "standalone",
                "--no-s2-require-session",
                "--s2-reset-step",
                "30",
            ]
        )
        if args.xr_smoke:
            command.extend(
                [
                    "--xr",
                    "--demo-display-toggle-smoke",
                    "--demo-backdrop-toggle-smoke",
                    "--demo-recenter-smoke",
                ]
            )
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
    print(f"Demo output: {output_dir}", flush=True)
    print(f"Demo command: {' '.join(command)}", flush=True)
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
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
