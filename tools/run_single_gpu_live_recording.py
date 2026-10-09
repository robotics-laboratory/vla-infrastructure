"""Reproducible opt-in single4090 live-camera recording diagnostic.

Builds the current shared VR scene and canonical recorder, solves real upstream
DLS decisions against CPU PhysX snapshots, pumps passive Kit XR presentation,
and mirrors the same recorded source into three GPU NVENC streams. No robot I/O.
"""

# ruff: noqa: E402
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "docs/experiments/20261009_live_camera_recording_30hz/deep_research"
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(ROOT / "tools"))
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--output", type=Path, required=True)
p.add_argument("--frames", type=int, default=600)
p.add_argument("--warmup", type=int, default=60)
p.add_argument("--media-warmup", type=int, default=20)
p.add_argument("--media", choices=("none", "gpu"), default="gpu")
p.add_argument("--xr", action="store_true")
p.add_argument("--view-mode", choices=("original", "minimal"), default="original")
p.add_argument("--witness", action=argparse.BooleanOptionalAction, default=True)
p.add_argument(
    "--physics-python",
    type=Path,
    default=Path("/data/ebulochkin/vla-runtime/live30-deep-20261009/optional-ovphysx/bin/python"),
)
args = p.parse_args()
if args.frames < 2 or args.warmup < 0:
    p.error("frames must be>=2 and warmup>=0")
