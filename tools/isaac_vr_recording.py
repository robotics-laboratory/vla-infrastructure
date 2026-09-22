"""Explicit control-boundary writer for NVIDIA Episode Recorder HDF5 V2.

This deliberately owns neither an HDF5 layout nor replay: it only coordinates the
public ``Recordable`` and ``SessionStorage`` primitives supplied by Isaac Sim.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import numpy as np


def ensure_episode_recorder_enabled() -> None:
    """Enable the public recorder extension before importing its Python package."""
    import omni.kit.app

    omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate(
        "isaacsim.replicator.episode_recorder", True
    )


class ExplicitFrameSampler:
    """Append one complete public-Recordable frame at a caller-owned boundary."""

    def __init__(self, storage: Any, recordables: Sequence[Any], *, pose_backend: str | None = None) -> None:
        self.storage = storage
        self.recordables = tuple(recordables)
        self.pose_backend = pose_backend
        groups = [recordable.group for recordable in self.recordables]
        if not groups or len(groups) != len(set(groups)):
            raise ValueError("recordables must have non-empty unique groups")
        self._schemas = {recordable.group: recordable.describe_channels() for recordable in self.recordables}
        self.failed = False

    @property
    def schemas(self) -> dict[str, Any]:
        return dict(self._schemas)

    def sample_frame(self) -> None:
        """Sample and append every group, advancing exactly once on full success.

        SessionStorage has no public rollback for partial buffered appends.  A
        failure is therefore terminal: callers must end/close the episode rather
        than risk a misleading successor identity.
        """
        if self.failed:
            raise RuntimeError("recording is failed closed after an earlier sample error")
        try:
            if self.pose_backend is None:
                self._append_recordable_frames()
            else:
                from isaacsim.core.experimental.utils.backend import use_backend
                with use_backend(self.pose_backend):
                    self._append_recordable_frames()
        except Exception:
            self.failed = True
            raise
        self.storage.advance_episode_frame()

    def _append_recordable_frames(self) -> None:
        for recordable in self.recordables:
            frame = recordable.sample()
            self._validate(recordable.group, frame)
            self.storage.append_frame(recordable.group, frame)

    def _validate(self, group: str, frame: Mapping[str, Any]) -> None:
        schema = self._schemas[group]
        if set(frame) != set(schema):
            raise ValueError(f"{group}: channels {sorted(frame)} != declared {sorted(schema)}")
        for name, descriptor in schema.items():
            value = np.asarray(frame[name])
            if value.shape != tuple(descriptor.shape):
                raise ValueError(f"{group}/{name}: shape {value.shape} != {descriptor.shape}")
            if not np.can_cast(value.dtype, np.dtype(descriptor.dtype), casting="same_kind"):
                raise TypeError(f"{group}/{name}: dtype {value.dtype} is incompatible with {descriptor.dtype}")
            if np.issubdtype(value.dtype, np.floating) and not np.isfinite(value).all():
                raise ValueError(f"{group}/{name}: non-finite value")


def open_explicit_session(
    output_path: str,
    *,
    recordables: Sequence[Any],
    stage: Any,
    session_metadata: Mapping[str, Any],
    stage_snapshot: str | None,
    pose_backend: str | None = None,
) -> tuple[Any, ExplicitFrameSampler]:
    """Open NVIDIA V2 storage and invoke the public Recordable setup lifecycle."""
    from isaacsim.replicator.episode_recorder import SessionStorage, build_manifest

    storage = SessionStorage(output_path)
    storage.open()
    opened: list[Any] = []
    try:
        for recordable in recordables:
            recordable.on_session_open(stage)
            opened.append(recordable)
        for key, value in session_metadata.items():
            storage.set_root_attr(key, value)
        if stage_snapshot is not None:
            storage.set_root_attr("stage_snapshot", stage_snapshot)
        storage.write_manifest(
            build_manifest(
                [recordable.to_manifest() for recordable in recordables],
                sampling={"mode": "explicit_control_boundary", "decimation": 1, "pose_backend": pose_backend},
                session_metadata=dict(session_metadata),
            )
        )
        return storage, ExplicitFrameSampler(storage, recordables, pose_backend=pose_backend)
    except Exception:
        for recordable in reversed(opened):
            recordable.on_session_close()
        storage.close()
        raise


def start_explicit_episode(storage: Any, sampler: ExplicitFrameSampler, recordables: Sequence[Any], metadata: Mapping[str, Any]) -> int:
    """Begin an episode and prepare its public Recordables for caller-driven frames."""
    episode = storage.begin_episode(sampler.schemas, metadata=metadata)
    for recordable in recordables:
        recordable.on_episode_start()
    return episode


def close_explicit_session(storage: Any, recordables: Sequence[Any], *, metadata: Mapping[str, Any]) -> None:
    """Finalize once and release public Recordable handles in recorder lifecycle order."""
    try:
        for recordable in recordables:
            recordable.on_episode_end()
        storage.end_episode(success=None, metadata=metadata)
    finally:
        for recordable in reversed(recordables):
            recordable.on_session_close()
        storage.close()


class LiveRecording:
    """Small owner for one live V2 session; callers select every sample boundary."""

    def __init__(self, storage: Any, sampler: ExplicitFrameSampler, recordables: Sequence[Any], d0: Any,
                 *, output_dir: Path, hdf5_path: Path, snapshot: Path) -> None:
        self.storage, self.sampler, self.recordables, self.d0 = storage, sampler, tuple(recordables), d0
        self.output_dir, self.hdf5_path, self.snapshot = output_dir, hdf5_path, snapshot

    def sample(self, d0_sample: Mapping[str, Any]) -> None:
        self.d0.set_sample(d0_sample)
        self.sampler.sample_frame()

    def close(self, *, outcome: str) -> None:
        close_explicit_session(self.storage, self.recordables, metadata={"outcome": outcome})
        manifest_path = self.output_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["hdf5_sha256"] = hashlib.sha256(self.hdf5_path.read_bytes()).hexdigest()
        manifest["outcome"] = outcome
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        (self.output_dir / "result.json").write_text(
            json.dumps({"outcome": outcome, "hdf5": str(self.hdf5_path), "stage_snapshot": str(self.snapshot)},
                       indent=2, sort_keys=True) + "\n"
        )


def start_live_recording(output_dir: Path, env: Any, *, session_metadata: Mapping[str, Any]) -> LiveRecording:
    """Configure upstream state tracks for the canonical VR scene, then sample O0."""
    ensure_episode_recorder_enabled()
    from isaacsim.replicator.episode_recorder import (
        ArticulationRecordable, CameraRecordable, RigidBodyRecordable, SimTimeRecordable,
        export_stage_snapshot,
    )
    import omni.usd

    output_dir.mkdir(parents=True, exist_ok=False)
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("recording requires a loaded USD stage")
    snapshot = Path(export_stage_snapshot(str(output_dir)))
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    sidecar_path = output_dir / "stage_snapshot.sidecar.json"
    sidecar = json.loads(sidecar_path.read_text()) if sidecar_path.is_file() else {}
    sidecar["sha256"] = snapshot_hash
    sidecar_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
    D0 = ensure_d0_recordable()
    cameras = {
        "left_wrist": env.camera.wrists[0],
        "right_wrist": env.camera.wrists[1],
        "scene": env.camera.scene_camera,
    }
    recordables: list[Any] = [
        SimTimeRecordable(),
        ArticulationRecordable(group="state/left_robot", prim_path="/World/LeftPiper"),
        ArticulationRecordable(group="state/right_robot", prim_path="/World/RightPiper"),
        *(
            RigidBodyRecordable(group=f"state/object_{index}", prim_path=asset.cfg.prim_path)
            for index, asset in enumerate(env.vr_runtime.dynamic_assets)
        ),
        *(
            CameraRecordable(group=f"state/camera/{role}", prim_path=camera._view.prim_paths[0], resolution=(640, 480))
            for role, camera in cameras.items()
        ),
    ]
    d0 = D0()
    recordables.append(d0)
    path = output_dir / "session.hdf5"
    storage, sampler = open_explicit_session(
        str(path), recordables=recordables, stage=stage, session_metadata=session_metadata,
        stage_snapshot=snapshot.name, pose_backend="fabric",
    )
    start_explicit_episode(storage, sampler, recordables, {"outcome": "unclassified"})
    repository = Path(__file__).resolve().parents[1]
    (output_dir / "manifest.json").write_text(json.dumps({
        "schema": "piper_x_isaac_vr_recording_manifest_v1",
        "git_commit": subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip(),
        "dirty_status": subprocess.check_output(["git", "-C", str(repository), "status", "--porcelain=v1"], text=True),
        "session_metadata": dict(session_metadata), "stage_snapshot": snapshot.name,
        "stage_snapshot_sha256": snapshot_hash,
        "camera_roles": {role: camera._view.prim_paths[0] for role, camera in cameras.items()},
        "recordables": [recordable.to_manifest() for recordable in recordables],
    }, indent=2, sort_keys=True) + "\n")
    return LiveRecording(storage, sampler, recordables, d0, output_dir=output_dir, hdf5_path=path, snapshot=snapshot)


def ensure_d0_recordable() -> type[Any]:
    """Register the provenance-only V2 track when running inside Isaac Sim.

    Delayed definition keeps core-only tests independent of Kit while ensuring the
    class is registered before ``EpisodeReplayer.prepare_episode`` rehydrates it.
    """
    from isaacsim.replicator.episode_recorder import ChannelDescriptor, Recordable, register_recordable

    @register_recordable
    class D0TransitionRecordable(Recordable):
        TYPE_ID = "piper_x_d0_transition_v1"

        def __init__(self, *, group: str = "d0/transition", sample: Mapping[str, Any] | None = None) -> None:
            super().__init__(group=group)
            self._sample = dict(sample or _empty_d0_sample())

        def set_sample(self, sample: Mapping[str, Any]) -> None:
            self._sample = dict(sample)

        def describe_channels(self) -> dict[str, Any]:
            return _d0_channels(ChannelDescriptor)

        def sample(self) -> dict[str, Any]:
            return dict(self._sample)

        def apply(self, frame: Mapping[str, np.ndarray], *, policy: Any) -> None:
            return  # provenance only; world state is replayed by NVIDIA tracks

        def to_manifest(self) -> dict[str, Any]:
            return {"type": self.TYPE_ID, "group": self.group}

        @classmethod
        def from_manifest(cls, entry: Mapping[str, Any]) -> Any:
            return cls(group=str(entry["group"]))

    return D0TransitionRecordable


def _d0_channels(ChannelDescriptor: Any) -> dict[str, Any]:
    def scalar_i() -> Any:
        return ChannelDescriptor(shape=(), dtype="i8")

    return {
        "observation_id": scalar_i(), "action_valid": ChannelDescriptor(shape=(), dtype="u1"),
        "action_from_observation_id": scalar_i(), "action_to_observation_id": scalar_i(),
        "control_tick_id": scalar_i(), "reset_epoch": scalar_i(),
        "observation_physics_step": scalar_i(), "observation_render_generation": scalar_i(),
        "action_source_physics_step": scalar_i(), "action_source_render_generation": scalar_i(),
        "control_reference_epoch": scalar_i(),
        "session_epoch": scalar_i(), "observation_state": ChannelDescriptor(shape=(14,), dtype="f4"),
        "dataset_action": ChannelDescriptor(shape=(14,), dtype="f4"),
        "native_preclip": ChannelDescriptor(shape=(14,), dtype="f4"),
        "native_clipped": ChannelDescriptor(shape=(14,), dtype="f4"),
        "native_residual": ChannelDescriptor(shape=(14,), dtype="f4"),
        "saturation": ChannelDescriptor(shape=(14,), dtype="u1"),
        "deviceio_update_epoch": scalar_i(), "submitted_frame_id": scalar_i(), "returned_frame_id": scalar_i(),
        "tracking_valid": ChannelDescriptor(shape=(2,), dtype="u1"), "transition_completed": ChannelDescriptor(shape=(), dtype="u1"),
    }


def _empty_d0_sample() -> dict[str, Any]:
    vector_f32 = {"observation_state", "dataset_action", "native_preclip", "native_clipped", "native_residual"}
    return {
        name: (
            np.zeros((14,), np.float32) if name in vector_f32 else
            np.zeros((14,), np.uint8) if name == "saturation" else
            np.zeros((2,), np.uint8) if name == "tracking_valid" else
            np.uint8(0) if name in {"action_valid", "transition_completed"} else np.int64(-1)
        )
        for name in _d0_channels(_Descriptor)
    }


class _Descriptor:
    def __init__(self, **_: Any) -> None: pass
