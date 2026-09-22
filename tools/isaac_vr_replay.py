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


def replay(env: Any, simulation_app: Any, *, recording: Path, episode: int,
           render_cameras: Path | None, report_path: Path) -> int:
    """Apply recorded state in order.  This function deliberately never calls PhysX."""
    from isaacsim.replicator.episode_recorder import EpisodeReplayer, SessionReader
    from isaac_vr_recording import ensure_d0_recordable

    if not recording.is_file():
        raise FileNotFoundError(f"recording HDF5 not found: {recording}")
    snapshot = recording.parent / "stage_snapshot.usd"
    if not snapshot.is_file():
        raise FileNotFoundError(f"recording stage snapshot not found: {snapshot}")
    ensure_d0_recordable()
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
        required = {"state/left_robot", "state/right_robot", "d0/transition"}
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
        if any(not np.isfinite(values).all() for values in d0.values() if np.issubdtype(values.dtype, np.floating)):
            raise RuntimeError("D0 contains NaN/Inf")
    physics_before = env.sim.get_physics_step_count()
    camera_paths = ({
        "left_wrist": env.camera.wrists[0]._view.prim_paths[0],
        "right_wrist": env.camera.wrists[1]._view.prim_paths[0],
        "scene": env.camera.scene_camera._view.prim_paths[0],
    } if render_cameras is not None else {})
    replayer = EpisodeReplayer(str(recording), pose_backend="usd")
    rendered: list[dict[str, Any]] = []
    try:
        replayer.prepare_episode(episode_name)
        render_indices = {0, frames // 2, frames - 1}
        def materialize(frame: int) -> None:
            if render_cameras is not None and frame in render_indices:
                rendered.extend(_render_frame(camera_paths, render_cameras, frame))

        # A Kit update renders USD edits only; the guard makes any accidental
        # timeline/physics progression a hard replay failure.
        apply_replay_frames(replayer, frames, pump=simulation_app.update,
                            physics_steps=env.sim.get_physics_step_count, materialize=materialize)
    finally:
        replayer.close()
    physics_after = env.sim.get_physics_step_count()
    if physics_after != physics_before:
        raise RuntimeError(f"replay advanced physics: {physics_before} -> {physics_after}")
    report = {
        "schema": "piper_x_isaac_vr_replay_report_v1",
        "recording": str(recording), "stage_snapshot": str(snapshot),
        "episode": episode_name, "frames_applied": frames,
        "physics_steps_before": physics_before, "physics_steps_after": physics_after,
        "native_action_replay": False, "tracks": list(manifest.tracks), "renders": rendered,
        "d0": {"observation_ids": observation_ids.tolist(), "action_valid_count": int(valid.sum())},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("REPLAY_RESULT_JSON=" + json.dumps(report, sort_keys=True), flush=True)
    return 0