args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
receipt = dict(
    schema="single_gpu_live_recording_diagnostic_v1",
    passed=False,
    dataset_admissible=False,
    physical=False,
    quest_connected=False,
    input_source="deterministic_injected_xr_v1",
    upstream_dls_used_for_actuation=True,
    arguments={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
    started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    sources={
        str(f): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in [Path(__file__), *(ROOT / "tools").glob("isaac_vr_standalone*.py")]
    },
)
ns = None


def benchmark(env, cli, app, **unused):
    import numpy as np
    import torch
    import yaml
    from isaac_s2_performance import S2PerformanceLogger
    from isaac_s2_runtime import _BimanualDifferentialIk
    from isaac_vr_injected_recording import record_injected_transitions
    from isaac_vr_recording import start_live_recording
    from isaac_vr_recording_smoke import recording_session_metadata
    from isaac_vr_standalone import StandaloneState
    from live_mirror import LiveMirror, ROLES, sha

    torch.set_num_threads(1)
    perf = S2PerformanceLogger(
        args.output / "performance.jsonl", window_steps=60, warmup_steps=args.warmup, target_hz=50
    )
    cfg = yaml.safe_load(cli.config.read_text())
    owner = record = mirror = None
    try:
        owner = StandaloneState(env, args.output / "physics", python=args.physics_python)
        metadata = recording_session_metadata(
            config_path=cli.config,
            environment_pins=cfg["environment"],
            run_id="single_gpu_20261009",
            session_id="single_gpu_20261009",
            episode_id="single_gpu_episode",
            execution_profile="isaac_vr_record_injected_no_client_audit",
            processor_revision="piper_x_isaac_s2_bimanual_relative_v3",
        )
        record = start_live_recording(
            args.output / "episode",
            env,
            session_metadata=metadata,
            portable_roots={
                "recording": args.output,
                "isaac61_production": Path(cfg["environment"]["materialized_path"]).parent,
                "project_assets": Path(cfg["asset"]["source_checkout"]).parent,
                "runtime_assets": state / "assets",
            },
            standalone_state=owner,
        )
        owner.start(record.snapshot)
        if args.xr:
            from omni.kit.xr.core import XRCore

            receipt["xr_enabled_at_admission"] = XRCore.get_singleton().is_xr_enabled()
        ik = _BimanualDifferentialIk(env)
        if args.media == "gpu":
            guard = args.output / "mirror-source-preimages.json"
            protected = [
                ROOT / "tools/isaac_vr_recording.py",
                Path(__file__),
                HELPERS / "live_mirror.py",
                ROOT / "tools/isaac_vr_live_worker.py",
            ]
            guard.write_text(json.dumps({str(f): sha(f) for f in protected}, indent=2) + "\n")
            gpu_guard = args.output / "gpu-preimages.json"
            from isaac_vr_live_gpu import write_preimages

            write_preimages(gpu_guard)
            from ovrtx_live_probe import pose_matrices

            frames = record.sampler.capture_frame()
            matrices = []
            for r in record.recordables:
                e = r.to_manifest()
                if e["type"] not in ("articulation", "rigid_body", "camera"):
                    continue
                f = frames[e["group"]]
                plural = e["type"] == "articulation"
                m = pose_matrices(
                    f["positions" if plural else "position"],
                    f["orientations" if plural else "orientation"],
                )
                matrices.append(m if plural else m[None])
            initial = dict(
                matrix_bytes_hex=np.concatenate(matrices).astype("<f8").tobytes().hex(),
                intrinsics=[
                    [
                        float(frames["state/camera/" + role][k])
                        for k in ("focal_length", "horizontal_aperture", "vertical_aperture")
                    ]
                    for role in ROLES
                ],
                sim_time_s=owner.clock.physics_step / 120,
                reset_epoch=owner.clock.epoch,
                state_generation=owner.clock.physics_step,
                snapshot_id="warmup_only",
                snapshot_sha256="0" * 64,
            )
            mirror = LiveMirror(
                record,
                args.output / "mirror",
                witness=args.witness,
                worker=ROOT / "tools/isaac_vr_live_worker.py",
                guard_path=guard,
                extra_seed={
                    "single_gpu": dict(
                        initial_payload=initial,
                        warmup_frames=args.media_warmup,
                        source_minimum_time=initial["sim_time_s"],
                        gpu_preimage_path=str(gpu_guard.resolve()),
                    )
                },
            )

        def solve(command, observation, xr, tick):
            # Bounded periodic Cartesian intent, solved against the same O_t.
            phase = tick * 2 * np.pi / 120
            delta = np.array([0, 0.00015 * np.cos(phase), 0.0001 * np.sin(phase), 0, 0, 0])
            command = replace(
                command,
                left=replace(
                    command.left, delta_pose=delta, gripper_aperture_m=0.04 + 0.01 * np.sin(phase)
                ),
                right=replace(
                    command.right, delta_pose=-delta, gripper_aperture_m=0.04 - 0.01 * np.sin(phase)
                ),
            )
            return ik.solve(command, observation, xr, tick)

        started_ns = time.perf_counter_ns()
        started = started_ns / 1e9
        transitions = record_injected_transitions(
            record,
            env,
            count=args.warmup + args.frames,
            performance_logger=perf,
            require_distinct_actions=False,
            decision_solver=solve,
        )
        working_end = time.perf_counter()
        summary = perf.close()
        if mirror:
            receipt["mirror"] = mirror.finish()
            encode_done = max(int(working_end * 1e9), receipt["mirror"]["worker"]["encode_done_ns"])
            receipt["complete_action_and_camera_hz_with_encode_tail"] = (
                (args.warmup + args.frames) * 1e9 / (encode_done - started_ns)
            )
        completed_end = time.perf_counter()
        receipt.update(
            transitions={k: v for k, v in transitions.items() if k != "actions"},
            performance=summary,
            working_s=working_end - started,
            drain_and_optical_decode_s=completed_end - working_end,
            complete_hz_including_drain=(args.warmup + args.frames) / (completed_end - started),
            source_owner=owner.receipt,
            camera_source_alignment_proven=False,
        )
        if args.xr:
            receipt["xr_enabled_at_stop"] = XRCore.get_singleton().is_xr_enabled()
        record.close(outcome="operator_stopped", reason="single_gpu_experimental_diagnostic")
        record = None
        if mirror:
            run = subprocess.run(
                [
                    sys.executable,
                    str(HELPERS / "verify_live_source.py"),
                    "--input",
                    str(args.output),
                    "--output",
                    str(args.output / "source-join.json"),
                ],
                capture_output=True,
                text=True,
            )
            (args.output / "source-join.log").write_text(run.stdout + run.stderr)
            if run.returncode:
                raise RuntimeError("persisted state/media source join failed")
            receipt["camera_source_alignment_proven"] = True
        receipt["passed"] = True
        return 0
    finally:
        errors = []
        cleanup = [
            mirror.abort if mirror else None,
            (
                lambda: record.close(
                    outcome="failure", reason="single_gpu_experimental_diagnostic_failed"
                )
            )
            if record
            else None,
            owner.close if owner else None,
            perf.close if not perf._closed else None,
        ]
        for release in cleanup:
            if release is not None:
                try:
                    release()
                except BaseException:
                    errors.append(traceback.format_exc())
        if owner:
            receipt["source_owner"] = owner.receipt
        receipt["cleanup_errors"] = errors
        if errors:
            receipt["passed"] = False
            raise RuntimeError("single-GPU cleanup failed; inspect retained cleanup_errors")


try:
    from isaac_demo_launch import (
        verify_stack,
        user_environment,
        write_runtime_config,
        configure_cloudxr,
    )

    stack = verify_stack("isaac61")
    environment, state = user_environment(stack, "isaac61")
    os.environ.update(environment)
    config = write_runtime_config(ROOT, stack, state, args.output)
    kit = [
        "--portable-root",
        str(state / "kit"),
        "--enable",
        "isaacsim.replicator.episode_recorder",
    ]
    if args.xr:
        kit += ["--enable", "omni.kit.scene_view.xr", "--enable", "omni.kit.scene_view.xr_utils"]
        os.environ["VLA_CLOUDXR_INSTALL_DIR"] = str(state / "cloudxr")
        configure_cloudxr(os.environ, mode="auto", dry_run=False)
    sys.argv = [
        str(ROOT / "tools/run_isaac_s1.py"),
        "--config",
        str(config),
        "--device",
        "cpu",
        "--vr-runtime",
        "--s2-record",
        "--viz",
        "kit",
        "--kit_args",
        shlex.join(kit),
    ]
    if args.xr:
        sys.argv += ["--xr"]
    receipt["base_command"] = sys.argv.copy()
    ns = runpy.run_path(str(ROOT / "tools/run_isaac_s1.py"), run_name="single_gpu_shared_base")
    if args.xr:
        from isaaclab_teleop.isaac_teleop_device import _enable_teleop_bridge
        from omni.kit.xr.core import XRCore

        _enable_teleop_bridge()
        XRCore.get_singleton().request_enable_profile("ar")
        receipt["xr_profile_enabled"] = XRCore.get_singleton().is_xr_enabled()
    import isaac_s2_runtime

    if args.view_mode == "minimal":
        import carb.settings

        settings = carb.settings.get_settings()
        receipt["view_settings_before"] = {
            key: settings.get(key) for key in ("/rtx/rendermode", "/rtx/minimal/mode")
        }
        settings.set("/rtx/rendermode", "MinimalRendering")
        settings.set("/rtx/minimal/mode", 2)
    isaac_s2_runtime.run_s2 = benchmark
    ns["main"]()
except BaseException:
    receipt["passed"] = False
    receipt["error"] = traceback.format_exc()
    print(receipt["error"], flush=True)
finally:
    receipt["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (args.output / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if ns:
        owned = ns.get("owned_cloudxr")
        if owned is not None:
            from omni.kit.xr.core import XRCore

            xr = XRCore.get_singleton()
            xr.request_disable_profile()
            for _ in range(120):
                ns["simulation_app"].update()
                if not xr.is_xr_enabled():
                    break
            else:
                raise RuntimeError("owned XR profile did not stop; server retained")
            owned.stop()
        ns["simulation_app"].close()
raise SystemExit(0 if receipt["passed"] else 1)
