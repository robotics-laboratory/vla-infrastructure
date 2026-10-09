"""Read-only repository checks, with retained commands and outputs for this bundle."""

from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[3]
BASE = "d5566834d29ef8bb56e4fb62bb324e23e0869100"
IMMUTABLE_SOURCES = {
    "decode_clock_initial.py",
    "pynv223_adapter_initial.py",
    "ovphysx_fixedbase_probe.py",
    "ovphysx_fixedbase_author.py",
    "matched_cpu_map_ovrtx_snapshot.py",
    "matched_cpu_map_optical_witness.py",
}
WHITESPACE_EXCLUSIONS = [
    ":(exclude)**/*.log",
    ":(exclude)docs/experiments/20261009_live_camera_recording_30hz/deep_research/ovphysx_fixedbase_v2.usda",
    ":(exclude)docs/experiments/20261009_live_camera_recording_30hz/deep_research/pynv223_adapter_initial.py",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipt = output / "checks.json"
    if receipt.exists() and json.loads(receipt.read_text()).get("checks"):
        raise FileExistsError("Preserve existing checks; select a new output directory")
    env = os.environ.copy()
    env.update(
        HF_HOME="/tmp/live30-check-cache/hf",
        HF_DATASETS_CACHE="/tmp/live30-check-cache/hf-datasets",
    )
    py = sys.executable
    ruff = str(Path(py).with_name("ruff"))
    maintained = [
        str(p.relative_to(ROOT))
        for p in sorted(BUNDLE.glob("*.py"))
        if p.name not in IMMUTABLE_SOURCES
    ]
    commands = [
        [py, "tools/lint_docs.py", "--base", BASE],
        [py, "tools/lint_spec_references.py"],
        [py, "tools/validate_resolved_contract.py", "configs/resolved_contract.yaml"],
        [py, "tools/generate_manifest.py", "verify"],
        [ruff, "check", *maintained],
        [ruff, "format", "--check", *maintained],
        [
            py,
            "-m",
            "pytest",
            "-q",
            "tests/test_docs_governance.py",
            "tests/test_validator_baseline.py",
            "tests/test_validator_negative.py",
            "tests/test_manifest.py",
            "tests/test_isaac_vr_recording.py",
            "tests/test_isaac_vr_config.py",
            "tests/test_isaac_vr_camera_rendering.py",
            "tests/test_temporal_recording_path.py",
        ],
        ["git", "diff", "--check", "--", ".", *WHITESPACE_EXCLUSIONS],
        ["git", "diff", "--cached", "--check", "--", ".", *WHITESPACE_EXCLUSIONS],
    ]
    result = dict(
        schema="live30_repository_checks_v1",
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        preservation_base=BASE,
        tested_head=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        python=py,
        gate_bindings=[],
        physical_qualification=False,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        tested_python_sources={
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(BUNDLE.glob("*.py"))
        },
        immutable_ruff_exclusions=sorted(IMMUTABLE_SOURCES),
        raw_log_whitespace_excluded=True,
        whitespace_exclusions=WHITESPACE_EXCLUSIONS,
        whitespace_scope="Retained original log/SDK USD/failed-source bytes are not reformatted",
        checks=[],
    )
    with (output / "checks.log").open("w") as log:
        for command in commands:
            print("Checking", command[:3], flush=True)
            started = time.monotonic()
            proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
            log.write(json.dumps(command) + "\n" + proc.stdout + proc.stderr + "\n")
            log.flush()
            result["checks"].append(
                dict(
                    command=command,
                    returncode=proc.returncode,
                    elapsed_s=time.monotonic() - started,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                )
            )
        errors = []
        files = sorted(BUNDLE.glob("*.py"))
        for path in files:
            try:
                compile(path.read_bytes(), str(path), "exec")
            except Exception as exc:
                errors.append(dict(path=str(path), error=repr(exc)))
        result["syntax_compile"] = dict(
            files=len(files),
            errors=errors,
            passed=not errors,
            scope="Syntax only, including immutable failed-attempt snapshots",
        )
        result["all_passed"] = not errors and all(
            row["returncode"] == 0 for row in result["checks"]
        )
        log.write(json.dumps(result["syntax_compile"]) + "\n")
    receipt.write_text(json.dumps(result, indent=2) + "\n")
    print("all_passed", result["all_passed"], flush=True)
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
