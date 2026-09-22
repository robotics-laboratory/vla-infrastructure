"""Committed control-boundary writer for NVIDIA Episode Recorder HDF5 V2.

Upstream ``SessionStorage`` and ``Recordable`` implementations continue to own
the file layout and simulator state bindings.  This module adds only the
project's fail-closed transaction boundary::

    capture O_t -> complete/commit transition -> append (O_t, A_t, O_t+1)

Sampling and persistence are deliberately separate.  A rejected control tick
discards its buffered observation without ever becoming an HDF5 frame.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from typing import Any, ContextManager
import zipfile

import numpy as np


POSE_BACKEND = "fabric"
TRANSITION_SCHEMA = "piper_x_committed_transition_v2"
REQUIRED_SESSION_METADATA = ("run_id", "session_id", "episode_id", "source_profile")
FINAL_OUTCOMES = {"success", "operator_stopped", "aborted", "failure"}
_ID_BYTES = 256
_HASH_BYTES = 32
TERMINAL_SUCCESSOR_SCHEMA = "piper_x_terminal_successor_v1"
TERMINAL_SUCCESSOR_FILENAME = "terminal_successor.npz"


def _fabric_backend_context() -> ContextManager[None]:
    """Enter the public Fabric pose backend, failing instead of demoting to USD."""
    import carb.settings

    if not carb.settings.get_settings().get_as_bool("/app/useFabricSceneDelegate"):
        raise RuntimeError(
            "recording requires Fabric Scene Delegate at every observation capture; "
            "refusing silent USD pose-backend demotion"
        )
    from isaacsim.core.experimental.utils.backend import use_backend

    return use_backend(POSE_BACKEND)


class ExplicitFrameSampler:
    """Capture a complete upstream frame, then append it exactly once after commit."""

    def __init__(
        self,
        storage: Any,
        recordables: Sequence[Any],
        *,
        deferred_groups: Sequence[str] = (),
        pose_backend: str = POSE_BACKEND,
        backend_context_factory: Callable[[], ContextManager[None]] | None = None,
        pose_batch_factory: Callable[[Sequence[str]], Any] | None = None,
    ) -> None:
        self.storage = storage
        self.recordables = tuple(recordables)
        groups = [recordable.group for recordable in self.recordables]
        if not groups or len(groups) != len(set(groups)):
            raise ValueError("recordables must have non-empty unique groups")
        unknown_deferred = set(deferred_groups).difference(groups)
        if unknown_deferred:
            raise ValueError(f"unknown deferred recordable groups: {sorted(unknown_deferred)}")
        if pose_backend != POSE_BACKEND:
            raise ValueError(f"recording pose backend must be {POSE_BACKEND!r}, got {pose_backend!r}")
        self.pose_backend = pose_backend
        self._backend_context_factory = backend_context_factory or _fabric_backend_context
        self._deferred_groups = frozenset(deferred_groups)
        self._schemas = {
            recordable.group: recordable.describe_channels() for recordable in self.recordables
        }
        self._pose_batch, self._pose_slots = self._build_pose_batch(pose_batch_factory)
        self.failed = False

    @property
    def schemas(self) -> dict[str, Any]:
        return dict(self._schemas)

    @property
    def deferred_groups(self) -> frozenset[str]:
        return self._deferred_groups

    def capture_frame(self) -> dict[str, dict[str, Any]]:
        """Sample non-deferred groups under Fabric without touching storage."""
        if self.failed:
            raise RuntimeError("recording is failed closed after an earlier sample error")
        frames: dict[str, dict[str, Any]] = {}
        try:
            with self._backend_context_factory():
                positions: np.ndarray | None = None
                orientations: np.ndarray | None = None
                if self._pose_batch is not None:
                    raw_positions, raw_orientations = self._pose_batch.get_world_poses()
                    positions = _to_numpy_f32(raw_positions)
                    orientations = _to_numpy_f32(raw_orientations)
                for recordable in self.recordables:
                    if recordable.group in self._deferred_groups:
                        continue
                    slot = self._pose_slots.get(id(recordable))
                    if slot is None:
                        frame = recordable.sample()
                    else:
                        if positions is None or orientations is None:
                            raise RuntimeError("pose-batch participant has no shared Fabric sample")
                        start, end = slot
                        frame = recordable.consume_pose_batch(
                            positions[start:end], orientations[start:end]
                        )
                    self._validate(recordable.group, frame)
                    # Recordables may return views into mutable simulator buffers.
                    frames[recordable.group] = {
                        name: np.asarray(value).copy() for name, value in frame.items()
                    }
        except Exception:
            self.failed = True
            raise
        return frames

    def _build_pose_batch(
        self, factory: Callable[[Sequence[str]], Any] | None
    ) -> tuple[Any | None, dict[int, tuple[int, int]]]:
        participants: list[tuple[Any, list[str]]] = []
        paths: list[str] = []
        for recordable in self.recordables:
            if recordable.group in self._deferred_groups:
                continue
            pose_paths = getattr(recordable, "pose_paths", None)
            selected = list(pose_paths() or ()) if pose_paths is not None else []
            if selected:
                participants.append((recordable, selected))
                paths.extend(selected)
        if not paths:
            return None, {}
        if factory is None:
            from isaacsim.core.experimental.prims import XformPrim

            factory = XformPrim
        # Construction failure is fatal: per-recordable ArticulationRecordable
        # sampling can swallow pose-read errors and return zero-filled state.
        batch = factory(paths)
        slots: dict[int, tuple[int, int]] = {}
        cursor = 0
        for recordable, selected in participants:
            end = cursor + len(selected)
            slots[id(recordable)] = (cursor, end)
            cursor = end
        return batch, slots

    def append_captured_frame(self, frames: Mapping[str, Mapping[str, Any]]) -> None:
        """Append one already captured, now committed, complete frame."""
        if self.failed:
            raise RuntimeError("recording is failed closed after an earlier sample error")
        expected = set(self._schemas)
        if set(frames) != expected:
            raise ValueError(
                f"captured groups {sorted(frames)} != declared groups {sorted(expected)}"
            )
        try:
            for recordable in self.recordables:
                frame = frames[recordable.group]
                self._validate(recordable.group, frame)
                self.storage.append_frame(recordable.group, frame)
        except Exception:
            # SessionStorage has no public rollback for partially appended buffers.
            self.failed = True
            raise
        self.storage.advance_episode_frame()

    def sample_frame(self) -> None:
        """Compatibility helper for schemas without deferred transaction groups."""
        if self._deferred_groups:
            raise RuntimeError("deferred transaction groups require append_captured_frame()")
        self.append_captured_frame(self.capture_frame())

    def _validate(self, group: str, frame: Mapping[str, Any]) -> None:
        schema = self._schemas[group]
        if set(frame) != set(schema):
            raise ValueError(f"{group}: channels {sorted(frame)} != declared {sorted(schema)}")
        for name, descriptor in schema.items():
            value = np.asarray(frame[name])
            if value.shape != tuple(descriptor.shape):
                raise ValueError(f"{group}/{name}: shape {value.shape} != {descriptor.shape}")
            if not np.can_cast(value.dtype, np.dtype(descriptor.dtype), casting="same_kind"):
                raise TypeError(
                    f"{group}/{name}: dtype {value.dtype} is incompatible with {descriptor.dtype}"
                )
            if np.issubdtype(value.dtype, np.floating) and not np.isfinite(value).all():
                raise ValueError(f"{group}/{name}: non-finite value")


def open_explicit_session(
    output_path: str,
    *,
    recordables: Sequence[Any],
    stage: Any,
    session_metadata: Mapping[str, Any],
    stage_snapshot: str | None,
    deferred_groups: Sequence[str] = (),
    backend_context_factory: Callable[[], ContextManager[None]] | None = None,
    pose_batch_factory: Callable[[Sequence[str]], Any] | None = None,
) -> tuple[Any, ExplicitFrameSampler]:
    """Open NVIDIA V2 storage and invoke the public Recordable lifecycle."""
    from isaacsim.replicator.episode_recorder import SessionStorage, build_manifest

    _validate_session_metadata(session_metadata)
    storage = SessionStorage(output_path)
    storage.open()
    opened: list[Any] = []
    try:
        for recordable in recordables:
            recordable.on_session_open(stage)
            opened.append(recordable)
        for key, value in session_metadata.items():
            storage.set_root_attr(key, value)
        storage.set_root_attr("transition_schema", TRANSITION_SCHEMA)
        storage.set_root_attr("pose_backend_requested", POSE_BACKEND)
        storage.set_root_attr("pose_backend_effective", POSE_BACKEND)
        storage.set_root_attr("dataset_admissible", False)
        if stage_snapshot is not None:
            storage.set_root_attr("stage_snapshot", stage_snapshot)
        storage.write_manifest(
            build_manifest(
                [recordable.to_manifest() for recordable in recordables],
                sampling={
                    "mode": "explicit_committed_control_boundary",
                    "decimation": 1,
                    "pose_backend": POSE_BACKEND,
                },
                session_metadata=dict(session_metadata),
            )
        )
        return storage, ExplicitFrameSampler(
            storage,
            recordables,
            deferred_groups=deferred_groups,
            backend_context_factory=backend_context_factory,
            pose_batch_factory=pose_batch_factory,
        )
    except Exception as exc:
        cleanup_errors: list[Exception] = []
        for recordable in reversed(opened):
            try:
                recordable.on_session_close()
            except Exception as cleanup_exc:
                cleanup_errors.append(cleanup_exc)
        try:
            storage.close()
        except Exception as cleanup_exc:
            cleanup_errors.append(cleanup_exc)
        for rollback_error in cleanup_errors:
            exc.add_note(f"session-open rollback also failed: {rollback_error!r}")
        raise


def start_explicit_episode(
    storage: Any,
    sampler: ExplicitFrameSampler,
    recordables: Sequence[Any],
    metadata: Mapping[str, Any],
) -> int:
    """Begin an episode and prepare public Recordables for caller-driven frames."""
    episode = storage.begin_episode(sampler.schemas, metadata=metadata)
    for recordable in recordables:
        recordable.on_episode_start()
    return episode


def close_explicit_session(
    storage: Any,
    recordables: Sequence[Any],
    *,
    success: bool | None,
    metadata: Mapping[str, Any],
) -> None:
    """Finalize once and release public Recordable handles in lifecycle order."""
    errors: list[Exception] = []
    for recordable in recordables:
        try:
            recordable.on_episode_end()
        except Exception as exc:
            errors.append(exc)
    try:
        storage.end_episode(success=success, metadata=metadata)
    except Exception as exc:
        errors.append(exc)
    for recordable in reversed(recordables):
        try:
            recordable.on_session_close()
        except Exception as exc:
            errors.append(exc)
    try:
        storage.close()
    except Exception as exc:
        errors.append(exc)
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise ExceptionGroup("recording lifecycle finalization failed", errors)


@dataclass(frozen=True)
class RecordedObservationToken:
    """Single-use handle binding upstream state tracks to the exact native O_t."""

    token_id: int
    observation: Any
    state: tuple[float, ...]
    physics_step: int
    capture_sequence: int
    reset_epoch: int
    state_generation: int
    scene_state_snapshot_id: str
    scene_state_snapshot_sha256: str


@dataclass(frozen=True)
class TerminalSuccessorSnapshot:
    """Verified full Recordable bundle for the final committed O_(t+1)."""

    token: RecordedObservationToken
    frames: dict[str, dict[str, np.ndarray]]
    artifact_sha256: str


class LiveRecording:
    """Owner of one live V2 session and one pending pre-action observation."""

    def __init__(
        self,
        storage: Any,
        sampler: ExplicitFrameSampler,
        recordables: Sequence[Any],
        d0: Any,
        *,
        output_dir: Path,
        hdf5_path: Path,
        snapshot: Path,
        identity: Mapping[str, str],
        observation_factory: Callable[[], Any],
        flush_every_frames: int = 64,
    ) -> None:
        if flush_every_frames < 1:
            raise ValueError("flush_every_frames must be positive")
        self.storage, self.sampler = storage, sampler
        self.recordables, self.d0 = tuple(recordables), d0
        self.output_dir, self.hdf5_path, self.snapshot = output_dir, hdf5_path, snapshot
        self.run_id = identity["run_id"]
        self.session_id = identity["session_id"]
        self.episode_id = identity["episode_id"]
        self.source_profile = identity["source_profile"]
        self.flush_every_frames = flush_every_frames
        self.committed_frames = 0
        self.discarded_observations = 0
        self.rejections: Counter[str] = Counter()
        self._observation_factory = observation_factory
        self._pending: tuple[RecordedObservationToken, dict[str, dict[str, Any]]] | None = None
        self._successor: tuple[RecordedObservationToken, dict[str, dict[str, Any]]] | None = None
        self._promoted: tuple[RecordedObservationToken, dict[str, dict[str, Any]]] | None = None
        self._terminal_successor: (
            tuple[RecordedObservationToken, dict[str, dict[str, Any]], dict[str, Any]] | None
        ) = None
        self._next_capture_sequence = 0
        self._closed = False
        self._failure_reason: str | None = None

    def capture_observation(self) -> RecordedObservationToken:
        """Buffer upstream Recordables and the exact native O_t at one fixed boundary."""
        self._require_open()
        if self._pending is not None:
            raise RuntimeError("a prior observation capture is still pending")
        if self._successor is not None:
            raise RuntimeError("a successor capture is awaiting transition commit")
        if self._promoted is not None:
            self._pending, self._promoted = self._promoted, None
            return self._pending[0]
        self._pending = self._capture_new_observation()
        return self._pending[0]

    def capture_successor(
        self, token: RecordedObservationToken
    ) -> RecordedObservationToken:
        """Capture full post-action O_(t+1) once, before causal completion/commit."""
        self._require_open()
        self._require_pending_token(token)
        if self._successor is not None:
            raise RuntimeError("a successor observation is already captured")
        successor = self._capture_new_observation()
        if successor[0].physics_step <= token.physics_step:
            self._failure_reason = "successor_capture_failed:physics_did_not_advance"
            raise ValueError("successor physics step must be after O_t")
        self._successor = successor
        return successor[0]

    def _capture_new_observation(
        self,
    ) -> tuple[RecordedObservationToken, dict[str, dict[str, Any]]]:
        try:
            # Both reads happen on the serialized simulation thread without an
            # intervening app/physics pump.  The factory's own boundary checks
            # reject a changed physics/state generation.
            observation = self._observation_factory()
            frames = self.sampler.capture_frame()
            snapshot_sha256 = _captured_frame_sha256(frames)
            snapshot_id = (
                f"{self.run_id}:{self.episode_id}:scene_state:{self._next_capture_sequence}"
            )
            bind_snapshot = getattr(observation, "bind_recording_snapshot", None)
            if bind_snapshot is not None:
                observation = bind_snapshot(
                    capture_sequence=self._next_capture_sequence,
                    snapshot_id=snapshot_id,
                    snapshot_sha256=snapshot_sha256,
                )
            token = RecordedObservationToken(
                token_id=self._next_capture_sequence,
                observation=observation,
                state=tuple(float(value) for value in observation.state),
                physics_step=int(observation.physics_step),
                capture_sequence=self._next_capture_sequence,
                reset_epoch=int(observation.reset_epoch),
                state_generation=int(observation.state_generation),
                scene_state_snapshot_id=snapshot_id,
                scene_state_snapshot_sha256=snapshot_sha256,
            )
        except Exception as exc:
            self._failure_reason = f"observation_capture_failed:{type(exc).__name__}:{exc}"
            raise
        if len(token.state) != 14 or not np.isfinite(token.state).all():
            self._failure_reason = "observation_capture_failed:invalid_native_state"
            raise ValueError("recorded observation state must be finite float[14]")
        self._next_capture_sequence += 1
        return token, frames

    def commit_transition(
        self,
        token: RecordedObservationToken,
        successor_token: RecordedObservationToken,
        sample: Mapping[str, Any],
    ) -> None:
        """Persist buffered O_t only after its causal transaction was committed."""
        self._require_open()
        pending = self._take_pending(token)
        successor = self._take_successor(successor_token)
        try:
            canonical = canonical_committed_transition(sample)
            verify_committed_transition_sample(canonical)
            self._validate_identity_and_index(token, successor_token, canonical)
            frames = dict(pending)
            frames[self.d0.group] = canonical
            self.sampler.append_captured_frame(frames)
            self.committed_frames += 1
            # Retain the most recent full successor independently of the
            # double buffer.  A later rejected tick may consume/discard the
            # promoted buffer, but it must not erase the last committed O_(t+1).
            self._terminal_successor = (successor_token, successor, canonical)
            # Exact O_(t+1) becomes the next O_t without sampling it again.
            self._promoted = (successor_token, successor)
            if self.committed_frames % self.flush_every_frames == 0:
                self.storage.flush()
        except Exception as exc:
            self._failure_reason = f"transition_commit_failed:{type(exc).__name__}:{exc}"
            raise

    def discard_observation(self, token: RecordedObservationToken, *, reason: str) -> None:
        """Discard an inadmissible tick without appending any HDF5 row."""
        self._require_open()
        if not reason or not reason.strip():
            raise ValueError("discard reason must be non-empty")
        self._take_pending(token)
        self._successor = None
        self.discarded_observations += 1
        self.rejections[reason.strip()] += 1

    def sample(self, d0_sample: Mapping[str, Any]) -> None:
        """Reject the old post-transition API so shifted rows cannot reappear."""
        raise RuntimeError(
            "LiveRecording.sample() is unsafe and removed; use capture_observation() "
            "before native actuation and commit_transition() after causal commit"
        )

    def close(self, *, outcome: str, reason: str | None = None) -> None:
        """Finalize metadata atomically; failures can never produce a finalized marker."""
        self._require_open()
        if outcome not in FINAL_OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(FINAL_OUTCOMES)}, got {outcome!r}")
        if self._pending is not None:
            self.discarded_observations += 1
            self.rejections["episode_closed_with_pending_observation"] += 1
            self._pending = None
        # A successor promoted by the last committed terminal row is expected;
        # it is not an invalid action attempt and does not increment rejection QA.
        self._promoted = None
        self._successor = None
        effective_reason: str | None
        if self._failure_reason is not None:
            effective_outcome = "failure"
            effective_reason = self._failure_reason
        elif self.committed_frames == 0 and outcome in {"success", "operator_stopped"}:
            effective_outcome = "aborted"
            effective_reason = reason or "zero_committed_transitions"
        else:
            effective_outcome = outcome
            effective_reason = reason
        success = True if effective_outcome == "success" else False
        try:
            close_explicit_session(
                self.storage,
                self.recordables,
                success=success,
                metadata={
                    "outcome": effective_outcome,
                    "reason": effective_reason,
                    "committed_frames": self.committed_frames,
                    "discarded_observations": self.discarded_observations,
                    "rejections": dict(self.rejections),
                },
            )
            terminal_successor: dict[str, Any] | None = None
            if self.committed_frames:
                if self._terminal_successor is None:
                    raise RuntimeError("committed recording lacks its terminal successor buffer")
                successor_token, successor_frames, last_transition = self._terminal_successor
                terminal_path = self.output_dir / TERMINAL_SUCCESSOR_FILENAME
                terminal_successor = write_terminal_successor_snapshot(
                    terminal_path,
                    successor_token,
                    successor_frames,
                )
                # Read the just-written artifact through the same strict path
                # used by replay before advertising it in the final manifest.
                verify_terminal_successor_snapshot(
                    terminal_path,
                    expected_artifact_sha256=terminal_successor["sha256"],
                    committed_transition=last_transition,
                )
            hdf5_hash = sha256_file(self.hdf5_path)
            manifest_path = self.output_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest.update(
                {
                    "artifact_state": (
                        "finalized" if effective_outcome in {"success", "operator_stopped"} else "failed"
                    ),
                    "committed_frames": self.committed_frames,
                    "discarded_observations": self.discarded_observations,
                    "hdf5_sha256": hdf5_hash,
                    "outcome": effective_outcome,
                    "reason": effective_reason,
                    "rejections": dict(sorted(self.rejections.items())),
                    "terminal_successor": terminal_successor,
                }
            )
            _atomic_write_json(manifest_path, manifest)
            state = {
                "artifact_state": manifest["artifact_state"],
                "committed_frames": self.committed_frames,
                "discarded_observations": self.discarded_observations,
                "hdf5": str(self.hdf5_path),
                "hdf5_sha256": hdf5_hash,
                "outcome": effective_outcome,
                "reason": effective_reason,
                "stage_snapshot": str(self.snapshot),
                "terminal_successor": terminal_successor,
            }
            _atomic_write_json(self.output_dir / "result.json", state)
            # This marker is deliberately written last.
            _atomic_write_json(self.output_dir / "recording_state.json", state)
        except Exception as exc:
            _atomic_write_json(
                self.output_dir / "recording_state.json",
                {
                    "artifact_state": "failed",
                    "committed_frames": self.committed_frames,
                    "outcome": "failure",
                    "reason": f"finalization_failed:{type(exc).__name__}:{exc}",
                },
            )
            self._closed = True
            raise
        self._closed = True

    def _take_pending(
        self, token: RecordedObservationToken
    ) -> dict[str, dict[str, Any]]:
        if self._pending is None:
            raise RuntimeError("no pending observation capture")
        expected, frames = self._pending
        if token is not expected:
            raise ValueError(
                f"capture token mismatch: expected {expected.token_id}, got {token.token_id}"
            )
        self._pending = None
        return frames

    def _require_pending_token(self, token: RecordedObservationToken) -> None:
        if self._pending is None:
            raise RuntimeError("no pending observation capture")
        expected, _ = self._pending
        if token is not expected:
            raise ValueError(
                f"capture token mismatch: expected {expected.token_id}, got {token.token_id}"
            )

    def _take_successor(
        self, token: RecordedObservationToken
    ) -> dict[str, dict[str, Any]]:
        if self._successor is None:
            raise RuntimeError("no successor observation capture")
        expected, frames = self._successor
        if token is not expected:
            raise ValueError(
                f"successor token mismatch: expected {expected.token_id}, got {token.token_id}"
            )
        self._successor = None
        return frames

    def _validate_identity_and_index(
        self,
        token: RecordedObservationToken,
        successor_token: RecordedObservationToken,
        sample: Mapping[str, Any],
    ) -> None:
        for key in ("run_id", "session_id", "episode_id"):
            actual = _decode_fixed_id(sample[key])
            if actual != getattr(self, key):
                raise ValueError(f"{key} {actual!r} != active recording {getattr(self, key)!r}")
        if _decode_fixed_id(sample["source_id"]) != "simulation.scene_state_snapshot":
            raise ValueError("recorded source_id must be simulation.scene_state_snapshot")
        frame_index = int(np.asarray(sample["frame_index"]))
        if frame_index != self.committed_frames:
            raise ValueError(
                f"frame_index {frame_index} != next committed frame {self.committed_frames}"
            )
        if not np.array_equal(
            np.asarray(sample["observation_state"], dtype=np.float32),
            np.asarray(token.state, dtype=np.float32),
        ):
            raise ValueError("committed O_t state differs from buffered native observation")
        if int(sample["observation_physics_step"]) != token.physics_step:
            raise ValueError("committed O_t physics step differs from buffered observation")
        if int(sample["observation_capture_sequence"]) != token.capture_sequence:
            raise ValueError("committed O_t sequence differs from buffered observation")
        if int(sample["simulation_state_generation"]) != token.state_generation:
            raise ValueError("committed O_t state generation differs from buffered observation")
        if _decode_fixed_id(sample["scene_state_snapshot_id"]) != token.scene_state_snapshot_id:
            raise ValueError("committed scene snapshot identity differs from buffered observation")
        if bytes(sample["scene_state_snapshot_sha256"]).hex() != token.scene_state_snapshot_sha256:
            raise ValueError("committed scene snapshot digest differs from buffered observation")
        if _decode_fixed_id(sample["next_scene_state_snapshot_id"]) != successor_token.scene_state_snapshot_id:
            raise ValueError("committed successor snapshot identity differs from buffered successor")
        if bytes(sample["next_scene_state_snapshot_sha256"]).hex() != successor_token.scene_state_snapshot_sha256:
            raise ValueError("committed successor snapshot digest differs from buffered successor")
        if not np.array_equal(
            np.asarray(sample["successor_observation_state"], dtype=np.float32),
            np.asarray(successor_token.state, dtype=np.float32),
        ):
            raise ValueError("committed successor state differs from buffered successor")
        if int(sample["successor_physics_step"]) != successor_token.physics_step:
            raise ValueError("committed successor physics step differs from buffered successor")
        if int(sample["successor_capture_sequence"]) != successor_token.capture_sequence:
            raise ValueError("committed successor sequence differs from buffered successor")
        if int(sample["successor_state_generation"]) != successor_token.state_generation:
            raise ValueError("committed successor state generation differs from buffered successor")
        if int(sample["reset_epoch"]) != token.reset_epoch:
            raise ValueError("committed reset epoch differs from buffered observation")

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("recording is already closed")


def start_live_recording(
    output_dir: Path,
    env: Any,
    *,
    session_metadata: Mapping[str, Any],
    portable_roots: Mapping[str, str | os.PathLike[str]],
    min_free_bytes: int = 1 << 30,
    flush_every_frames: int = 64,
) -> LiveRecording:
    """Configure upstream state tracks for committed snapshot-backed transitions."""
    from isaacsim.replicator.episode_recorder import (
        ArticulationRecordable,
        CameraRecordable,
        RigidBodyRecordable,
        SimTimeRecordable,
        export_stage_snapshot,
    )
    import omni.usd
    from tools.isaac_vr_decision import capture_state_snapshot

    _validate_session_metadata(session_metadata)
    repository = Path(__file__).resolve().parents[1]
    output_dir = prepare_private_output_dir(
        output_dir, repository=repository, min_free_bytes=min_free_bytes
    )
    _atomic_write_json(
        output_dir / "recording_state.json",
        {"artifact_state": "in_progress", "committed_frames": 0, "outcome": None},
    )
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("recording requires a loaded USD stage")
    snapshot = Path(export_stage_snapshot(str(output_dir)))
    snapshot_stage = _sanitize_exported_stage(snapshot)
    snapshot_hash = sha256_file(snapshot)
    asset_closure = write_asset_closure_sidecar(
        snapshot,
        output_dir / "asset_closure.json",
        portable_roots=portable_roots,
    )
    asset_closure_path = output_dir / "asset_closure.json"
    sidecar_path = output_dir / "stage_snapshot.sidecar.json"
    sidecar = json.loads(sidecar_path.read_text()) if sidecar_path.is_file() else {}
    sidecar["sha256"] = snapshot_hash
    _atomic_write_json(sidecar_path, sidecar)
    D0 = ensure_d0_recordable()
    cameras = {
        "left_wrist": env.camera.wrists[0],
        "right_wrist": env.camera.wrists[1],
        "scene": env.camera.scene_camera,
    }
    try:
        from tools.isaac_vr_visual_provenance import build_visual_provenance
    except ImportError:  # Runtime can import tools directly from its source directory.
        from isaac_vr_visual_provenance import build_visual_provenance

    camera_roles = {role: camera._view.prim_paths[0] for role, camera in cameras.items()}
    visual_provenance = build_visual_provenance(
        snapshot_stage,
        {
            role: {"data_type": "rgb", "prim_path": path, "resolution": (640, 480)}
            for role, path in camera_roles.items()
        },
    )
    recordables: list[Any] = [
        SimTimeRecordable(),
        ArticulationRecordable(group="state/left_robot", prim_path="/World/LeftPiper"),
        ArticulationRecordable(group="state/right_robot", prim_path="/World/RightPiper"),
        *(
            RigidBodyRecordable(group=f"state/object_{index}", prim_path=asset.cfg.prim_path)
            for index, asset in enumerate(env.vr_runtime.dynamic_assets)
        ),
        *(
            CameraRecordable(
                group=f"state/camera/{role}",
                prim_path=camera._view.prim_paths[0],
                resolution=(640, 480),
            )
            for role, camera in cameras.items()
        ),
    ]
    d0 = D0()
    recordables.append(d0)
    path = output_dir / "session.hdf5"
    storage_session_metadata = enrich_recording_session_metadata(
        session_metadata,
        stage_snapshot=snapshot.name,
        stage_snapshot_sha256=snapshot_hash,
        asset_closure_sha256=str(asset_closure["asset_closure_sha256"]),
        visual_provenance_sha256=str(visual_provenance["visual_provenance_sha256"]),
    )
    storage, sampler = open_explicit_session(
        str(path),
        recordables=recordables,
        stage=stage,
        session_metadata=storage_session_metadata,
        stage_snapshot=snapshot.name,
        deferred_groups=(d0.group,),
    )
    start_explicit_episode(
        storage,
        sampler,
        recordables,
        {
            "artifact_state": "in_progress",
            "episode_id": session_metadata["episode_id"],
            "outcome": None,
        },
    )
    identity = {key: str(session_metadata[key]) for key in REQUIRED_SESSION_METADATA}
    manifest = {
        "schema": "piper_x_isaac_vr_recording_manifest_v2",
        "artifact_state": "in_progress",
        "asset_closure": asset_closure_path.name,
        "asset_closure_sha256": asset_closure["asset_closure_sha256"],
        "camera_roles": camera_roles,
        "committed_frames": 0,
        "dataset_admissible": False,
        "dirty_status": subprocess.check_output(
            ["git", "-C", str(repository), "status", "--porcelain=v1"], text=True
        ),
        "git_commit": subprocess.check_output(
            ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
        ).strip(),
        "hdf5": path.name,
        "pose_backend_effective": POSE_BACKEND,
        "pose_backend_requested": POSE_BACKEND,
        "recordables": [recordable.to_manifest() for recordable in recordables],
        "session_metadata": storage_session_metadata,
        "stage_snapshot": snapshot.name,
        "stage_snapshot_sha256": snapshot_hash,
        "transition_schema": TRANSITION_SCHEMA,
        "visual_provenance": visual_provenance,
        "visual_provenance_sha256": visual_provenance["visual_provenance_sha256"],
    }
    _atomic_write_json(output_dir / "manifest.json", manifest)
    return LiveRecording(
        storage,
        sampler,
        recordables,
        d0,
        output_dir=output_dir,
        hdf5_path=path,
        snapshot=snapshot,
        identity=identity,
        observation_factory=lambda: capture_state_snapshot(env),
        flush_every_frames=flush_every_frames,
    )


def _sanitize_exported_stage(snapshot: Path) -> Any:
    """Remove runtime-only prims and open the immutable replay input.

    ``export_stage_snapshot`` may canonicalize authored asset paths.  Hashing the
    live stage would therefore describe a different composed input than replay
    later opens.  Render, Replicator, and XR graphs are runtime products and
    collide with fresh offline render products when persisted.  A separate USD
    stage preserves the active simulation while binding provenance to the
    sanitized snapshot that replay actually opens.
    """
    from pxr import Usd

    stage = Usd.Stage.Open(str(snapshot))
    if stage is None:
        raise RuntimeError(f"could not open exported recording snapshot: {snapshot}")
    for path in ("/Render", "/Replicator", "/_xr"):
        if stage.GetPrimAtPath(path).IsValid():
            stage.RemovePrim(path)
    if stage.GetRootLayer().Save() is False:
        raise RuntimeError(f"could not save sanitized recording snapshot: {snapshot}")
    return stage


def enrich_recording_session_metadata(
    metadata: Mapping[str, Any],
    *,
    stage_snapshot: str,
    stage_snapshot_sha256: str,
    asset_closure_sha256: str,
    visual_provenance_sha256: str,
) -> dict[str, Any]:
    """Bind public HDF session metadata to the verified portable scene artifact."""
    _validate_session_metadata(metadata)
    snapshot_path = Path(stage_snapshot)
    if (
        not stage_snapshot
        or snapshot_path.is_absolute()
        or len(snapshot_path.parts) != 1
        or snapshot_path.name != stage_snapshot
    ):
        raise ValueError("stage_snapshot must be one safe artifact-relative filename")
    for field, digest in (
        ("stage_snapshot_sha256", stage_snapshot_sha256),
        ("asset_closure_sha256", asset_closure_sha256),
        ("visual_provenance_sha256", visual_provenance_sha256),
    ):
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"{field} must be lowercase SHA-256 hex")
    return {
        **dict(metadata),
        "stage_snapshot": stage_snapshot,
        "stage_snapshot_sha256": stage_snapshot_sha256,
        "asset_closure_sha256": asset_closure_sha256,
        "visual_provenance_sha256": visual_provenance_sha256,
    }


def write_asset_closure_sidecar(
    snapshot: Path,
    sidecar_path: Path,
    *,
    portable_roots: Mapping[str, str | os.PathLike[str]],
    dependency_provider: Callable[
        [str], tuple[Iterable[Any], Iterable[Any], Iterable[Any]]
    ]
    | None = None,
) -> dict[str, object]:
    """Traverse the saved stage and atomically persist its portable closure."""

    try:
        from .isaac_vr_asset_closure import build_asset_closure_manifest
    except ImportError:  # Runtime imports tools directly from its source directory.
        from isaac_vr_asset_closure import build_asset_closure_manifest

    closure = build_asset_closure_manifest(
        snapshot,
        portable_roots=portable_roots,
        dependency_provider=dependency_provider,
    )
    _atomic_write_json(sidecar_path, closure)
    return closure


def ensure_d0_recordable() -> type[Any]:
    """Register the provenance-only committed-transition V2 track inside Kit."""
    from isaacsim.replicator.episode_recorder import ChannelDescriptor, Recordable, register_recordable

    @register_recordable
    class D0TransitionRecordable(Recordable):
        TYPE_ID = TRANSITION_SCHEMA

        def __init__(self, *, group: str = "d0/committed_transition") -> None:
            super().__init__(group=group)

        def describe_channels(self) -> dict[str, Any]:
            return _d0_channels(ChannelDescriptor)

        def sample(self) -> dict[str, Any]:
            raise RuntimeError("committed transition samples are supplied only after causal commit")

        def apply(self, frame: Mapping[str, np.ndarray], *, policy: Any) -> None:
            return  # provenance only; world state is replayed by NVIDIA tracks

        def to_manifest(self) -> dict[str, Any]:
            return {"type": self.TYPE_ID, "group": self.group, "schema": TRANSITION_SCHEMA}

        @classmethod
        def from_manifest(cls, entry: Mapping[str, Any]) -> Any:
            return cls(group=str(entry["group"]))

    return D0TransitionRecordable


def _d0_channels(ChannelDescriptor: Any) -> dict[str, Any]:
    def scalar(dtype: str = "i8", **attrs: Any) -> Any:
        return ChannelDescriptor(shape=(), dtype=dtype, **attrs)

    def vector(dtype: str = "f4", **attrs: Any) -> Any:
        return ChannelDescriptor(shape=(14,), dtype=dtype, **attrs)

    def fixed_id() -> Any:
        return ChannelDescriptor(shape=(), dtype=f"S{_ID_BYTES}")

    def digest() -> Any:
        return ChannelDescriptor(shape=(_HASH_BYTES,), dtype="u1", attrs={"encoding": "sha256"})

    return {
        "schema_version": scalar("u2"),
        "frame_index": scalar(),
        "run_id": fixed_id(),
        "session_id": fixed_id(),
        "episode_id": fixed_id(),
        "source_id": fixed_id(),
        "source_epoch": fixed_id(),
        "obs_id": fixed_id(),
        "scene_state_snapshot_id": fixed_id(),
        "scene_state_snapshot_sha256": digest(),
        "observation_payload_sha256": digest(),
        "observation_state": vector(units="policy_state"),
        "observation_physics_step": scalar(),
        "observation_capture_sequence": scalar(),
        "simulation_state_generation": scalar(),
        "dataset_action_id": fixed_id(),
        "action_source_id": fixed_id(),
        "action_payload_sha256": digest(),
        "action_source_sha256": digest(),
        "dataset_action": vector(units="deg_mm"),
        "processor_revision": fixed_id(),
        "processor_provenance_revision": fixed_id(),
        "processor_generation": scalar(),
        "native_command_id": fixed_id(),
        "native_command_sha256": digest(),
        "native_preclip": vector(units="joint_radians_gripper_metres"),
        "native_clipped": vector(units="joint_radians_gripper_metres"),
        "native_residual": vector(units="joint_radians_gripper_metres"),
        "saturation": vector("u1"),
        "transition_id": fixed_id(),
        "transition_payload_sha256": digest(),
        "transition_outcome": fixed_id(),
        "terminated": scalar("u1"),
        "success": scalar("u1"),
        "failure_code": fixed_id(),
        "failure_reason": fixed_id(),
        "next_obs_id": fixed_id(),
        "next_scene_state_snapshot_id": fixed_id(),
        "next_scene_state_snapshot_sha256": digest(),
        "successor_payload_sha256": digest(),
        "successor_observation_state": vector(units="policy_state"),
        "successor_physics_step": scalar(),
        "successor_capture_sequence": scalar(),
        "successor_state_generation": scalar(),
        "successor_reset_epoch": scalar(),
        "control_tick_id": scalar(),
        "reset_epoch": scalar(),
        "control_reference_epoch": scalar(),
        "session_epoch": scalar(),
        "deviceio_update_epoch": scalar(),
        "submitted_frame_id": scalar(),
        "returned_frame_id": scalar(),
        "xr_deviceio_source_id": fixed_id(),
        "xr_deviceio_source_sha256": digest(),
        "xr_submitted_source_id": fixed_id(),
        "xr_submitted_source_sha256": digest(),
        "xr_returned_source_id": fixed_id(),
        "xr_returned_source_sha256": digest(),
        "xr_resolved_source_id": fixed_id(),
        "xr_resolved_source_sha256": digest(),
        "xr_ran_synchronously": scalar("u1"),
        "xr_rebased": scalar("u1"),
        "tracking_valid": ChannelDescriptor(shape=(2,), dtype="u1"),
        "xr_world_transform": ChannelDescriptor(shape=(16,), dtype="f4"),
        "xr_hands_sha256": digest(),
        "committed": scalar("u1"),
    }


def canonical_transition_outcome_payload(
    *,
    transition_id: str,
    transition_outcome: str,
    terminated: bool,
    success: bool,
    failure_code: str,
    failure_reason: str,
) -> bytes:
    return json.dumps(
        {
            "failure_code": failure_code,
            "failure_reason": failure_reason,
            "success": bool(success),
            "terminated": bool(terminated),
            "transition_id": transition_id,
            "transition_outcome": transition_outcome,
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def verify_committed_transition_sample(sample: Mapping[str, Any]) -> None:
    """Recompute every payload/source digest represented by one D0 row."""
    from tools.isaac_vr_decision import (
        canonical_action_payload,
        canonical_native_command_payload,
        canonical_state_snapshot_payload,
        canonical_xr_payload_from_fields,
    )

    observation_payload = canonical_state_snapshot_payload(
        reset_epoch=int(sample["reset_epoch"]),
        physics_step=int(sample["observation_physics_step"]),
        state_generation=int(sample["simulation_state_generation"]),
        capture_sequence=int(sample["observation_capture_sequence"]),
        scene_state_snapshot_id=_decode_fixed_id(sample["scene_state_snapshot_id"]),
        scene_state_snapshot_sha256=_digest_hex(sample["scene_state_snapshot_sha256"]),
        state=sample["observation_state"],
    )
    successor_payload = canonical_state_snapshot_payload(
        reset_epoch=int(sample["successor_reset_epoch"]),
        physics_step=int(sample["successor_physics_step"]),
        state_generation=int(sample["successor_state_generation"]),
        capture_sequence=int(sample["successor_capture_sequence"]),
        scene_state_snapshot_id=_decode_fixed_id(sample["next_scene_state_snapshot_id"]),
        scene_state_snapshot_sha256=_digest_hex(sample["next_scene_state_snapshot_sha256"]),
        state=sample["successor_observation_state"],
    )
    action_payload = canonical_action_payload(
        sample["dataset_action"],
        processor_revision=_decode_fixed_id(sample["processor_revision"]),
        provenance_revision=_decode_fixed_id(sample["processor_provenance_revision"]),
        processor_generation=int(sample["processor_generation"]),
    )
    native_payload = canonical_native_command_payload(
        preclip=sample["native_preclip"],
        clipped=sample["native_clipped"],
        residual=sample["native_residual"],
        saturation=sample["saturation"],
    )
    xr_payload = canonical_xr_payload_from_fields(
        session_epoch=int(sample["session_epoch"]),
        control_reference_epoch=int(sample["control_reference_epoch"]),
        deviceio_update_epoch=int(sample["deviceio_update_epoch"]),
        submitted_frame_id=int(sample["submitted_frame_id"]),
        returned_frame_id=int(sample["returned_frame_id"]),
        ran_synchronously=bool(sample["xr_ran_synchronously"]),
        rebased=bool(sample["xr_rebased"]),
        tracking_valid=sample["tracking_valid"],
        world_transform=sample["xr_world_transform"],
        hands_sha256=_digest_hex(sample["xr_hands_sha256"]),
    )
    transition_payload = canonical_transition_outcome_payload(
        transition_id=_decode_fixed_id(sample["transition_id"]),
        transition_outcome=_decode_fixed_id(sample["transition_outcome"]),
        terminated=bool(sample["terminated"]),
        success=bool(sample["success"]),
        failure_code=_decode_fixed_id(sample["failure_code"]),
        failure_reason=_decode_fixed_id(sample["failure_reason"]),
    )
    expected = {
        "observation_payload_sha256": observation_payload,
        "successor_payload_sha256": successor_payload,
        "action_payload_sha256": action_payload,
        "native_command_sha256": native_payload,
        "transition_payload_sha256": transition_payload,
        "action_source_sha256": xr_payload,
        "xr_deviceio_source_sha256": xr_payload,
        "xr_submitted_source_sha256": xr_payload,
        "xr_returned_source_sha256": xr_payload,
        "xr_resolved_source_sha256": xr_payload,
    }
    for field, canonical_payload in expected.items():
        actual = _digest_hex(sample[field])
        wanted = hashlib.sha256(canonical_payload).hexdigest()
        if actual != wanted:
            raise ValueError(f"{field} does not verify from stored row payload")


def build_committed_transition_sample(
    recording: LiveRecording,
    token: RecordedObservationToken,
    successor_token: RecordedObservationToken,
    decision: Any,
    committed: Any,
    *,
    transition_outcome: str = "continued",
    terminated: bool = False,
    success: bool = False,
    failure_code: str = "",
    failure_reason: str = "",
) -> dict[str, Any]:
    """Build the exact HDF row from causal-validator identities and payloads.

    ``committed`` is the public project ``CommittedRecordingTransition`` receipt.
    The helper intentionally consumes its prepared/completed identities rather
    than asking the runtime to reconstruct IDs or hashes a second time.
    """
    if decision.observation_identity is not token.observation:
        raise ValueError("decision observation is not the recorder's buffered O_t")
    if committed.successor_observation is not successor_token.observation:
        raise ValueError("causal successor is not the recorder's buffered O_(t+1)")
    prepared, completed = committed.prepared, committed.completed
    if prepared.observation.payload_id == completed.successor.payload_id:
        raise ValueError("successor identity must differ from O_t")
    sources = {source.name: source for source in prepared.sources}
    required_sources = {
        "simulation.scene_state_snapshot",
        "xr.device_io_update",
        "xr.submitted_frame",
        "xr.returned_frame",
        "xr.resolved_input",
    }
    if set(sources) != required_sources or len(sources) != len(prepared.sources):
        raise ValueError("committed receipt lacks unique offline-RGB source identities")
    scene_source = sources["simulation.scene_state_snapshot"]
    action_source = sources["xr.resolved_input"]
    epoch = prepared.observation.epoch
    xr = decision.xr_identity
    if xr is None:
        raise ValueError("committed recording decision lacks XR identity")
    if tuple(float(value) for value in decision.observation_identity.state) != token.state:
        raise ValueError("decision O_t state differs from recorder token")
    from tools.isaac_vr_decision import (
        canonical_hands_sha256,
        canonical_native_command_fields,
    )

    processor_revision, provenance_revision, processor_generation = decision.processor_identity
    hands_sha256 = canonical_hands_sha256(xr.hands)
    native_fields = canonical_native_command_fields(
        preclip=decision.native_preclip, clipped=decision.native_clipped
    )
    result = canonical_committed_transition(
        {
            "schema_version": 2,
            "frame_index": recording.committed_frames,
            "run_id": recording.run_id,
            "session_id": recording.session_id,
            "episode_id": recording.episode_id,
            "source_id": scene_source.name,
            "source_epoch": epoch.source_epoch,
            "obs_id": prepared.observation.payload_id,
            "scene_state_snapshot_id": token.scene_state_snapshot_id,
            "scene_state_snapshot_sha256": token.scene_state_snapshot_sha256,
            "observation_payload_sha256": prepared.observation.sha256,
            "observation_state": np.asarray(token.state, dtype=np.float32),
            "observation_physics_step": token.physics_step,
            "observation_capture_sequence": token.capture_sequence,
            "simulation_state_generation": token.state_generation,
            "dataset_action_id": prepared.dataset_action.payload_id,
            "action_source_id": action_source.sample.payload_id,
            "action_payload_sha256": prepared.dataset_action.sha256,
            "action_source_sha256": action_source.sample.sha256,
            "dataset_action": np.asarray(decision.dataset_action, dtype=np.float32),
            "processor_revision": processor_revision,
            "processor_provenance_revision": provenance_revision,
            "processor_generation": processor_generation,
            "native_command_id": completed.native_command.payload_id,
            "native_command_sha256": completed.native_command.sha256,
            "native_preclip": native_fields["preclip"],
            "native_clipped": native_fields["clipped"],
            "native_residual": native_fields["residual"],
            "saturation": native_fields["saturation"],
            "transition_id": completed.transition_id,
            "transition_payload_sha256": hashlib.sha256(
                canonical_transition_outcome_payload(
                    transition_id=completed.transition_id,
                    transition_outcome=transition_outcome,
                    terminated=terminated,
                    success=success,
                    failure_code=failure_code,
                    failure_reason=failure_reason,
                )
            ).hexdigest(),
            "transition_outcome": transition_outcome,
            "terminated": np.uint8(terminated),
            "success": np.uint8(success),
            "failure_code": failure_code,
            "failure_reason": failure_reason,
            "next_obs_id": completed.successor.payload_id,
            "next_scene_state_snapshot_id": successor_token.scene_state_snapshot_id,
            "next_scene_state_snapshot_sha256": successor_token.scene_state_snapshot_sha256,
            "successor_payload_sha256": completed.successor.sha256,
            "successor_observation_state": np.asarray(successor_token.state, dtype=np.float32),
            "successor_physics_step": successor_token.physics_step,
            "successor_capture_sequence": successor_token.capture_sequence,
            "successor_state_generation": successor_token.state_generation,
            "successor_reset_epoch": successor_token.reset_epoch,
            "control_tick_id": prepared.observation.control_tick_id,
            "reset_epoch": epoch.reset_epoch,
            "control_reference_epoch": epoch.control_reference_epoch,
            "session_epoch": int(epoch.source_epoch),
            "deviceio_update_epoch": xr.deviceio_update_epoch,
            "submitted_frame_id": xr.submitted_frame_id,
            "returned_frame_id": xr.returned_frame_id,
            "xr_deviceio_source_id": sources["xr.device_io_update"].sample.payload_id,
            "xr_deviceio_source_sha256": sources["xr.device_io_update"].sample.sha256,
            "xr_submitted_source_id": sources["xr.submitted_frame"].sample.payload_id,
            "xr_submitted_source_sha256": sources["xr.submitted_frame"].sample.sha256,
            "xr_returned_source_id": sources["xr.returned_frame"].sample.payload_id,
            "xr_returned_source_sha256": sources["xr.returned_frame"].sample.sha256,
            "xr_resolved_source_id": sources["xr.resolved_input"].sample.payload_id,
            "xr_resolved_source_sha256": sources["xr.resolved_input"].sample.sha256,
            "xr_ran_synchronously": np.uint8(xr.ran_synchronously),
            "xr_rebased": np.uint8(xr.rebased),
            "tracking_valid": np.asarray(xr.tracking_valid, dtype=np.uint8),
            "xr_world_transform": np.asarray(xr.world_transform, dtype=np.float32),
            "xr_hands_sha256": hands_sha256,
            "committed": np.uint8(1),
        }
    )
    verify_committed_transition_sample(result)
    return result


def canonical_committed_transition(sample: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize one admitted ``(O_t, A_t, O_t+1)`` row."""
    channels = _d0_channels(_Descriptor)
    if set(sample) != set(channels):
        missing = sorted(set(channels).difference(sample))
        extra = sorted(set(sample).difference(channels))
        raise ValueError(f"committed transition channels mismatch; missing={missing}, extra={extra}")
    result: dict[str, Any] = {}
    id_fields = {
        "run_id",
        "session_id",
        "episode_id",
        "source_id",
        "source_epoch",
        "obs_id",
        "scene_state_snapshot_id",
        "dataset_action_id",
        "action_source_id",
        "processor_revision",
        "processor_provenance_revision",
        "native_command_id",
        "transition_id",
        "transition_outcome",
        "next_obs_id",
        "next_scene_state_snapshot_id",
        "xr_deviceio_source_id",
        "xr_submitted_source_id",
        "xr_returned_source_id",
        "xr_resolved_source_id",
    }
    optional_text_fields = {"failure_code", "failure_reason"}
    hash_fields = {name for name in channels if name.endswith("_sha256")}
    for name, descriptor in channels.items():
        if name in optional_text_fields:
            result[name] = _fixed_text(sample[name], field=name, allow_empty=True)
        elif name in id_fields:
            result[name] = _fixed_id(sample[name], field=name)
        elif name in hash_fields:
            result[name] = _sha256_bytes(sample[name], field=name)
        else:
            value = np.asarray(sample[name], dtype=np.dtype(descriptor.dtype))
            if value.shape != tuple(descriptor.shape):
                raise ValueError(f"{name}: shape {value.shape} != {descriptor.shape}")
            if np.issubdtype(value.dtype, np.floating) and not np.isfinite(value).all():
                raise ValueError(f"{name}: non-finite value")
            result[name] = value
    if int(result["schema_version"]) != 2:
        raise ValueError("schema_version must be 2")
    if int(result["committed"]) != 1:
        raise ValueError("only causally committed transitions may be admitted")
    if int(result["frame_index"]) < 0 or int(result["control_tick_id"]) < 0:
        raise ValueError("frame_index and control_tick_id must be nonnegative")
    if _decode_fixed_id(result["obs_id"]) == _decode_fixed_id(result["next_obs_id"]):
        raise ValueError("successor observation identity must differ from O_t")
    if _decode_fixed_id(result["scene_state_snapshot_id"]) == _decode_fixed_id(
        result["next_scene_state_snapshot_id"]
    ):
        raise ValueError("successor scene snapshot identity must differ from O_t")
    if _decode_fixed_id(result["action_source_id"]) != _decode_fixed_id(
        result["xr_resolved_source_id"]
    ):
        raise ValueError("action source must be the stored resolved XR source")
    try:
        source_epoch = int(_decode_fixed_id(result["source_epoch"]))
    except ValueError as exc:
        raise ValueError("VR source_epoch must be an integer session epoch") from exc
    if source_epoch != int(result["session_epoch"]):
        raise ValueError("source_epoch must equal the stored XR session_epoch")
    if int(result["successor_physics_step"]) != int(result["observation_physics_step"]) + 4:
        raise ValueError("successor_physics_step must be exactly four steps after O_t")
    if int(result["successor_capture_sequence"]) != int(result["observation_capture_sequence"]) + 1:
        raise ValueError("successor_capture_sequence must be exactly one after O_t")
    if int(result["successor_reset_epoch"]) != int(result["reset_epoch"]):
        raise ValueError("successor_reset_epoch must equal the O_t reset epoch")
    if int(result["simulation_state_generation"]) != int(result["observation_physics_step"]):
        raise ValueError("O_t state generation must equal its physics step")
    if int(result["successor_state_generation"]) != int(result["successor_physics_step"]):
        raise ValueError("successor state generation must equal its physics step")
    terminated, success = int(result["terminated"]), int(result["success"])
    if terminated not in (0, 1) or success not in (0, 1):
        raise ValueError("terminated and success must be boolean")
    outcome = _decode_fixed_id(result["transition_outcome"])
    expected_outcome = (
        "continued" if not terminated else "terminated_success" if success else "terminated_failure"
    )
    if outcome != expected_outcome:
        raise ValueError(f"transition_outcome must be {expected_outcome!r} for termination/success flags")
    if not terminated and success:
        raise ValueError("a non-terminated transition cannot be successful")
    failure_code = _decode_fixed_id(result["failure_code"])
    failure_reason = _decode_fixed_id(result["failure_reason"])
    if success and (failure_code or failure_reason):
        raise ValueError("successful transition cannot carry failure classification")
    if outcome == "terminated_failure" and not failure_code:
        raise ValueError("terminated failure requires failure_code")
    if not np.array_equal(result["tracking_valid"], np.ones(2, dtype=np.uint8)):
        raise ValueError("committed XR transition requires both tracking flags")
    if int(result["xr_ran_synchronously"]) != 1 or int(result["xr_rebased"]) != 0:
        raise ValueError("committed XR input must be synchronous and not rebased")
    if int(result["submitted_frame_id"]) != int(result["returned_frame_id"]):
        raise ValueError("submitted and returned XR frame identities must match")
    if int(result["processor_generation"]) < 0:
        raise ValueError("processor_generation must be nonnegative")
    saturation = np.asarray(result["saturation"], dtype=np.uint8)
    if not np.isin(saturation, (0, 1)).all():
        raise ValueError("saturation flags must be boolean")
    residual = np.asarray(result["native_residual"], dtype=np.float32)
    expected_residual = np.asarray(result["native_clipped"], dtype=np.float32) - np.asarray(
        result["native_preclip"], dtype=np.float32
    )
    if not np.allclose(residual, expected_residual, rtol=1e-5, atol=1e-7):
        raise ValueError("native_residual must equal native_clipped - native_preclip")
    if not np.array_equal(saturation, (residual != 0).astype(np.uint8)):
        raise ValueError("saturation flags must exactly match nonzero native_residual")
    return result


