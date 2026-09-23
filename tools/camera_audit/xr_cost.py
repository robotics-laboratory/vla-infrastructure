"""Run native committed RECORD transitions inside the already-active XR session."""

import importlib.metadata
import json
import os
from pathlib import Path
from uuid import uuid4


def run(env, args, out):
    from isaac_s2_performance import S2PerformanceLogger
    from isaac_vr_injected_recording import record_injected_transitions
    from isaac_vr_recording import start_live_recording
    from isaac_vr_recording_smoke import recording_portable_roots, recording_session_metadata
    from omni.kit.xr.core import XRCore
    import yaml

    core = XRCore.get_singleton()
    if not core.is_xr_enabled() or not core.is_xr_display_enabled():
        raise RuntimeError("XR rendering is not active; refuse XR camera-cost claim")
    warmup = int(os.environ["CAMERA_AUDIT_WARMUP"])
    measured = int(os.environ["CAMERA_AUDIT_MEASURED"])
    logger = S2PerformanceLogger(
        out / "xr-performance.jsonl", window_steps=measured, warmup_steps=warmup, target_hz=30
    )
    previous = env.performance_logger
    env.performance_logger = logger
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
        timing_observer=logger.add_nested,
    )
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
        (out / "xr-cost-result.json").write_text(json.dumps(result, indent=2))
    except Exception:
        recording.close(outcome="failure", reason="experiment_failed")
        raise
    finally:
        logger.close()
        env.performance_logger = previous
