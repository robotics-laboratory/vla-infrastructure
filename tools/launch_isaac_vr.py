#!/usr/bin/env python3
"""Launch one PIPER-X VR runtime, with optional diagnostic observers."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shlex
import signal
import sys
from contextlib import nullcontext

from isaac_vr_config import CONFIG_PATH, ASSET_LAB_CONFIG, load_composition

import yaml

from isaac_demo_launch import (
    STACKS,
    configure_cloudxr,
    user_environment,
    verify_stack,
    write_runtime_config,
)


ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_INPUTS = (
    CONFIG_PATH,
    ROOT / "configs/isaac61_s2_runtime.yaml",
    ROOT / "configs/environments/isaac1103/ENVIRONMENT.yaml",
    ROOT / "tools/isaac_vr_config.py",
    ROOT / "tools/isaac_vr_camera_guard.py",
    ROOT / "tools/isaac_vr_capture.py",
    ROOT / "tools/isaac_vr_decision.py",
    ROOT / "tools/isaac_s2_performance.py",
    ROOT / "tools/isaac_s2_processor.py",
    ROOT / "tools/isaac_s1_runtime.py",
    ROOT / "run-vr",
    ROOT / "tools/isaac_demo_launch.py",
    ROOT / "tools/run_isaac_s1.py",
    ROOT / "tools/isaac_preview_partitions.py",
    ROOT / "tools/launch_isaac_vr.py",
    ROOT / "tools/isaac_vr_runtime.py",
    ROOT / "tools/isaac_s2_runtime.py",
    ROOT / "tools/isaac_s2_upstream.py",
)


def _git_output(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).rstrip("\n")


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
    s2_path = ROOT / "configs" / stack["s2"]
    s2 = yaml.safe_load(s2_path.read_text())
    for path in (s2_path, ROOT / "configs" / stack["s1"]):
        source_hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if "asset_lab" in config:
        for path in (ASSET_LAB_CONFIG, ROOT / config["asset_lab"]["asset_manifest"]):
            source_hashes[str(path.relative_to(ROOT))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    invocation = [os.environ.get("VLA_VR_ENTRYPOINT", "./run-vr"), *args.invocation]
    manifest = {
        "schema": "piper_x_isaac_vr_run_manifest_v1",
        "run_id": output_dir.name,
        "mode": args.mode,
        "top_level_invocation": invocation,
        "top_level_command": shlex.join(invocation),
        "generated_runtime_config_sha256": hashlib.sha256(
            (output_dir / "runtime.yaml").read_bytes()
        ).hexdigest(),
        "processor_revision": s2["processor"]["revision"],
        "effective_control_config": {
            "processor": {**s2["processor"], "sensitivity": config["teleop_tuning"]["sensitivity"]},
            "xr_presentation": config["xr_presentation"],
            "preview": {
                **config["vr_camera_feeds"],
                "initial_visibility": bool(args.hud_on_start),
                "include_scene_camera": args.preview_cameras == 3,
                "preview_isolation": args.preview_isolation,
            },
            "backdrop": config["scene"]["backdrop"],
        },
        "repository": {
            "root": str(ROOT),
            "branch": _git_output("rev-parse", "--abbrev-ref", "HEAD"),
            "commit": _git_output("rev-parse", "HEAD"),
            "full_status": _git_output("status", "--porcelain=v1", "--untracked-files=all"),
            "untracked_files": _git_output(
                "ls-files", "--others", "--exclude-standard", "-z"
            ).split("\0")[:-1],
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
            "environment_pins": s2["environment"],
            "frozen_workspace_sha256": {"pyproject": stack["pyproject"], "lock": stack["lock"]},
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
            "cloudxr_install_root": str(state / "cloudxr"),
            "python_environment": str(stack["environment"]),
        },
        "cloudxr_web_client": {
            **config["cloudxr_web_client"],
            "passed_to_host_process": False,
            "state_location": "headset browser cache/localStorage",
        },
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    invocation = list(sys.argv[1:] if argv is None else argv)
    config = yaml.safe_load(CONFIG_PATH.read_text())
    defaults = config["operator"]
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("mode", nargs="?", choices=("run", "diag"), default="run")
    parser.add_argument(
        "--profile",
        choices=("dual_cube_to_matching_plates", "robosyn_asset_lab"),
        default=config["profiles"]["default"],
    )
    parser.add_argument("--stack", choices=tuple(STACKS), default=defaults["stack"])
    parser.add_argument("--preview-isolation", choices=("off", "scene-partitions"))
    parser.add_argument("--preview-cameras", choices=(2, 3), type=int)
    parser.add_argument("--cloudxr-mode", choices=("auto", "existing"), default="auto")
    parser.add_argument(
        "--state-root", type=Path, help="Private directory owned by the current UID."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--capture-preview-evidence",
        action="store_true",
        help="Opt in to bounded preview PPM diagnostics outside the repository.",
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
    parser.add_argument(
        "--max-control-steps", type=int, help="Default:60 for smoke,18000 otherwise."
    )
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
    args = parser.parse_args(invocation)
    args.invocation = invocation
    args.mode = "diagnostic" if args.mode == "diag" else "run"
    diagnostic_flags = {
        "--preview-isolation",
        "--preview-cameras",
        "--capture-preview-evidence",
        "--scene-preview",
        "--performance-window-steps",
        "--performance-warmup-steps",
    }
    used = [
        item.split("=", 1)[0] for item in invocation if item.split("=", 1)[0] in diagnostic_flags
    ]
    if args.mode == "run" and (used or args.profile == "robosyn_asset_lab"):
        parser.error(
            f"Diagnostic-only option/profile: {used or args.profile}; use ./run-vr diag ..."
        )
    if args.performance_window_steps <= 0 or args.performance_warmup_steps < 0:
        parser.error("performance window must be positive and warmup nonnegative")
    if args.max_control_steps is not None and args.max_control_steps <= 0:
        parser.error("--max-control-steps must be positive")
    if args.smoke and args.xr_smoke:
        parser.error("--smoke and --xr-smoke are mutually exclusive")
    if args.hud_on_start and args.smoke:
        parser.error("HUD measurement requires --xr-smoke or the default physical XR run")
    if args.preview_isolation is None:
        args.preview_isolation = defaults["stacks"][args.stack]["preview_isolation"]
    if args.preview_cameras is None:
        args.preview_cameras = defaults["stacks"][args.stack]["preview_cameras"]
    if args.stack == "legacy" and args.preview_isolation != "off":
        parser.error(
            "legacy Kit is not qualified for Scene Partitions; use --preview-isolation off"
        )
    args.max_control_steps = (
        args.max_control_steps
        or defaults["smoke_control_steps" if args.smoke or args.xr_smoke else "max_control_steps"]
    )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stack = verify_stack(args.stack)
    config = load_composition(args.profile)
    if not args.dry_run and os.environ.get("OMNI_KIT_ACCEPT_EULA", "").upper() not in {
        "Y",
        "YES",
        "1",
    }:
        raise RuntimeError("NVIDIA EULA acceptance is required: set OMNI_KIT_ACCEPT_EULA=Y")

    environment, state = user_environment(stack, args.stack, state_root=args.state_root)
    environment["VLA_CLOUDXR_INSTALL_DIR"] = str(state / "cloudxr")
    configure_cloudxr(environment, mode=args.cloudxr_mode, dry_run=args.dry_run)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    hud_name = "hud-on" if args.hud_on_start else "hud-off"
    output_dir = state / "runs" / f"{stamp}-{args.mode}-{args.profile}-{hud_name}"
    output_dir.mkdir(parents=True, exist_ok=False)
    if args.capture_preview_evidence:
        environment["ROBOSYN_VR_CAMERA_DIAGNOSTICS_DIR"] = str(
            output_dir / "camera_feed_diagnostics"
        )
    runtime_config = write_runtime_config(ROOT, stack, state, output_dir)
    bounded = args.smoke or args.xr_smoke
    max_steps = args.max_control_steps
    kit_args = ["--portable-root", str(state / "kit")]
    if not args.smoke:
        kit_args += [
            "--enable",
            "omni.kit.scene_view.xr",
            "--enable",
            "omni.kit.scene_view.xr_utils",
        ]
    if args.preview_isolation == "scene-partitions":
        # Initialize the topology before the first frame. Cached personal Kit settings cannot override it.
        kit_args += [
            "--/renderer/scenePartitioning/enabled=true",
            "--/rtx/scenePartitioning/showAllPartitionsByDefault=true",
        ]
        if args.smoke:
            kit_args += ["--enable", "omni.kit.scene_view.xr"]
    command = [
        str(stack["environment"] / "bin/python"),
        str(ROOT / "tools/run_isaac_s1.py"),
        "--config",
        str(runtime_config),
        "--s2-config",
        str(ROOT / "configs" / stack["s2"]),
        "--vr-runtime",
        "--s2-mode",
        args.mode,
        "--s2-teleop",
        "--demo-profile",
        args.profile,
        "--device",
        "cuda:0",
        "--kit_args",
        shlex.join(kit_args),
        "--demo-preview-isolation",
        args.preview_isolation,
        "--report",
        str(output_dir / "result.json"),
        "--s2-max-control-steps",
        str(max_steps),
    ]
    if args.mode == "diagnostic":
        command.extend(
            [
                "--s2-performance-log",
                str(output_dir / "performance.jsonl"),
                "--s2-performance-window-steps",
                str(args.performance_window_steps),
                "--s2-performance-warmup-steps",
                str(args.performance_warmup_steps),
            ]
        )
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
    if args.xr_smoke and args.mode == "diagnostic":
        command += [
            "--demo-display-toggle-smoke",
            "--demo-backdrop-toggle-smoke",
            "--demo-recenter-smoke",
        ]
    _write_launch_manifest(
        output_dir,
        args=args,
        command=command,
        environment=environment,
        config=config,
        state=state,
        stack=stack,
    )
    print(f"VR output: {output_dir}", flush=True)
    print(f"Quest WebXR client: {config['cloudxr_web_client']['url']}", flush=True)
    print(f"Quest client setup: {config['cloudxr_web_client']['operator_setup']}", flush=True)
    print(f"VR command: {' '.join(command)}", flush=True)
    if args.dry_run:
        return 0
    stop_requested = False
    process: subprocess.Popen[str] | None = None

    def request_stop(_signum, _frame) -> None:
        nonlocal stop_requested
        if stop_requested:
            return
        stop_requested = True
        print("VR stop requested; waiting for final report...", flush=True)
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)

    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    try:
        log_context = (
            (output_dir / "stdout.log").open("w", encoding="utf-8")
            if args.mode == "diagnostic"
            else nullcontext(None)
        )
        with log_context as log:
            with subprocess.Popen(
                command,
                cwd=ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            ) as process:
                assert process.stdout is not None
                for line in process.stdout:
                    if log is not None:
                        log.write(line)
                        log.flush()
                    print(line, end="", flush=True)
                return_code = process.wait()
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
    report_path = output_dir / "result.json"
    if not report_path.is_file():
        return return_code or 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["process"] = {
        "exit_code": return_code,
        "clean_shutdown": return_code in (0, 130),
        "stop_requested": stop_requested,
        "stdout_log": str(output_dir / "stdout.log") if args.mode == "diagnostic" else None,
        "launcher": str(Path(__file__).resolve()),
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
