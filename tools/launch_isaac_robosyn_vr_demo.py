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
import shlex

import yaml

from isaac_demo_launch import (STACKS, configure_cloudxr, git, user_environment,
                               verify_stack, write_runtime_config)


ROOT = Path(__file__).resolve().parents[1]
DEMO_CONFIG = ROOT / "configs/experiments/robosyn_vr_demo.yaml"
ASSET_MANIFEST = ROOT / "configs/experiments/robosyn_test_assets.yaml"
PROVENANCE_INPUTS = (
    DEMO_CONFIG,
    ROOT / "tools/isaac_demo_launch.py",
    ROOT / "tools/run_isaac_s1.py",
    ROOT / "tools/isaac_preview_partitions.py",
    ROOT / "tools/launch_isaac_robosyn_vr_demo.py",
    ROOT / "tools/isaac_robosyn_vr_demo.py",
    ROOT / "tools/isaac_s2_runtime.py",
    ROOT / "tools/isaac_s2_upstream.py",
)


def _verify_demo_inputs() -> dict:
    config = yaml.safe_load(DEMO_CONFIG.read_text(encoding="utf-8"))
    manifest = yaml.safe_load(ASSET_MANIFEST.read_text(encoding="utf-8"))
    checkout = Path(manifest["source_checkout"])
    commit = git(checkout, "rev-parse", "HEAD")
    dirty = git(checkout, "status", "--porcelain")
    if commit != manifest["source_commit"] or dirty:
        raise RuntimeError(f"RoboSyn test checkout is not clean/pinned: {checkout}")
    for item in manifest["assets"]:
        path = checkout / item["source_path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise RuntimeError(f"RoboSyn test asset hash mismatch: {path}")
    if config["status"] != "EXPERIMENTAL_TEST_ONLY_NOT_A_GATE":
        raise RuntimeError("demo config lost its experimental classification")
    return config


def _git_output(*args: str) -> str:
    return git(ROOT, *args)


def _write_launch_manifest(
    output_dir: Path,
    *,
    args: argparse.Namespace,
    command: list[str],
    environment: dict[str, str],
    config: dict,
    state: Path,
    stack: dict,
) -> None:
    """Persist the host-controlled launch inputs before the long-running child starts."""
    home = environment.get("HOME", str(Path.home()))
    source_hashes = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in PROVENANCE_INPUTS
    }
    manifest = {
        "schema": "piper_x_robosyn_vr_launch_provenance_v1",
        "repository": {
            "root": str(ROOT),
            "branch": _git_output("rev-parse", "--abbrev-ref", "HEAD"),
            "commit": _git_output("rev-parse", "HEAD"),
            "tracked_status": _git_output("status", "--porcelain", "--untracked-files=no"),
            "source_sha256": source_hashes,
        },
        "launch": {
            "command": command,
            "profile": args.profile,
            "stack": args.stack,
            "preview_isolation": args.preview_isolation,
            "preview_cameras": args.preview_cameras,
            "cloudxr_mode": args.cloudxr_mode,
            "dry_run": args.dry_run,
            "pinned_packages": stack["packages"],
            "lab_commit": stack["commit"],
            "hud_on_start": bool(args.hud_on_start),
            "smoke": bool(args.smoke),
            "xr_smoke": bool(args.xr_smoke),
            "max_control_steps": int(command[command.index("--s2-max-control-steps") + 1]),
        },
        "host_paths": {
            "uid": os.getuid(),
            "home": home,
            "kit_portable_root": str(state / "kit"),
            "xdg_cache_home": environment["XDG_CACHE_HOME"],
            "cloudxr_install_root": str(Path(home) / ".cloudxr"),
            "python_environment": str(stack["environment"]),
        },
        "cloudxr_web_client": {
            **config["cloudxr_web_client"],
            "passed_to_host_process": False,
            "state_location": "headset browser cache/localStorage",
        },
    }
    (output_dir / "launch_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("dual_cube_to_matching_plates", "robosyn_asset_lab"),
        default="dual_cube_to_matching_plates",
    )
    parser.add_argument("--stack", choices=tuple(STACKS), default="isaac61")
    parser.add_argument("--preview-isolation", choices=("off", "scene-partitions"))
    parser.add_argument("--preview-cameras", choices=(2, 3), type=int)
    parser.add_argument("--cloudxr-mode", choices=("auto", "existing"), default="auto")
    parser.add_argument("--state-root", type=Path, help="Private directory owned by the current UID.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--capture-preview-evidence", action="store_true",
                        help="Opt in to bounded preview PPM diagnostics outside the repository.")
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
    parser.add_argument("--max-control-steps", type=int, help="Default:60 for smoke,18000 otherwise.")
    args = parser.parse_args()
    if args.max_control_steps is not None and args.max_control_steps <= 0:
        parser.error("--max-control-steps must be positive")
    if args.smoke and args.xr_smoke:
        parser.error("--smoke and --xr-smoke are mutually exclusive")
    if args.hud_on_start and args.smoke:
        parser.error("HUD measurement requires --xr-smoke or the default physical XR run")
    if args.preview_isolation is None:
        args.preview_isolation = "scene-partitions" if args.stack == "isaac61" else "off"
    if args.preview_cameras is None:
        args.preview_cameras = 3 if args.stack == "isaac61" else 2
    if args.stack == "legacy" and args.preview_isolation != "off":
        parser.error("legacy Kit is not qualified for Scene Partitions; use --preview-isolation off")
    stack = verify_stack(args.stack)
    config = _verify_demo_inputs()
    if not args.dry_run and os.environ.get("OMNI_KIT_ACCEPT_EULA", "").upper() not in {"Y", "YES", "1"}:
        raise RuntimeError("NVIDIA EULA acceptance is required: set OMNI_KIT_ACCEPT_EULA=Y")

    environment, state = user_environment(stack, args.stack, state_root=args.state_root)
    configure_cloudxr(environment, mode=args.cloudxr_mode, dry_run=args.dry_run)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    hud_name = "hud-on" if args.hud_on_start else "hud-off"
    output_dir = state / "runs" / f"{stamp}-{args.profile}-{hud_name}"
    output_dir.mkdir(parents=True, exist_ok=False)
    if args.capture_preview_evidence:
        environment["ROBOSYN_VR_CAMERA_DIAGNOSTICS_DIR"] = str(output_dir / "camera_feed_diagnostics")
    runtime_config = write_runtime_config(ROOT, stack, state, output_dir)
    bounded = args.smoke or args.xr_smoke
    max_steps = args.max_control_steps or (60 if bounded else 18000)
    kit_args = ["--portable-root", str(state / "kit")]
    if not args.smoke:
        kit_args += ["--enable", "omni.kit.scene_view.xr", "--enable", "omni.kit.scene_view.xr_utils"]
    if args.preview_isolation == "scene-partitions":
        # Initialize the topology before the first frame. Cached personal Kit settings cannot override it.
        kit_args += ["--/renderer/scenePartitioning/enabled=true",
                     "--/rtx/scenePartitioning/showAllPartitionsByDefault=true"]
        if args.smoke:
            kit_args += ["--enable", "omni.kit.scene_view.xr"]
    command = [
        str(stack["environment"] / "bin/python"),
        str(ROOT / "tools/run_isaac_s1.py"),
        "--config", str(runtime_config), "--s2-config", str(ROOT / "configs" / stack["s2"]),
        "--robosyn-vr-demo", "--s2-teleop", "--demo-profile", args.profile,
        "--device", "cuda:0", "--kit_args", shlex.join(kit_args),
        "--demo-preview-isolation", args.preview_isolation,
        "--report", str(output_dir / "result.json"),
        "--s2-max-control-steps", str(max_steps),
    ]
    if args.stack == "isaac61":
        command += ["--viz", "kit"]
    if not args.smoke:
        command += ["--experience", str(stack["lab"] / "apps/isaaclab.python.xr.openxr.kit")]
    if args.preview_cameras == 3:
        command.append("--demo-preview-scene")
    if args.hud_on_start:
        command.append("--demo-hud-on-start")
    if args.scene_preview is not None:
        command.extend(["--demo-scene-preview", str(args.scene_preview.resolve())])
    if bounded:
        command.extend(
            [
                "--s2-cloudxr-profile",
                "standalone",
                "--s2-require-session" if args.xr_smoke else "--no-s2-require-session",
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
    _write_launch_manifest(
        output_dir,
        args=args,
        command=command,
        environment=environment,
        config=config,
        state=state,
        stack=stack,
    )
    print(f"Demo output: {output_dir}", flush=True)
    print(f"Quest WebXR client: {config['cloudxr_web_client']['url']}", flush=True)
    print(f"Quest client setup: {config['cloudxr_web_client']['operator_setup']}", flush=True)
    print(f"Demo command: {' '.join(command)}", flush=True)
    if args.dry_run:
        return 0
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
