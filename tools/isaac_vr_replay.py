"""State-only NVIDIA Episode Recorder replay and optional RGB materialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def apply_replay_frames(replayer: Any, frames: int, *, pump: Any, physics_steps: Any,
                        materialize: Any | None = None) -> None:
    """Apply every state frame while proving the caller never advances PhysX."""
    before = physics_steps()
    for frame in range(frames):
        replayer.apply_frame(frame)
        pump()
        if materialize is not None:
            materialize(frame)
    after = physics_steps()
    if after != before:
        raise RuntimeError(f"replay advanced physics: {before} -> {after}")


def _render_frame(camera_paths: dict[str, str], output_dir: Path, frame: int) -> list[dict[str, Any]]:
    """Synchronously materialize the three recorded camera roles without PhysX."""
    import omni.kit.async_engine
    import omni.replicator.core as rep
    from PIL import Image

    output_dir.mkdir(parents=True, exist_ok=True)
    products = {role: rep.create.render_product(path, (640, 480), force_new=True)
                for role, path in camera_paths.items()}
    annotators = {role: rep.AnnotatorRegistry.get_annotator("rgb") for role in products}
    for role, annotator in annotators.items():
        annotator.attach(products[role])
    try:
        # The installed public API has no synchronous step; waiting for its public
        # coroutine is the pinned synchronous capture path.
        omni.kit.async_engine.run_coroutine(rep.orchestrator.step_async()).result()
        rendered = []
        for role, annotator in annotators.items():
            image = np.asarray(annotator.get_data())
            if image.shape != (480, 640, 4) and image.shape != (480, 640, 3):
                raise RuntimeError(f"{role}: unexpected RGB shape {image.shape}")
            path = output_dir / f"frame_{frame:06d}_{role}.png"
            Image.fromarray(image[..., :3]).save(path)
            rendered.append({"role": role, "frame": frame, "path": str(path)})
        return rendered
    finally:
        for annotator in annotators.values():
            annotator.detach()
        for product in products.values():
            product.destroy()


def replay_snapshot(simulation_app: Any, *, recording: Path, episode: int,
                    render_cameras: Path | None, report_path: Path) -> int:
    """Open the recorded snapshot, then apply its state tracks without PhysX."""
    from isaac_vr_recording import ensure_d0_recordable, ensure_episode_recorder_enabled

    if not recording.is_file():
        raise FileNotFoundError(f"recording HDF5 not found: {recording}")
    snapshot = recording.parent / "stage_snapshot.usd"
    if not snapshot.is_file():
        raise FileNotFoundError(f"recording stage snapshot not found: {snapshot}")
    ensure_episode_recorder_enabled()
    from isaacsim.replicator.episode_recorder import EpisodeReplayer, SessionReader

    ensure_d0_recordable()
    sidecar_manifest = recording.parent / "manifest.json"
    if not sidecar_manifest.is_file():
        raise FileNotFoundError(f"recording manifest not found: {sidecar_manifest}")
    sidecar = json.loads(sidecar_manifest.read_text())
    expected_snapshot_hash = sidecar.get("stage_snapshot_sha256")
    if expected_snapshot_hash is not None:
        import hashlib
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != expected_snapshot_hash:
            raise RuntimeError("recording stage snapshot hash does not match manifest")
    with SessionReader(str(recording)) as reader:
        episodes = reader.list_episodes()
        if not episodes:
            raise RuntimeError("recording contains no episodes")
        episode_name = reader.normalize_episode(episode)
        frames = reader.num_frames(episode_name)
        if frames == 0:
            raise RuntimeError("recording episode contains no frames")
        manifest = reader.manifest()
        tracks = {str(track["group"]): str(track["type"]) for track in manifest.tracks}
        required = {"state/left_robot", "state/right_robot", "state/camera/left_wrist",
                    "state/camera/right_wrist", "state/camera/scene", "d0/transition"}
        missing = required - set(tracks)
        if missing:
            raise RuntimeError(f"recording missing required tracks: {sorted(missing)}")
        d0 = reader.read_group_all_frames(episode_name, "d0/transition")
        observation_ids = d0["observation_id"].astype(np.int64)
        if not np.array_equal(observation_ids, np.arange(frames, dtype=np.int64)):
            raise RuntimeError("D0 observation IDs are not exact control-boundary order")
        valid = d0["action_valid"].astype(bool)
        if valid[0] or np.any(d0["action_from_observation_id"][valid] != observation_ids[valid] - 1) or np.any(d0["action_to_observation_id"][valid] != observation_ids[valid]):
            raise RuntimeError("D0 action/state transition indexing is invalid")
        if (np.any(d0["transition_completed"][valid] != 1)
                or np.any(d0["action_source_physics_step"][valid] >= d0["observation_physics_step"][valid])
                or np.any(d0["action_source_render_generation"][valid] > d0["observation_render_generation"][valid])):
            raise RuntimeError("D0 action has no completed state-only successor")
        if any(not np.isfinite(values).all() for values in d0.values() if np.issubdtype(values.dtype, np.floating)):
            raise RuntimeError("D0 contains NaN/Inf")
    camera_paths = sidecar.get("camera_roles")
    if not isinstance(camera_paths, dict) or set(camera_paths) != {"left_wrist", "right_wrist", "scene"}:
        raise RuntimeError("recording manifest has no complete camera-role mapping")
    import carb.settings
    import omni.physx
    import omni.usd
    import omni.replicator.core as rep
    from pxr import Usd

    carb.settings.get_settings().set("/app/player/playSimulations", False)
    rep.orchestrator.set_capture_on_play(False)
    physics_steps = 0
    def on_physics_step(_: float) -> None:
        nonlocal physics_steps
        physics_steps += 1
    subscription = omni.physx.get_physx_interface().subscribe_physics_step_events(on_physics_step)
    prepared = Usd.Stage.Open(str(snapshot))
    if prepared is None:
        raise RuntimeError("recording stage snapshot cannot be opened")
    removed_runtime_roots = []
    for path in ("/Render", "/Replicator"):
        if prepared.GetPrimAtPath(path):
            prepared.RemovePrim(path)
            removed_runtime_roots.append(path)
    prepared_snapshot = report_path.parent / "replay_scene.usd"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    prepared.GetRootLayer().Export(str(prepared_snapshot))
    context = omni.usd.get_context()
    context.open_stage(str(prepared_snapshot))
    for _ in range(20):
        simulation_app.update()
    if context.get_stage() is None:
        raise RuntimeError("recording stage snapshot did not load")
    if physics_steps != 0:
        raise RuntimeError(f"snapshot load advanced physics: 0 -> {physics_steps}")
    replayer = EpisodeReplayer(str(recording), pose_backend="usd")
    rendered: list[dict[str, Any]] = []
    try:
        replayer.prepare_episode(episode_name)
        render_indices = {0, frames // 2, frames - 1}
        def materialize(frame: int) -> None:
            if render_cameras is not None and frame in render_indices:
                rendered.extend(_render_frame(camera_paths, render_cameras, frame))

        apply_replay_frames(replayer, frames, pump=lambda: None,
                            physics_steps=lambda: physics_steps, materialize=materialize)
    finally:
        replayer.close()
        subscription = None
    if physics_steps != 0:
        raise RuntimeError(f"replay advanced physics: 0 -> {physics_steps}")
    report = {
        "schema": "piper_x_isaac_vr_replay_report_v1",
        "recording": str(recording), "stage_snapshot": str(snapshot),
        "prepared_stage_snapshot": str(prepared_snapshot),
        "removed_runtime_roots": removed_runtime_roots,
        "episode": episode_name, "frames_applied": frames,
        "physics_steps_before": 0, "physics_steps_after": physics_steps,
        "native_action_replay": False, "tracks": list(manifest.tracks), "renders": rendered,
        "d0": {"observation_ids": observation_ids.tolist(), "action_valid_count": int(valid.sum())},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("REPLAY_RESULT_JSON=" + json.dumps(report, sort_keys=True), flush=True)
    return 0
