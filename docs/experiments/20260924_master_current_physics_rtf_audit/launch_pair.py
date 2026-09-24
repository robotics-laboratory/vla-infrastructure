"""Run the bounded OLD/CURRENT assay in separate source and conversion roots."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


EXPECTED = {
    "old": "76b93ee6562ac1da2e21551d1aff5454cfd7a859",
    "current": "a36bc5cc302eefef19fe4f94063a3f6179aaf1aa",
}


def _git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state-parent", type=Path, required=True)
    parser.add_argument("--which", choices=("old", "current", "both"), default="both")
    args = parser.parse_args()
    roots = {"old": args.old.resolve(), "current": args.current.resolve()}
    for name, root in roots.items():
        actual = _git(root, "rev-parse", "HEAD")
        if actual != EXPECTED[name]:
            parser.error(f"{name}: expected {EXPECTED[name]}, got {actual}")
        if _git(root, "status", "--porcelain"):
            parser.error(f"{name}: checkout has WIP")
    for variable in ("OMNI_KIT_ACCEPT_EULA", "ISAACLAB_CXR_ACCEPT_EULA"):
        if os.environ.get(variable, "").upper() not in {"1", "Y", "YES", "TRUE"}:
            parser.error(f"Set {variable} only after accepting its license")
    args.output.mkdir(parents=True, exist_ok=True)
    args.state_parent.mkdir(parents=True, exist_ok=True)
    selected = roots if args.which == "both" else {args.which: roots[args.which]}
    for name, root in selected.items():
        state = args.state_parent / name
        state.mkdir(mode=0o700, exist_ok=True)
        environment = os.environ.copy()
        environment.pop("HEADLESS", None)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent)
        environment["PHYSICS_AUDIT_OUTPUT"] = str(args.output.resolve())
        environment["PHYSICS_AUDIT_CHECKPOINT"] = name
        environment["DISPLAY"] = environment.get("DISPLAY", ":0")
        command = ["./run-vr"]
        if name == "current":
            command.append("record")
        command += ["--smoke", "--max-control-steps", "1", "--state-root", str(state)]
        (args.output / f"command-{name}.json").write_text(
            json.dumps({"cwd": str(root), "command": command,
                        "source_sha": EXPECTED[name], "state_root": str(state)}, indent=2) + "\n")
        with (args.output / f"launch-{name}.log").open("w") as log:
            process = subprocess.run(command, cwd=root, env=environment, stdout=log,
                                     stderr=subprocess.STDOUT, timeout=1800, check=False)
        if process.returncode:
            raise SystemExit(f"{name} assay failed with exit {process.returncode}; see launch-{name}.log")


if __name__ == "__main__":
    main()