def _empty_d0_sample() -> dict[str, Any]:
    """Return a deliberately non-admissible shape fixture for schema tooling/tests."""
    result: dict[str, Any] = {}
    for name, descriptor in _d0_channels(_Descriptor).items():
        dtype = np.dtype(descriptor.dtype)
        if dtype.kind == "S":
            result[name] = np.asarray(b"", dtype=dtype)
        else:
            result[name] = np.zeros(descriptor.shape, dtype=dtype)
    result["schema_version"] = np.uint16(2)
    result["frame_index"] = np.int64(-1)
    result["committed"] = np.uint8(0)
    return result


def prepare_private_output_dir(
    output_dir: Path,
    *,
    repository: Path,
    min_free_bytes: int,
) -> Path:
    """Validate and create a new private recording directory with mode ``0700``."""
    output_dir = Path(output_dir)
    if not output_dir.is_absolute():
        raise ValueError("recording output directory must be absolute")
    if min_free_bytes < 0:
        raise ValueError("min_free_bytes must be nonnegative")
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"recording output directory already exists: {output_dir}")
    parent = output_dir.parent
    resolved_parent = parent.resolve(strict=True)
    if parent != resolved_parent:
        raise ValueError("recording output parent must not traverse symlinks")
    parent_stat = resolved_parent.stat()
    if not stat.S_ISDIR(parent_stat.st_mode):
        raise NotADirectoryError(resolved_parent)
    if parent_stat.st_uid != os.getuid():
        raise PermissionError("recording output parent must be owned by the current uid")
    if stat.S_IMODE(parent_stat.st_mode) & 0o077:
        raise PermissionError("recording output parent must not grant group/other permissions")
    resolved_repository = repository.resolve(strict=True)
    candidate = (resolved_parent / output_dir.name).resolve(strict=False)
    if candidate == resolved_repository or candidate.is_relative_to(resolved_repository):
        raise ValueError("recording output directory must be outside the repository")
    free = shutil.disk_usage(resolved_parent).free
    if free < min_free_bytes:
        raise OSError(f"insufficient recording disk space: {free} < required {min_free_bytes}")
    candidate.mkdir(mode=0o700)
    if stat.S_IMODE(candidate.stat().st_mode) != 0o700:
        candidate.chmod(0o700)
    return candidate


