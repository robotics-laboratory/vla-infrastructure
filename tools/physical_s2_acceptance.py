#!/usr/bin/env python3
"""One S2 acceptance procedure. `prepare` never starts Kit, CloudXR or Quest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import time

import yaml

try:
    from .check_physical_s2 import HUMAN_ITEMS, check_directory, write_json  # type: ignore[import-not-found]
    from .isaac_demo_launch import verify_stack  # type: ignore[import-not-found]
except ImportError:
    from check_physical_s2 import HUMAN_ITEMS, check_directory, write_json
    from isaac_demo_launch import verify_stack

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MASTER = "6430dc1a1a4366d87a3f9d1427f5e95dab7153a0"
SCENARIOS = [
    ("STARTUP", "Подключить Quest обычным CloudXR Start AR; дождаться обеих рук и preview."),
    ("NEUTRAL", "10 секунд держать оба контроллера неподвижно."),
    *[(f"{side}_{kind}_{axis}", f"Только {side}: три медленных движения {kind} по +{axis}/-{axis}; вторая рука неподвижна.")
      for side in ("LEFT", "RIGHT") for kind, axes in
      (("TRANSLATION", ("X", "Y", "Z")), ("ROTATION", ("ROLL", "PITCH", "YAW"))) for axis in axes],
    *[(f"{side}_GRIPPER", f"Только {side}: три цикла trigger 0, .25, .5, .75, 1 и обратно.") for side in ("LEFT", "RIGHT")],
    *[(f"{side}_SPEED", f"Только {side}: проверить независимое изменение speed и translation/rotation scale.") for side in ("LEFT", "RIGHT")],
    *[(f"{side}_CLUTCH", f"{side}: squeeze, переместить controller, отпустить; повторить трижды.") for side in ("LEFT", "RIGHT")],
    *[(f"{side}_TRACKING", f"{side}: краткая контролируемая потеря tracking и возврат; только если это удобно и безопасно. Иначе UNCERTAIN.") for side in ("LEFT", "RIGHT")],
    ("RECONNECT", "Обычный Stop AR / Start AR; проверить rebase и identities."),
    ("RESET", "Client reset; дождаться recovery, выполнить небольшое движение каждой рукой."),
    ("PREVIEW", "В Quest проверить обе wrist feeds, ориентацию, видимость, отсутствие вложенных panels и артефактов."),
    ("SHUTDOWN", "Остановить AR; затем runner отправит SIGINT и дождётся завершения."),
]


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def provenance(expected):
    refs = {ref: git("rev-parse", ref) for ref in ("HEAD", "master", "origin/master")}
    paths = sorted({*ROOT.joinpath("tools").glob("*.py"), *ROOT.joinpath("configs").glob("*"),
                    ROOT / "pyproject.toml", ROOT / "uv.lock"})
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in paths if p.is_file()}
    return {"expected_master": expected, "refs": refs, "git_status": git("status", "--porcelain"),
            "sha256": hashes, "exact_unmodified_master": all(v == expected for v in refs.values())
            and not git("status", "--porcelain", "--untracked-files=no")
            and not git("ls-files", "--others", "--exclude-standard", "--", "tools", "configs"),
            "profile": "isaac_vr_record", "environment_id": "isaac",
            "processor_revision": "piper_x_isaac_s2_bimanual_relative_v3",
            "source_timing": "host_receipt_timestamp only; acquisition D0/R2 unresolved"}


def prepare(directory, expected):
    before = provenance(expected)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "environment").mkdir()
    stack = verify_stack("isaac61")  # imports package metadata only, never starts XR
    write_json(directory / "environment/provenance.json", {**before, "verified_stack": {
        k: str(v) if isinstance(v, Path) else v for k, v in stack.items()}})
    (directory / "environment/working_tree.patch").write_text(git("diff", "HEAD", "--", "tools", "configs"))
    with tarfile.open(directory / "environment/source_snapshot.tar.gz", "w:gz") as archive:
        for relative in before["sha256"]:
            archive.add(ROOT / relative, arcname=relative)
    config = yaml.safe_load((ROOT / "configs/isaac61_s2_runtime.yaml").read_text())
    blockers = []
    if not before["exact_unmodified_master"]:
        blockers.append("Instrumentation changes runtime: this is master + patch, not exact unmodified requested master")
    if config["processor"]["sensitivity"].get("control_mode", "toggle") != "slider":
        blockers.append("Requested speed-slider criterion conflicts with canonical toggle config (2.0/0.5)")
    write_json(directory / "run_manifest.json", {**before, "run_id": directory.name,
        "physical_run_started": False, "readiness": "BLOCKED" if blockers else "READY",
        "blockers": blockers, "scenarios": SCENARIOS,
        "artifact_note": "prepare is not physical evidence; failures are never overwritten"})
    write_json(directory / "human_acceptance.json", {"observer": None, "answers": {
        k: {"question": question, "status": "UNCERTAIN", "comment": "", "answered_at_ns": None}
        for k, question in HUMAN_ITEMS.items()}, "scenario_answers": []})
    # Runtime journal is created exclusively by the runtime. An empty file here
    # would hide whether the instrumented process ever reached its entrypoint.
    (directory / "stdout.log").touch()
    check_directory(directory)
    print(json.dumps({"directory": str(directory), "blockers": blockers}, ensure_ascii=False, indent=2))


def mark(directory, name):
    value = {"name": name, "host_marker_timestamp_ns": time.monotonic_ns()}
    temp = directory / "scenario.tmp"
    write_json(temp, value)
    temp.replace(directory / "scenario.json")
    with (directory / "scenario_events.jsonl").open("a") as stream:
        stream.write(json.dumps(value) + "\n")


def answer(prompt):
    while True:
        status = input(f"{prompt}\nPASS / FAIL / UNCERTAIN: ").strip().upper()
        if status in ("PASS", "FAIL", "UNCERTAIN"):
            return {"status": status, "comment": input("COMMENT: "), "answered_at_ns": time.monotonic_ns()}


def run(directory):
    manifest = json.loads((directory / "run_manifest.json").read_text())
    current = provenance(manifest["expected_master"])
    if manifest["blockers"] or not current["exact_unmodified_master"]:
        raise RuntimeError(f"Preflight blocked: {manifest['blockers']}; reconcile before physical launch")
    if current["sha256"] != manifest["sha256"]:
        raise RuntimeError("Source/config hashes changed since prepare; prepare a new run")
    if manifest["physical_run_started"]:
        raise RuntimeError("Run already used; preserve it and prepare a new directory")
    human = json.loads((directory / "human_acceptance.json").read_text())
    human["observer"] = input("Observer name: ").strip()
    if not human["observer"]:
        raise RuntimeError("Observer required")
    command = [sys.executable, str(ROOT / "tools/launch_isaac_s2.py"),
               "--output-dir", str(directory / "runtime"), "--acceptance-dir", str(directory),
               "--max-control-steps", "18000"]
    manifest.update(physical_run_started=True, command=command)
    write_json(directory / "run_manifest.json", manifest)
    write_json(directory / "human_acceptance.json", human)
    # No default affirmative answers, no automatic PASS from runtime exit code.
    with (directory / "stdout.log").open("a", buffering=1) as stdout:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=subprocess.STDOUT,
                                   start_new_session=True, env=os.environ.copy())
        try:
            print(f"Runtime log: {directory / 'stdout.log'}")
            for name, instruction in SCENARIOS:
                if process.poll() is not None:
                    print("Runtime exited; remaining scenarios untested.")
                    break
                input(f"\n{name}: {instruction}\nEnter BEFORE beginning this scenario: ")
                mark(directory, name)
                response = answer("После выполнения оцените сценарий")
                human["scenario_answers"].append({"name": name, **response})
                write_json(directory / "human_acceptance.json", human)
                if response["status"] == "FAIL":
                    print("Failure retained; stopping this run.")
                    break
        except (KeyboardInterrupt, EOFError):
            print("Checklist interrupted; unanswered criteria remain UNCERTAIN.")
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)  # launcher forwards to its owned runtime
            while process.poll() is None:
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    print("Waiting for owned runtime shutdown; no clean exit claimed.", flush=True)
            write_json(directory / "process.json", {"exit_code": process.returncode,
                       "host_exit_timestamp_ns": time.monotonic_ns()})
            after = provenance(manifest["expected_master"])
            write_json(directory / "environment/provenance_after.json", after)
    try:
        for key, question in HUMAN_ITEMS.items():
            human["answers"][key].update(answer(question))
            write_json(directory / "human_acceptance.json", human)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        print(json.dumps(check_directory(directory), ensure_ascii=False, indent=2))
        write_json(directory / "artifact_hashes.json", {
            str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*") if p.is_file() and p.name != "artifact_hashes.json"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "run", "check"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--expected-master", default=EXPECTED_MASTER)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.operation == "prepare":
        prepare(directory, args.expected_master)
    elif args.operation == "run":
        run(directory)
    else:
        print(json.dumps(check_directory(directory), indent=2))


if __name__ == "__main__":
    main()
