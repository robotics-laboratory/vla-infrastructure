"""Retain read-only repository verification; use a new output directory per attempt."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
BASE = "d1676c5c05f3bf6ae300f47533526085fdab4204"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", default=BASE, help="Reviewer-supplied trusted preservation commit")
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    if (output / "results.json").exists() and json.loads((output / "results.json").read_text()).get("checks"):
        raise FileExistsError("Preserve previous attempt; select a new output")
    py = sys.executable
    ruff = str(Path(py).with_name("ruff"))
    sources = [
        *ROOT.glob("tools/isaac_vr_standalone*.py"),
        *ROOT.glob("tools/isaac_vr_live_*.py"),
        ROOT / "tools/run_single_gpu_live_recording.py",
        ROOT / "tools/isaac_s2_runtime.py",
        ROOT / "tools/isaac_vr_injected_recording.py",
        ROOT / "tools/isaac_vr_recording.py",
        ROOT / "tools/isaac_vr_replay.py",
        *ROOT.glob("tests/test_isaac_vr_standalone*.py"),
        ROOT / "tests/test_isaac_vr_live_media.py",
        ROOT / "docs/experiments/20261009_live_camera_recording_30hz/deep_research/live_mirror.py",
        ROOT / "docs/experiments/20261009_live_camera_recording_30hz/deep_research/verify_live_source.py",
        ROOT / "docs/experiments/20261009_live_camera_recording_30hz/deep_research/optical_witness.py",
        ROOT / "docs/experiments/20261009_live_camera_recording_30hz/meaningful_episode/export_preview.py",
        *ROOT.glob("docs/experiments/20261009_live_camera_recording_30hz/temporal_physics/*.py"),
        ROOT / "tests/test_isaac_vr_live_source_queue.py",
        ROOT / "tests/test_isaac_vr_live_dataset.py",
        ROOT / "tests/test_isaac_vr_live_dataset_qa.py",
        ROOT / "tests/test_isaac_vr_live_video_import.py",
        ROOT / "tests/test_isaac_vr_replay.py",
        Path(__file__),
        *ROOT.glob("docs/experiments/20261009_live_camera_recording_30hz/resource30/*.py"),
    ]
    tests = [
        "test_docs_governance",
        "test_validator_baseline",
        "test_validator_negative",
        "test_manifest",
        "test_isaac_vr_recording",
        "test_isaac_vr_injected_recording",
        "test_isaac_s2_recording_runtime",
        "test_isaac_vr_recording_contract",
        "test_isaac_s2_processor",
        "test_isaac_s2_upstream",
        "test_isaac_vr_config",
        "test_isaac_vr_camera_rendering",
        "test_temporal_recording_path",
        "test_isaac_vr_live_media",
        "test_isaac_vr_live_source_queue",
        "test_isaac_vr_live_dataset",
        "test_isaac_vr_live_dataset_qa",
        "test_isaac_vr_live_video_import",
        "test_isaac_vr_replay",
        "test_isaac_vr_lerobot_materialize",
        "test_isaac_vr_asset_closure",
        "test_isaac_vr_visual_provenance",
        "test_isaac_vr_standalone_owner",
        "test_isaac_vr_standalone_scene",
        "test_isaac_vr_standalone_worker",
    ]
    raw_transcripts = [
        "docs/experiments/20261009_live_camera_recording_30hz/temporal_physics/temporal_audit/" + name
        for name in ("clock-codegraph.txt", "codegraph.txt", "master-s2.diff", "master.diff")
    ]
    whitespace_paths = [".", ":(exclude)**/*.log", *[":(exclude)" + p for p in raw_transcripts]]
    commands = [
        [py, "tools/lint_docs.py", "--base", args.base],
        [py, "tools/lint_spec_references.py"],
        [py, "tools/validate_resolved_contract.py", "configs/resolved_contract.yaml"],
        [py, "tools/generate_manifest.py", "verify"],
        [ruff, "check", *map(str, sources)],
        [py, "-m", "pytest", "-q", *[f"tests/{t}.py" for t in tests]],
        ["git", "diff", "--check", "--", *whitespace_paths],
        ["git", "diff", "--cached", "--check", "--", *whitespace_paths],
    ]
    receipt = dict(
        schema="single_gpu_repository_checks_v1",
        preservation_base=args.base,
        python=py,
        tested_head=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        dataset_admissible=False,
        gate_bindings=[],
        started_ns=time.time_ns(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        tested_sources={
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
        },
        checks=[],
    )
    env = os.environ.copy()
    env.update(HF_HOME="/tmp/live30-single-gpu-check-cache/hf",
               HF_DATASETS_CACHE="/tmp/live30-single-gpu-check-cache/hf-datasets")
    receipt["cache_environment"] = {key: env[key] for key in ("HF_HOME", "HF_DATASETS_CACHE")}
    receipt["raw_log_whitespace_excluded"] = True
    receipt["raw_transcript_whitespace_excluded"] = raw_transcripts
    receipt["raw_transcript_semantics"] = "Verbatim CodeGraph/git diff output; preserve trailing source-line tabs and diff context bytes"
    with (output / "results.log").open("w") as log:
        for cmd in commands:
            started = time.monotonic()
            proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
            row = dict(
                command=cmd,
                returncode=proc.returncode,
                elapsed_s=time.monotonic() - started,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
            receipt["checks"].append(row)
            log.write(json.dumps(cmd) + "\n" + proc.stdout + proc.stderr + "\n")
            log.flush()
    receipt["all_passed"] = all(r["returncode"] == 0 for r in receipt["checks"])
    (output / "results.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "all_passed": receipt["all_passed"],
                "failed": [r["command"] for r in receipt["checks"] if r["returncode"]],
            }
        )
    )
    return 0 if receipt["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
