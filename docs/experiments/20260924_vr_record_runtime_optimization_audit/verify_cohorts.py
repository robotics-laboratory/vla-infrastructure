"""Check exact runtime invariants for every selected performance process."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = Path("/data/ebulochkin/vla-runtime/evidence/20260924_vr_record_runtime_optimization_audit")
PINNED_FILES = (
    "configs/isaac61_s1_runtime.yaml",
    "configs/isaac61_s2_runtime.yaml",
    "configs/isaac61_vr_runtime.yaml",
    "tools/run_isaac_s1.py",
    "tools/isaac_s2_runtime.py",
    "tools/isaac_vr_recording.py",
    "tools/isaac_vr_injected_recording.py",
)


def main() -> None:
    cohorts = json.loads((HERE / "cohorts.json").read_text())
    expected_pins = None
    output = []
    for group in cohorts["groups"]:
        for name in group["runs"]:
            path = RAW / name
            launch = json.loads((path / "launch.json").read_text())
            args = launch["arguments"]
            assert launch["exit_code"] == 0, name
            assert args["temporal"] == "t0" and args["cost"] == "c0", name
            assert args["mode"] == "xr-smoke" and args["warmup"] == 300, name
            assert args["state_root"] == "/data/ebulochkin/vla-runtime/isaac-isaac61", name
            pins = {file: launch["source_hashes"][file] for file in PINNED_FILES}
            if expected_pins is None:
                expected_pins = pins
            assert pins == expected_pins, name
            measured = args["measured"]
            all_rows = [json.loads(line) for line in (path / "mechanisms.jsonl").read_text().splitlines()]
            # Ten DIAG startup ticks precede the warmup and measured XR control loop.
            rows = all_rows[10 + args["warmup"]: 10 + args["warmup"] + measured]
            assert len(rows) == measured, (name, len(rows), measured)
            assert all(row["physics_delta"] == 4 for row in rows), name
            assert all(row["counts"]["native_physics"] == 4 for row in rows), name
            assert all(row["counts"]["kit"] == 1 for row in rows), name
            assert all(row["render_flags"] == [False, False, False, True] for row in rows), name
            assert all(row["render_delta"] == 1 for row in rows), name
            assert all(not any(row["products_enabled"]) and not row["panels_bound"] for row in rows), name
            xr = json.loads((path / "xr-readback.json").read_text())
            assert xr["profile/persistent/renderQuality"] == "performance", name
            assert xr["profile/persistent/foveation/mode"] == (
                "none" if group["id"] == "XR-none" else "warped"
            ), name
            assert xr["profile/persistent/render/resolutionMultiplier"] == args["xr_scale"], name
            effective_renderer = json.loads((path / "settings-after.json").read_text())
            renderer = "MinimalRendering" if group["id"] == "R1" else "RealTimePathTracing"
            assert effective_renderer["/rtx/rendermode"] == renderer, name
            if renderer == "MinimalRendering":
                assert effective_renderer["/rtx/minimal/mode"] == 2, name
            policy_file = path / "recording-policy.json"
            if policy_file.is_file():
                policy = json.loads(policy_file.read_text())
                effective_flush = policy["effective_flush_every_frames"]
                flush_evidence = "runtime readback"
            else:
                # Two renderer screens predate the flush observer; the exact
                # pinned LiveRecording default and requested value are both 64.
                assert args["flush_every"] == 64, name
                effective_flush = 64
                flush_evidence = "pinned source default, no runtime readback"
            assert effective_flush == args["flush_every"], name
            manifest = json.loads((path / "recording/manifest.json").read_text())
            assert manifest["artifact_state"] == "finalized", name
            assert manifest["committed_frames"] == args["warmup"] + measured, name
            terminal = manifest["terminal_successor"]
            assert terminal and (path / "recording" / terminal["file"]).is_file(), name
            assert (path / "recording/session.hdf5").is_file(), name
            output.append({
                "run": name,
                "group": group["id"],
                "checked_controls": len(rows),
                "native_physics_per_control": 4,
                "kit_pumps_per_control": 1,
                "render_flags": "F,F,F,T",
                "dataset_render_products_enabled": 0,
                "preview_panels_ever_bound_in_window": False,
                "renderer_effective": renderer,
                "xr_readback": xr,
                "flush_every_effective": effective_flush,
                "flush_evidence": flush_evidence,
                "committed_frames": manifest["committed_frames"],
                "launch_sha256": hashlib.sha256((path / "launch.json").read_bytes()).hexdigest(),
            })
    (HERE / "cohort-check.json").write_text(json.dumps({
        "schema": "vr_record_runtime_cohort_check_v1",
        "passed": True,
        "selected_runs": len(output),
        "pins_sha256": expected_pins,
        "runs": output,
    }, indent=2) + "\n")
    print(f"PASS {len(output)} selected runs; four native integrations and F,F,F,T throughout")


if __name__ == "__main__":
    main()
