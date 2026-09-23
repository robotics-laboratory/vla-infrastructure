"""Launch one fresh process and retain exact input and output provenance."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--temporal", choices=("t0", "t1", "t2", "t3", "t4", "t5", "t6-sync-explicit"), default="t0"
    )
    parser.add_argument("--cost", choices=("c0", "c1", "c2", "c3", "c4"), default="c3")
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--mode", choices=("smoke", "xr-smoke", "physical"), default="smoke")
    parser.add_argument("--warmup", type=int, default=300)
    parser.add_argument("--measured", type=int, default=3000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args()
    if not args.probe and args.mode != "smoke":
        parser.error("Cost runs use the existing no-client committed RECORD benchmark")
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    sources = args.output / "sources"
    shutil.copytree(Path(__file__).parent, sources, ignore=shutil.ignore_patterns("__pycache__"))
    env = os.environ.copy()
    env.pop("HEADLESS", None)
    env.update(
        OMNI_KIT_ACCEPT_EULA="Y",
        ISAACLAB_CXR_ACCEPT_EULA="1",
        PYTHONPATH=str(Path(__file__).parent),
        DISPLAY=env.get("DISPLAY", ":0"),
        CAMERA_AUDIT_OUTPUT=str(args.output.resolve()),
        CAMERA_AUDIT_TEMPORAL=args.temporal,
        CAMERA_AUDIT_COST=args.cost,
        CAMERA_AUDIT_BATCH=str(int(args.batch or args.temporal == "t5")),
        CAMERA_AUDIT_PROBE=str(args.measured if args.probe else 0),
    )
    ticks = 10 if args.probe else args.warmup + args.measured
    cmd = [
        "./run-vr",
        "diag" if args.probe else "record",
        "--state-root",
        str(args.state_root),
        "--run-dir",
        str(args.output / "runtime"),
        "--max-control-steps",
        str(ticks),
        "--performance-warmup-steps",
        str(0 if args.probe else args.warmup),
        "--performance-window-steps",
        str(ticks),
    ]
    if not args.probe:
        cmd += ["--xr-resolution-scale", "0.4"]
    if args.mode != "physical":
        cmd.append("--" + args.mode)
    if not args.probe:
        cmd += [
            "--injected-actions",
            "--recording-benchmark",
            "--benchmark-pair-id",
            "camera-audit",
            "--benchmark-warmup-steps",
            str(args.warmup),
            "--benchmark-measured-steps",
            str(args.measured),
            "--recording-dir",
            str(args.output / "recording"),
        ]
    manifest = {
        "arguments": vars(args) | {"output": str(args.output), "state_root": str(args.state_root)},
        "command": cmd,
        "cwd": str(ROOT),
        "started_unix": time.time(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dirty": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
        "environment": {
            k: v
            for k, v in env.items()
            if k.startswith("CAMERA_AUDIT") or k in ("PYTHONPATH", "DISPLAY")
        },
        "source_hashes": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in (ROOT / "tools", ROOT / "configs")
            for p in folder.rglob("*")
            if p.is_file() and "__pycache__" not in str(p)
        },
    }
    path = args.output / "launch.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with (
        (args.output / "stdout.log").open("w") as stream,
        (args.output / "gpu.csv").open("w") as gpu,
    ):
        monitor = subprocess.Popen(
            [
                "nvidia-smi",
                "--query-gpu=timestamp,utilization.gpu,memory.used,power.draw",
                "--format=csv",
                "-l",
                "1",
            ],
            stdout=gpu,
            stderr=subprocess.STDOUT,
        )
        try:
            result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
            manifest["exit_code"] = result.returncode
        finally:
            monitor.terminate()
            monitor.wait()
    manifest["ended_unix"] = time.time()
    manifest["artifacts"] = {
        str(p.relative_to(args.output)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in args.output.rglob("*")
        if p.is_file() and p != path
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "exit": result.returncode}), flush=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
