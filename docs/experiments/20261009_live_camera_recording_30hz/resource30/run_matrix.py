"""Serial, bounded resource comparison; every attempt uses a fresh output root."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
ISAAC = "/data/vla-infrastructure/isaac61_production/env/bin/python"
PRIOR = Path("/data/ebulochkin/vla-runtime/live30-dataset-20261010")


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qa-workers", type=int, choices=(0, 2, 4), required=True)
    parser.add_argument("--cases", nargs="+", default=None)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sources = sorted(
        {
            *ROOT.glob("tools/isaac_vr_*.py"),
            *ROOT.glob("tools/isaac_s2_*.py"),
            ROOT / "tools/run_single_gpu_live_recording.py",
            *Path(__file__).parent.glob("*.py"),
        }
    )
    snapshot = args.output / "sources"
    snapshot.mkdir()
    hashes = {}
    for path in sources:
        content = path.read_bytes()
        relative = path.relative_to(ROOT)
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        hashes[str(relative)] = hashlib.sha256(content).hexdigest()
    save(args.output / "source-sha256.json", hashes)
    cases = [
        ("paced-all-quiet", 30, list(range(24)), None),
        ("paced-p-quiet", 30, list(range(16)), None),
        ("paced-p-shared", 30, list(range(16)), list(range(16))),
        ("paced-p-isolated", 30, list(range(16)), list(range(16, 20))),
        ("uncapped-all-quiet", 0, list(range(24)), None),
        ("uncapped-p-quiet", 0, list(range(16)), None),
        ("uncapped-p-isolated", 0, list(range(16)), list(range(16, 20))),
    ]
    if args.cases:
        if set(args.cases) - {v[0] for v in cases}:
            parser.error("Unknown case")
        cases = [v for v in cases if v[0] in args.cases]
    outcomes = []
    for name, pace, affinity, background_affinity in cases:
        case = args.output / name
        case.mkdir()
        rec = case / "recording"
        config = dict(
            argv=[
                ISAAC,
                str(ROOT / "tools/run_single_gpu_live_recording.py"),
                "--output",
                str(rec),
                "--frames",
                "840" if pace else "1800",
                "--warmup",
                "120",
                "--xr",
                "--motion",
                "reach-demo",
                "--no-witness",
                "--audit-host-events",
                "--pace-hz",
                str(pace),
                "--source-queue-capacity",
                "1",
            ],
            cwd=str(ROOT),
            affinity=affinity,
            nice=0,
            timeout_s=300,
            lock_file=str(args.output / ".recording-assay.lock"),
            recording_output=str(rec),
            interval_s=0.5,
            env=dict(
                OMNI_KIT_ACCEPT_EULA="Y",
                ISAACLAB_CXR_ACCEPT_EULA="1",
                PYTHONDONTWRITEBYTECODE="1",
                CUDA_DEVICE_MAX_CONNECTIONS="1",
            ),
        )
        command = [
            sys.executable,
            str(Path(__file__).with_name("run_resource_assay.py")),
            "--config",
            str(case / "recording-config.json"),
            "--output",
            str(case / "assay"),
        ]
        if background_affinity is not None:
            config["background_trigger"] = dict(
                path=str(rec / "performance.jsonl"),
                match=dict(event="performance_step", post_warmup=True),
                timeout_s=120,
            )
            bg = dict(
                argv=[
                    sys.executable,
                    str(ROOT / "tools/isaac_vr_live_dataset.py"),
                    "materialize",
                    "--prepared",
                    str(PRIOR / "prepared-reach03"),
                    "--output",
                    str(case / "dataset"),
                    "--repo-id",
                    "local/resource30-" + name,
                    "--qa-workers",
                    str(args.qa_workers),
                ],
                cwd=str(ROOT),
                affinity=background_affinity,
                nice=10,
                timeout_s=900,
                env=dict(
                    HF_HOME=str(case / "cache/hf"),
                    HF_DATASETS_CACHE=str(case / "cache/hf-datasets"),
                    OMP_NUM_THREADS="1",
                    MKL_NUM_THREADS="1",
                    PYTHONDONTWRITEBYTECODE="1",
                ),
            )
            save(case / "background-config.json", bg)
            command.extend(["--background-command-file", str(case / "background-config.json")])
        save(case / "recording-config.json", config)
        started = time.time_ns()
        print(json.dumps(dict(event="case_started", case=name, unix_ns=started)), flush=True)
        with (
            (case / "harness.stdout").open("xb") as out,
            (case / "harness.stderr").open("xb") as err,
        ):
            process = subprocess.run(command, stdout=out, stderr=err)
        row = dict(
            case=name,
            command=command,
            started_unix_ns=started,
            finished_unix_ns=time.time_ns(),
            returncode=process.returncode,
        )
        outcomes.append(row)
        save(args.output / "matrix.json", outcomes)
        print(json.dumps(dict(event="case_finished", **row)), flush=True)
        if process.returncode:
            return process.returncode
    unchanged = all(
        hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha for p, sha in hashes.items()
    )
    save(args.output / "source-unchanged.json", dict(passed=unchanged))
    return 0 if unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
