"""Run native committed RECORD transitions inside the already-active XR session."""

import importlib.metadata
import json
import os
from pathlib import Path
import time
from uuid import uuid4


def run(env, args, out):
    from isaac_s2_performance import S2PerformanceLogger
    from isaac_vr_injected_recording import record_injected_transitions
    from isaac_vr_recording import start_live_recording
    from isaac_vr_recording_smoke import recording_portable_roots, recording_session_metadata
    from omni.kit.xr.core import XRCore, XRSettings
    import yaml

    core = XRCore.get_singleton()
    if not core.is_xr_enabled() or not core.is_xr_display_enabled():
        raise RuntimeError("XR rendering is not active; refuse XR camera-cost claim")
    xr = XRSettings.get_singleton()
    readback = {
        key: xr.get_setting(key)
        for key in (
            "profile/persistent/renderQuality",
            "profile/persistent/render/resolutionMultiplier",
            "profile/persistent/foveation/mode",
            "status/renderResolution",
        )
    }
    (out / "xr-readback.json").write_text(json.dumps(readback, indent=2, default=str) + "\n")
    warmup = int(os.environ["CAMERA_AUDIT_WARMUP"])
    measured = int(os.environ["CAMERA_AUDIT_MEASURED"])
    logger = S2PerformanceLogger(
        out / "xr-performance.jsonl", window_steps=measured, warmup_steps=warmup, target_hz=30
    )
    previous = env.performance_logger
    env.performance_logger = logger
    if os.environ.get("CAMERA_AUDIT_STATE_BATCH") == "1":
        # Both articulation buffers are read at the same causal boundary. Keep
        # their native order and check the first ten warmup snapshots byte for byte.
        from isaac_s1_runtime import native_state_to_d0
        from isaac_vr_runtime import _tensor
        import numpy as np
        import torch

        original_state = env.capture_measured_state
        parity = {"checked": 0, "exact": True, "host_transfers_per_capture": 1}

        def batched_state():
            before = env.sim.get_physics_step_count()
            parts = [_tensor(robot.data.joint_pos)[0, ids] for robot, ids in
                     zip(env.robots, env.joint_ids, strict=True)]
            sizes = [part.numel() for part in parts]
            contiguous = torch.cat(parts).detach().cpu().numpy()
            native = np.split(contiguous, np.cumsum(sizes)[:-1])
            if before != env.sim.get_physics_step_count() or before != env._state_physics_step:
                raise RuntimeError("Articulation state generation changed during capture")
            result = before, tuple(float(value) for value in native_state_to_d0(*native))
            if parity["checked"] < 10:
                reference = original_state()
                parity["checked"] += 1
                if result != reference:
                    parity["exact"] = False
                    raise RuntimeError("batched native state differs from original at same boundary")
            return result

        env.capture_measured_state = batched_state
    config = yaml.safe_load(Path(args.s2_config).read_text())
    expected = config["environment"]
    pins = {
        "isaac_sim": importlib.metadata.version("isaacsim"),
        "isaac_lab_package": importlib.metadata.version("isaaclab"),
        "isaac_lab_release": expected["isaac_lab_release"],
        "isaacteleop": importlib.metadata.version("isaacteleop"),
        "isaaclab_teleop": importlib.metadata.version("isaaclab-teleop"),
        "cloudxr": expected["cloudxr_runtime_version"],
    }
    env.vr_runtime.prepare_recording_view()
    args.s2_recording_dir = out / "recording"
    recording = start_live_recording(
        out / "recording",
        env,
        session_metadata=recording_session_metadata(
            xr_render=getattr(args, "xr_render_readback", None),
            config_path=Path(args.s2_config),
            environment_pins=pins,
            run_id=str(uuid4()),
            session_id=str(uuid4()),
            episode_id="episode_000000",
            execution_profile="experiment_xr_injected_record",
            processor_revision=config["processor"]["revision"],
        ),
        portable_roots=recording_portable_roots(args),
        flush_every_frames=int(os.environ.get("CAMERA_AUDIT_FLUSH_EVERY", "64")),
        timing_observer=logger.add_nested,
    )
    (out / "recording-policy.json").write_text(
        json.dumps(
            {
                "requested_flush_every_frames": int(os.environ.get("CAMERA_AUDIT_FLUSH_EVERY", "64")),
                "effective_flush_every_frames": recording.flush_every_frames,
                "durability": "periodic flush plus terminal close; larger interval delays periodic durability",
            },
            indent=2,
        )
        + "\n"
    )
    breakdown_counts: dict[str, int] = {}
    if os.environ.get("CAMERA_AUDIT_STATE_BREAKDOWN") == "1":
        import isaac_vr_recording as recording_module

        def timed(owner, attribute, name):
            original = getattr(owner, attribute)

            def call(*args, **kwargs):
                started = time.perf_counter_ns()
                try:
                    return original(*args, **kwargs)
                finally:
                    breakdown_counts[name] = breakdown_counts.get(name, 0) + 1
                    logger.add_nested(name, time.perf_counter_ns() - started)

            setattr(owner, attribute, call)

        timed(env, "capture_measured_state", "state_native_joint_reads")
        timed(recording, "_observation_factory", "state_observation_factory")
        timed(recording.sampler, "capture_frame", "state_fabric_frame")
        timed(recording_module, "_to_numpy_f32", "state_pose_host_conversion")
        timed(recording_module, "_captured_frame_sha256", "state_digest")
    try:
        result = record_injected_transitions(
            recording, env, count=warmup + measured, performance_logger=logger
        )
        result.update(
            xr_enabled=core.is_xr_enabled(),
            xr_display=core.is_xr_display_enabled(),
            physical_quest=False,
            actual_xr_input_used=False,
            input="existing bounded injected native targets",
            completed=True,
        )
        recording.close(outcome="operator_stopped", reason="automated_benchmark_completed")
        if breakdown_counts:
            (out / "state-breakdown-counts.json").write_text(
                json.dumps(breakdown_counts, indent=2) + "\n"
            )
        if os.environ.get("CAMERA_AUDIT_STATE_BATCH") == "1":
            (out / "state-batch-parity.json").write_text(json.dumps(parity, indent=2) + "\n")
        if os.environ.get("CAMERA_AUDIT_OPERATOR_SCREENSHOT") == "1":
            screenshot = out / "operator-viewport.png"
            status: dict[str, object] = {
                "path": str(screenshot), "scope": "desktop XR viewport after measured window"
            }
            try:
                from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport

                viewport = get_active_viewport()
                if viewport is None:
                    raise RuntimeError("no active viewport")
                capture_viewport_to_file(viewport, file_path=str(screenshot))
                for _ in range(60):
                    env.sim.render()
                    if screenshot.is_file() and screenshot.stat().st_size:
                        break
                status["captured"] = screenshot.is_file() and screenshot.stat().st_size > 0
            except Exception as exc:
                status.update(captured=False, error=f"{type(exc).__name__}: {exc}")
            (out / "operator-screenshot-status.json").write_text(
                json.dumps(status, indent=2) + "\n"
            )
        (out / "xr-cost-result.json").write_text(json.dumps(result, indent=2))
    except Exception:
        recording.close(outcome="failure", reason="experiment_failed")
        raise
    finally:
        logger.close()
        env.performance_logger = previous
