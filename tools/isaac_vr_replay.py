"""State-only NVIDIA Episode Recorder replay and optional RGB materialization."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
import json
import time
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


@contextmanager
def replay_camera_streams(camera_paths: dict[str, str]):
    """Keep one annotator binding per camera throughout the selected episode."""
    import omni.replicator.core as rep

    products = {role: rep.create.render_product(path, (640, 480), force_new=True)
                for role, path in camera_paths.items()}
    annotators = {role: rep.AnnotatorRegistry.get_annotator("rgb") for role in products}
    try:
        for role, annotator in annotators.items():
            annotator.attach(products[role])
        yield annotators
    finally:
        for annotator in annotators.values():
            annotator.detach()
        for product in products.values():
            product.destroy()


def _render_frame(camera_paths: dict[str, str], output_dir: Path, frame: int,
                  *, physics_steps: Any = lambda: 0, annotators: Any = None) -> list[dict[str, Any]]:
    """Materialize a stopped-timeline capture; never advance PhysX."""
    if annotators is None:
        with replay_camera_streams(camera_paths) as streams:
            return _render_frame(camera_paths, output_dir, frame,
                                 physics_steps=physics_steps, annotators=streams)
    import carb.eventdispatcher
    import omni.kit.app
    import omni.kit.async_engine
    import omni.replicator.core as rep
    from PIL import Image

    before = physics_steps()
    output_dir.mkdir(parents=True, exist_ok=True)
    capture_seen = False

    def on_capture(event):
        nonlocal capture_seen
        if event.get("capture_id") is not None:
            capture_seen = True

    capture_subscription = carb.eventdispatcher.get_eventdispatcher().observe_event(
        event_name="omni.replicator.core.orchestrator:orchestratorEvent",
        on_event=on_capture, observer_name="piper_x_replay_capture",
    )
    try:
        # Kit's main-thread future needs app updates, not a blocking result().
        import omni.kit.app
        task = omni.kit.async_engine.run_coroutine(rep.orchestrator.step_async(delta_time=0.0, pause_timeline=True, wait_for_render=True))
        deadline = time.monotonic() + 30.0
        while not task.done():
            if time.monotonic() >= deadline:
                task.cancel()
                raise TimeoutError("Replay camera render exceeded 30 seconds")
            omni.kit.app.get_app().update()
            time.sleep(0.001)
        task.result()  # Propagate coroutine errors before reading annotators.
        if not capture_seen:
            raise RuntimeError("Replicator completed without scheduling a capture")
        if physics_steps() != before:
            raise RuntimeError("Replay camera render advanced physics")
        # Fresh render products may publish their host buffers a few Kit updates
        # after the capture coroutine completes. Await all three without physics.
        while True:
            if physics_steps() != before:
                raise RuntimeError("Replay camera render advanced physics")
            images = {role: np.asarray(annotator.get_data()) for role, annotator in annotators.items()}
            if all(image.size for image in images.values()):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Replay camera annotators exceeded 30 seconds")
            omni.kit.app.get_app().update()
            time.sleep(0.001)
        rendered = []
        for role, image in images.items():
            if image.shape != (480, 640, 4) and image.shape != (480, 640, 3):
                raise RuntimeError(f"{role}: unexpected RGB shape {image.shape}")
            path = output_dir / f"frame_{frame:06d}_{role}.png"
            Image.fromarray(image[..., :3]).save(path)
            rendered.append({"role": role, "frame": frame, "path": str(path)})
        return rendered
    finally:
        capture_subscription.reset()



def validate_required_tracks(reader: Any, episode: str, frames: int,
                             tracks: list[dict[str, Any]], sidecar: dict[str, Any]) -> dict[str, Any]:
    """Use upstream schemas; require every declared state track and coherent lengths."""
    from isaacsim.replicator.episode_recorder.registry import rehydrate

    required = {"state/left_robot": "articulation", "state/right_robot": "articulation",
                "state/object_0": "rigid_body", "state/object_1": "rigid_body",
                **{f"state/camera/{role}": "camera" for role in ("left_wrist", "right_wrist", "scene")},
                "d0/transition": "piper_x_d0_transition_v1", "meta/time": "sim_time"}
    by_group = {track["group"]: track for track in tracks}
    if len(by_group) != len(tracks) or any(by_group.get(g, {}).get("type") != t for g, t in required.items()):
        raise RuntimeError("recording missing required tracks or has wrong track types")
    if sidecar.get("recordables") != tracks:
        raise RuntimeError("recordable manifest does not match HDF5 tracks")
    d0 = None
    for group, track in by_group.items():
        if track["type"] not in set(required.values()):
            raise RuntimeError(f"unsupported required track type: {track['type']}")
        paths = track.get("link_paths") if track["type"] == "articulation" else None
        if track["type"] == "articulation" and (not paths or len(paths) != len(set(paths))):
            raise RuntimeError(f"{group}: required articulation has no coherent link binding")
        if track["type"] in {"articulation", "rigid_body", "camera"} and not track.get("prim_path"):
            raise RuntimeError(f"{group}: missing required prim binding")
        schema = rehydrate(track).describe_channels()
        values = reader.read_group_all_frames(episode, group)
        if set(values) != set(schema):
            raise RuntimeError(f"{group}: required channels differ")
        for name, descriptor in schema.items():
            array = np.asarray(values[name])
            if array.shape != (frames, *descriptor.shape) or array.dtype != np.dtype(descriptor.dtype):
                raise RuntimeError(f"{group}/{name}: incoherent frame count, shape or type")
            if not np.isfinite(array).all():
                raise RuntimeError(f"{group}/{name}: NaN/Inf")
            if name in {"orientation", "orientations"} and not np.allclose(np.linalg.norm(array, axis=-1), 1, atol=1e-5, rtol=0):
                raise RuntimeError(f"{group}: invalid quaternion")
        if group == "d0/transition":
            d0 = values
    assert d0 is not None
    return d0


def validate_d0(d0: dict[str, Any], frames: int) -> tuple[Any, Any]:
    observation_ids = d0["observation_id"]
    if not np.array_equal(observation_ids, np.arange(frames, dtype=np.int64)):
        raise RuntimeError("D0 observation IDs are not exact control-boundary order")
    for flag in ("action_valid", "transition_completed", "tracking_valid", "saturation"):
        if not np.isin(d0[flag], [0, 1]).all():
            raise RuntimeError(f"D0 invalid boolean channel: {flag}")
    valid = d0["action_valid"].astype(bool)
    if (valid[0] or np.any(d0["transition_completed"] != valid)
            or np.any(d0["action_from_observation_id"][valid] != observation_ids[valid] - 1)
            or np.any(d0["action_to_observation_id"][valid] != observation_ids[valid])
            or np.any(d0["action_from_observation_id"][~valid] != -1)
            or np.any(d0["action_to_observation_id"][~valid] != -1)):
        raise RuntimeError("D0 action/state transition indexing is invalid")
    for name in ("reset_epoch", "session_epoch", "control_reference_epoch"):
        if np.any(d0[name] < 0) or np.any(d0[name] != d0[name][0]):
            raise RuntimeError(f"D0 {name} splice or missing epoch")
    physics = d0["observation_physics_step"]
    render = d0["observation_render_generation"]
    prior_physics = np.roll(physics, 1)
    prior_render = np.roll(render, 1)
    if (np.any(physics < 0) or np.any(np.diff(physics) <= 0)
            or np.any(render < 0) or np.any(np.diff(render) < 0)
            or np.any(physics[valid] - d0["action_source_physics_step"][valid] != 4)
            or np.any(d0["action_source_physics_step"][valid] != prior_physics[valid])
            or np.any(d0["action_source_render_generation"][valid] != prior_render[valid])):
        raise RuntimeError("D0 action has no exact four-step completed successor")
    for name in ("control_tick_id", "deviceio_update_epoch", "submitted_frame_id", "returned_frame_id"):
        if np.any(d0[name][valid] < 0) or np.any(np.diff(d0[name][valid]) <= 0):
            raise RuntimeError(f"D0 invalid or reused {name}")
    if (not d0["tracking_valid"][valid].all()
            or np.any(d0["submitted_frame_id"][valid] != d0["returned_frame_id"][valid])):
        raise RuntimeError("D0 action has no valid resolved XR input")
    return observation_ids, valid


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
    from isaacsim.replicator.episode_recorder import EpisodeReplayer, ReplayPolicy, SessionReader

    ensure_d0_recordable()
    sidecar_manifest = recording.parent / "manifest.json"
    if not sidecar_manifest.is_file():
        raise FileNotFoundError(f"recording manifest not found: {sidecar_manifest}")
    sidecar = json.loads(sidecar_manifest.read_text())
    expected_snapshot_hash = sidecar.get("stage_snapshot_sha256")
    if not expected_snapshot_hash or hashlib.sha256(snapshot.read_bytes()).hexdigest() != expected_snapshot_hash:
        raise RuntimeError("recording stage snapshot hash missing or does not match manifest")
    if "hdf5_sha256" in sidecar and hashlib.sha256(recording.read_bytes()).hexdigest() != sidecar["hdf5_sha256"]:
        raise RuntimeError("recording HDF5 hash does not match manifest")
    if sidecar.get("outcome") not in {"completed", "operator_stopped"}:
        raise RuntimeError("recording outcome is failed, aborted or missing; forensic recovery required")
    with SessionReader(str(recording)) as reader:
        episode_name = reader.normalize_episode(episode)
        if episode_name not in reader.list_episodes():
            raise RuntimeError("selected episode does not exist")
        frames = reader.num_frames(episode_name)
        if frames <= 0:
            raise RuntimeError("recording episode contains no frames")
        if reader.episode_attrs(episode_name).get("user_metadata", {}).get("outcome") not in {"completed", "operator_stopped"}:
            raise RuntimeError("selected episode outcome is failed, aborted or missing")
        manifest = reader.manifest()
        d0 = validate_required_tracks(reader, episode_name, frames, manifest.tracks, sidecar)
        observation_ids, valid = validate_d0(d0, frames)
    camera_paths = sidecar.get("camera_roles")
    if not isinstance(camera_paths, dict) or set(camera_paths) != {"left_wrist", "right_wrist", "scene"}:
        raise RuntimeError("recording manifest has no complete camera-role mapping")
    import carb.settings
    import omni.physx
    import omni.usd
    import omni.replicator.core as rep
    from pxr import Usd

    carb.settings.get_settings().set("/app/player/playSimulations", False)
    # Pinned Replicator drives explicit stopped-timeline captures only in its
    # async-rendering path; otherwise step_async logs scheduling failure but returns.
    carb.settings.get_settings().set("/exts/omni.replicator.core/Orchestrator/enabled", True)
    carb.settings.get_settings().set("/omni/replicator/asyncRendering", True)
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
    for track in manifest.tracks:
        paths = [track["prim_path"]] if "prim_path" in track else []
        paths += track.get("link_paths", [])
        if any(not context.get_stage().GetPrimAtPath(path) for path in paths):
            raise RuntimeError(f"required replay target missing: {track['group']}")
    for role, path in camera_paths.items():
        if path != next(t["prim_path"] for t in manifest.tracks if t["group"] == f"state/camera/{role}"):
            raise RuntimeError(f"camera role binding differs: {role}")
    replayer = EpisodeReplayer(str(recording), pose_backend="usd", policy=ReplayPolicy(strictness="strict"))
    rendered: list[dict[str, Any]] = []
    try:
        replayer.prepare_episode(episode_name)
        if {rec.group for rec in replayer.prepared_recordables} != {track["group"] for track in manifest.tracks}:
            raise RuntimeError("EpisodeReplayer did not bind every required track")
        render_indices = {0, frames // 2, frames - 1}
        def materialize(frame: int) -> None:
            if render_cameras is not None and frame in render_indices:
                rendered.extend(_render_frame(camera_paths, render_cameras, frame, physics_steps=lambda: physics_steps, annotators=streams))

        with replay_camera_streams(camera_paths) if render_cameras is not None else nullcontext(None) as streams:
            apply_replay_frames(replayer, frames, pump=lambda: None,
                                physics_steps=lambda: physics_steps, materialize=materialize)
    finally:
        replayer.close()
        del subscription
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