def sha256_file(path: Path, *, chunk_bytes: int = 1024 * 1024) -> str:
    """Hash a file with bounded memory."""
    if chunk_bytes < 1:
        raise ValueError("chunk_bytes must be positive")
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def write_terminal_successor_snapshot(
    path: Path,
    token: RecordedObservationToken,
    frames: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Atomically persist the final full Recordable O_(t+1) bundle.

    The file is a deterministic, uncompressed NPZ-compatible ZIP.  Array
    member names are generated indexes rather than Recordable-controlled
    paths, so group/channel names cannot escape the archive namespace.
    """
    path = Path(path)
    if path.name != TERMINAL_SUCCESSOR_FILENAME:
        raise ValueError(f"terminal successor must be named {TERMINAL_SUCCESSOR_FILENAME!r}")
    if not frames:
        raise ValueError("terminal successor must contain at least one Recordable group")
    arrays: list[tuple[str, np.ndarray]] = []
    descriptors: list[dict[str, Any]] = []
    seen_channels: set[tuple[str, str]] = set()
    for group in sorted(frames):
        if not group or not frames[group]:
            raise ValueError("terminal successor groups and channel maps must be non-empty")
        for channel in sorted(frames[group]):
            identity = (str(group), str(channel))
            if identity in seen_channels:
                raise ValueError(f"duplicate terminal successor channel: {identity!r}")
            seen_channels.add(identity)
            value = np.ascontiguousarray(np.asarray(frames[group][channel]))
            if value.dtype.hasobject:
                raise TypeError(f"terminal successor {group}/{channel} cannot contain objects")
            entry = f"arrays/{len(arrays):08d}.npy"
            arrays.append((entry, value))
            descriptors.append(
                {
                    "channel": str(channel),
                    "dtype": value.dtype.str,
                    "entry": entry,
                    "group": str(group),
                    "shape": list(value.shape),
                }
            )
    snapshot_sha256 = _captured_frame_sha256(frames)
    if snapshot_sha256 != token.scene_state_snapshot_sha256:
        raise ValueError("terminal successor frames differ from the committed snapshot digest")
    metadata = {
        "arrays": descriptors,
        "capture_sequence": token.capture_sequence,
        "observation_state": list(token.state),
        "physics_step": token.physics_step,
        "reset_epoch": token.reset_epoch,
        "scene_state_snapshot_id": token.scene_state_snapshot_id,
        "scene_state_snapshot_sha256": token.scene_state_snapshot_sha256,
        "schema": TERMINAL_SUCCESSOR_SCHEMA,
        "state_generation": token.state_generation,
    }
    metadata_bytes = json.dumps(
        metadata, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as raw_stream:
            with zipfile.ZipFile(raw_stream, mode="w", compression=zipfile.ZIP_STORED) as archive:
                _write_deterministic_zip_member(archive, "metadata.json", metadata_bytes)
                for entry, value in arrays:
                    buffer = io.BytesIO()
                    np.lib.format.write_array(buffer, value, allow_pickle=False)
                    _write_deterministic_zip_member(archive, entry, buffer.getvalue())
            raw_stream.flush()
            os.fsync(raw_stream.fileno())
        os.replace(temporary, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return {
        "capture_sequence": token.capture_sequence,
        "file": path.name,
        "scene_state_snapshot_id": token.scene_state_snapshot_id,
        "scene_state_snapshot_sha256": token.scene_state_snapshot_sha256,
        "schema": TERMINAL_SUCCESSOR_SCHEMA,
        "sha256": sha256_file(path),
    }


def verify_terminal_successor_snapshot(
    path: Path,
    *,
    expected_artifact_sha256: str,
    committed_transition: Mapping[str, Any] | None = None,
) -> TerminalSuccessorSnapshot:
    """Verify and decode a terminal successor artifact, failing closed.

    Passing the last committed D0 row additionally proves that the complete
    Recordable bundle is its declared successor rather than an unrelated valid
    snapshot.  Strict replay should always provide that row.
    """
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("terminal successor must be a regular non-symlink file")
    if path.name != TERMINAL_SUCCESSOR_FILENAME:
        raise ValueError(f"terminal successor must be named {TERMINAL_SUCCESSOR_FILENAME!r}")
    if not _is_sha256_hex(expected_artifact_sha256):
        raise ValueError("terminal successor artifact digest must be lowercase SHA-256 hex")
    artifact_sha256 = sha256_file(path)
    if artifact_sha256 != expected_artifact_sha256:
        raise ValueError("terminal successor artifact digest mismatch")
    try:
        with zipfile.ZipFile(path, mode="r") as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or "metadata.json" not in names:
                raise ValueError("terminal successor archive has duplicate entries or no metadata")
            metadata_entry = archive.getinfo("metadata.json")
            if metadata_entry.file_size > 4 * 1024 * 1024:
                raise ValueError("terminal successor metadata is unreasonably large")
            metadata = json.loads(archive.read(metadata_entry).decode("utf-8"))
            if not isinstance(metadata, dict) or metadata.get("schema") != TERMINAL_SUCCESSOR_SCHEMA:
                raise ValueError("terminal successor schema mismatch")
            if set(metadata) != {
                "arrays",
                "capture_sequence",
                "observation_state",
                "physics_step",
                "reset_epoch",
                "scene_state_snapshot_id",
                "scene_state_snapshot_sha256",
                "schema",
                "state_generation",
            }:
                raise ValueError("terminal successor metadata fields are not canonical")
            descriptors = metadata.get("arrays")
            if not isinstance(descriptors, list) or not descriptors or len(descriptors) > 10000:
                raise ValueError("terminal successor array table is invalid")
            expected_names = {"metadata.json"}
            frames: dict[str, dict[str, np.ndarray]] = {}
            prior_key: tuple[str, str] | None = None
            for index, descriptor in enumerate(descriptors):
                if not isinstance(descriptor, dict) or set(descriptor) != {
                    "channel", "dtype", "entry", "group", "shape"
                }:
                    raise ValueError("terminal successor array descriptor is invalid")
                group, channel = descriptor["group"], descriptor["channel"]
                entry = descriptor["entry"]
                key = (group, channel)
                if not isinstance(group, str) or not group or not isinstance(channel, str) or not channel:
                    raise ValueError("terminal successor group/channel must be non-empty strings")
                if prior_key is not None and key <= prior_key:
                    raise ValueError("terminal successor descriptors are not uniquely sorted")
                prior_key = key
                expected_entry = f"arrays/{index:08d}.npy"
                if entry != expected_entry:
                    raise ValueError("terminal successor array entry is not canonical")
                expected_names.add(entry)
                member = archive.getinfo(entry)
                if member.file_size > 8 * 1024 * 1024 * 1024:
                    raise ValueError("terminal successor array is unreasonably large")
                payload = archive.read(member)
                buffer = io.BytesIO(payload)
                value = np.lib.format.read_array(buffer, allow_pickle=False)
                if buffer.tell() != len(payload) or value.dtype.hasobject:
                    raise ValueError("terminal successor array encoding is invalid")
                if value.dtype.str != descriptor["dtype"] or list(value.shape) != descriptor["shape"]:
                    raise ValueError("terminal successor array dtype/shape differs from metadata")
                frames.setdefault(group, {})[channel] = np.ascontiguousarray(value)
            if set(names) != expected_names:
                raise ValueError("terminal successor archive contains undeclared entries")
    except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile, KeyError) as exc:
        raise ValueError(f"terminal successor archive is invalid: {exc}") from exc

    snapshot_sha256 = _captured_frame_sha256(frames)
    snapshot_id = _required_metadata_text(metadata, "scene_state_snapshot_id")
    _fixed_id(snapshot_id, field="scene_state_snapshot_id")
    declared_snapshot_sha256 = _required_metadata_text(metadata, "scene_state_snapshot_sha256")
    if not _is_sha256_hex(declared_snapshot_sha256) or snapshot_sha256 != declared_snapshot_sha256:
        raise ValueError("terminal successor Recordable snapshot digest mismatch")
    state = metadata.get("observation_state")
    if not isinstance(state, list) or len(state) != 14:
        raise ValueError("terminal successor observation_state must be float[14]")
    state_array = np.asarray(state, dtype=np.float64)
    if not np.isfinite(state_array).all():
        raise ValueError("terminal successor observation_state must be finite")
    token = RecordedObservationToken(
        token_id=_required_metadata_int(metadata, "capture_sequence"),
        observation=None,
        state=tuple(float(value) for value in state_array),
        physics_step=_required_metadata_int(metadata, "physics_step"),
        capture_sequence=_required_metadata_int(metadata, "capture_sequence"),
        reset_epoch=_required_metadata_int(metadata, "reset_epoch"),
        state_generation=_required_metadata_int(metadata, "state_generation"),
        scene_state_snapshot_id=snapshot_id,
        scene_state_snapshot_sha256=declared_snapshot_sha256,
    )
    if committed_transition is not None:
        canonical = canonical_committed_transition(committed_transition)
        verify_committed_transition_sample(canonical)
        if snapshot_id != _decode_fixed_id(canonical["next_scene_state_snapshot_id"]):
            raise ValueError("terminal successor identity differs from the last committed row")
        if declared_snapshot_sha256 != _digest_hex(
            canonical["next_scene_state_snapshot_sha256"]
        ):
            raise ValueError("terminal successor digest differs from the last committed row")
        expected_state = np.asarray(canonical["successor_observation_state"], dtype=np.float32)
        if not np.array_equal(np.asarray(token.state, dtype=np.float32), expected_state):
            raise ValueError("terminal successor native state differs from the last committed row")
        scalar_bindings = {
            "physics_step": "successor_physics_step",
            "capture_sequence": "successor_capture_sequence",
            "state_generation": "successor_state_generation",
            "reset_epoch": "successor_reset_epoch",
        }
        for token_field, row_field in scalar_bindings.items():
            if getattr(token, token_field) != int(canonical[row_field]):
                raise ValueError(
                    f"terminal successor {token_field} differs from the last committed row"
                )
    return TerminalSuccessorSnapshot(token, frames, artifact_sha256)


def _write_deterministic_zip_member(
    archive: zipfile.ZipFile, name: str, payload: bytes
) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    archive.writestr(info, payload)


def _required_metadata_text(metadata: Mapping[str, Any], field: str) -> str:
    value = metadata.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"terminal successor {field} must be a non-empty string")
    return value


def _required_metadata_int(metadata: Mapping[str, Any], field: str) -> int:
    value = metadata.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"terminal successor {field} must be a nonnegative integer")
    return value


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _to_numpy_f32(value: Any) -> np.ndarray:
    if isinstance(value, np.ndarray):
        array = value
    elif hasattr(value, "numpy"):
        array = value.numpy()
    elif hasattr(value, "cpu"):
        array = value.cpu().numpy()
    else:
        array = np.asarray(value)
    return np.asarray(array, dtype=np.float32)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _validate_session_metadata(metadata: Mapping[str, Any]) -> None:
    missing = [key for key in REQUIRED_SESSION_METADATA if not str(metadata.get(key, "")).strip()]
    if missing:
        raise ValueError(f"session_metadata requires non-empty fields: {missing}")
    for key in REQUIRED_SESSION_METADATA:
        _fixed_id(metadata[key], field=key)


def _fixed_id(value: Any, *, field: str) -> np.ndarray:
    return _fixed_text(value, field=field, allow_empty=False)


def _fixed_text(value: Any, *, field: str, allow_empty: bool) -> np.ndarray:
    if isinstance(value, np.ndarray):
        if value.shape != ():
            raise ValueError(f"{field} must be a scalar identifier")
        value = value.item()
    if isinstance(value, bytes):
        encoded = value
    else:
        encoded = str(value).encode("utf-8")
    minimum = 0 if allow_empty else 1
    if len(encoded) < minimum or len(encoded) > _ID_BYTES or b"\0" in encoded:
        raise ValueError(f"{field} must encode to {minimum}..{_ID_BYTES} non-NUL bytes")
    return np.asarray(encoded, dtype=f"S{_ID_BYTES}")


def _decode_fixed_id(value: Any) -> str:
    raw = np.asarray(value, dtype=f"S{_ID_BYTES}").item()
    return raw.rstrip(b"\0").decode("utf-8")


def _sha256_bytes(value: Any, *, field: str) -> np.ndarray:
    if isinstance(value, str):
        try:
            raw = bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be a 64-character hex SHA-256") from exc
    elif isinstance(value, bytes):
        raw = value
    else:
        array = np.asarray(value)
        if array.shape != (_HASH_BYTES,):
            raise ValueError(f"{field} must contain {_HASH_BYTES} bytes")
        raw = bytes(np.asarray(array, dtype=np.uint8))
    if len(raw) != _HASH_BYTES:
        raise ValueError(f"{field} must contain {_HASH_BYTES} bytes")
    return np.frombuffer(raw, dtype=np.uint8).copy()


def _digest_hex(value: Any) -> str:
    array = np.asarray(value, dtype=np.uint8)
    if array.shape != (_HASH_BYTES,):
        raise ValueError(f"digest must contain {_HASH_BYTES} bytes")
    return bytes(array).hex()


def _captured_frame_sha256(frames: Mapping[str, Mapping[str, Any]]) -> str:
    """Content-address an immutable upstream O_t bundle without positional inference."""
    digest = hashlib.sha256()
    for group in sorted(frames):
        group_bytes = group.encode("utf-8")
        digest.update(len(group_bytes).to_bytes(4, "little"))
        digest.update(group_bytes)
        for channel in sorted(frames[group]):
            name_bytes = channel.encode("utf-8")
            value = np.ascontiguousarray(np.asarray(frames[group][channel]))
            dtype_bytes = value.dtype.str.encode("ascii")
            digest.update(len(name_bytes).to_bytes(4, "little"))
            digest.update(name_bytes)
            digest.update(len(dtype_bytes).to_bytes(2, "little"))
            digest.update(dtype_bytes)
            digest.update(len(value.shape).to_bytes(2, "little"))
            for dimension in value.shape:
                digest.update(int(dimension).to_bytes(8, "little"))
            digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


class _Descriptor:
    def __init__(self, *, shape: tuple[int, ...], dtype: str, **_: Any) -> None:
        self.shape, self.dtype = shape, dtype
