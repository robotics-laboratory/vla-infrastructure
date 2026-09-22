"""No-client Episode Recorder lifecycle smoke, isolated from XR/teleop imports."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml


def recording_portable_roots(args_cli) -> dict[str, Path]:
    s1_config = yaml.safe_load(Path(args_cli.config).read_text(encoding="utf-8"))
    return {
        "recording": Path(args_cli.s2_recording_dir),
        "isaac61_production": Path(s1_config["environment"]["materialized_path"]).parent,
        "project_assets": Path(s1_config["asset"]["source_checkout"]).parent,
    }


def recording_session_metadata(
    *,
    config_path: Path,
    environment_pins: dict[str, Any],
    run_id: str,
    session_id: str,
    episode_id: str,
    execution_profile: str,
    processor_revision: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "session_id": session_id,
        "episode_id": episode_id,
        "source_profile": "isaac_human_vr_offline_rgb_v1",
        "task": "dual_cube_to_matching_plates",
        "execution_profile": execution_profile,
        "live_rgb": False,
        "d0_revision": processor_revision,
        "runtime_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "environment_pins": environment_pins,
    }


def run_recording_lifecycle_smoke(
    env,
    args_cli,
    *,
    default_config_path: Path,
    processor_revision: str,
) -> int:
    """Exercise recording capture/finalization without importing XR or teleop."""

    from isaac_vr_recording import start_live_recording

    config_path = Path(getattr(args_cli, "s2_config", None) or default_config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["processor"]["revision"] != processor_revision:
        raise RuntimeError("S2 processor config/code revision mismatch")
    if not getattr(args_cli, "s2_record", False) or args_cli.s2_recording_dir is None:
        raise ValueError("recording lifecycle smoke requires --s2-recording-dir")
    if getattr(args_cli, "s2_teleop", False) or getattr(args_cli, "xr", False):
        raise ValueError("recording lifecycle smoke must not initialize teleop or XR")

    expected = config["environment"]
    environment_pins = {
        "isaac_sim": importlib.metadata.version("isaacsim"),
        "isaac_lab_package": importlib.metadata.version("isaaclab"),
        "isaac_lab_release": expected["isaac_lab_release"],
        "isaacteleop": importlib.metadata.version("isaacteleop"),
        "isaaclab_teleop": importlib.metadata.version("isaaclab-teleop"),
        "cloudxr_expected_not_initialized": expected["cloudxr_runtime_version"],
    }
    experiment = getattr(env, "vr_runtime", None)
    recording = None
    summary: dict[str, Any] = {}
    try:
        if experiment is not None:
            experiment.disable_live_rgb()
        # The caller has already reset, settled and validated this exact scene.
        # A second reset would invalidate the accepted three-camera boundary and
        # make this lifecycle probe exercise renderer startup instead of storage.
        run_id, session_id = str(uuid4()), str(uuid4())
        episode_id = "episode_000000"
        recording = start_live_recording(
            args_cli.s2_recording_dir,
            env,
            session_metadata=recording_session_metadata(
                config_path=config_path,
                environment_pins=environment_pins,
                run_id=run_id,
                session_id=session_id,
                episode_id=episode_id,
                execution_profile="isaac_vr_record_no_client_lifecycle_smoke",
                processor_revision=processor_revision,
            ),
            portable_roots=recording_portable_roots(args_cli),
        )
        token = recording.capture_observation()
        recording.discard_observation(token, reason="no_client_lifecycle_smoke")
        summary = {
            "artifact_state": "failed",
            "committed_frames": 0,
            "discarded_observations": recording.discarded_observations,
            "episode_id": recording.episode_id,
            "mode": "recording_lifecycle_smoke",
            "outcome": "aborted",
            "passed": True,
            "reason": "no_client_lifecycle_smoke",
            "run_id": recording.run_id,
            "session_id": recording.session_id,
            "teleop_initialized": False,
            "xr_initialized": False,
        }
        recording.close(outcome="aborted", reason="no_client_lifecycle_smoke")
        recording = None
    except Exception as exc:
        if recording is not None:
            recording.close(
                outcome="failure",
                reason=f"recording_lifecycle_smoke_failed:{type(exc).__name__}:{exc}",
            )
        raise
    finally:
        if experiment is not None:
            experiment.close()
    if getattr(args_cli, "report", None) is not None:
        Path(args_cli.report).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0
