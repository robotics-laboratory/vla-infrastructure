"""Fail-closed NVIDIA Episode Recorder replay and offline RGB materialization.

Filesystem validation intentionally has no Kit dependency so corrupt or
incomplete artifacts are rejected before a USD stage is touched.  The
``replay_from_snapshot`` entry point runs immediately after AppLauncher creates
Kit and before the current task scene is constructed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

try:
    from .isaac_vr_asset_closure import AssetClosureError, verify_asset_closure_manifest
except ImportError:  # Runtime imports tools directly from its source directory.
    from isaac_vr_asset_closure import AssetClosureError, verify_asset_closure_manifest
try:
    from .isaac_vr_visual_provenance import (
        VisualProvenanceError,
        assert_visual_provenance_matches,
        verify_visual_provenance,
    )
except ImportError:  # Runtime imports tools directly from its source directory.
    from isaac_vr_visual_provenance import (
        VisualProvenanceError,
        assert_visual_provenance_matches,
        verify_visual_provenance,
    )


CANONICAL_CAMERA_ROLES = ("left_wrist", "right_wrist", "scene")
REQUIRED_TRACKS = frozenset(
    {
        "state/left_robot",
        "state/right_robot",
        "state/camera/left_wrist",
        "state/camera/right_wrist",
        "state/camera/scene",
        "d0/committed_transition",
    }
)
REQUIRED_TRACK_TYPES = {
    "state/left_robot": "articulation",
    "state/right_robot": "articulation",
    "state/camera/left_wrist": "camera",
    "state/camera/right_wrist": "camera",
    "state/camera/scene": "camera",
    "d0/committed_transition": "piper_x_committed_transition_v2",
}
# Version 1 encoded O_n beside A_(n-1), so it is deliberately unsupported.
SUPPORTED_RECORDING_SCHEMAS = frozenset({"piper_x_isaac_vr_recording_manifest_v2"})


@dataclass(frozen=True)
class ReplayArtifact:
    """Verified immutable inputs required before Kit opens the snapshot."""

    recording: Path
    snapshot: Path
    manifest_path: Path
    manifest: Mapping[str, Any]
    hdf5_sha256: str
    snapshot_sha256: str
    asset_closure_path: Path
    asset_closure_sha256: str
    visual_provenance: Mapping[str, Any]
    visual_provenance_sha256: str
    terminal_successor_path: Path
    terminal_successor_sha256: str
    camera_paths: Mapping[str, str]
    committed_frames: int
    outcome: str


@dataclass(frozen=True)
class ReplaySession:
    """Validated HDF episode identity and transaction summary."""

    episode_name: str
    frames: int
    tracks: tuple[Mapping[str, Any], ...]
    observation_ids: tuple[str, ...]
    scene_state_snapshot_ids: tuple[str, ...]
    scene_state_snapshot_sha256: tuple[str, ...]
    committed_count: int


def _sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _required_digest(manifest: Mapping[str, Any], key: str) -> str:
    value = manifest.get(key)
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"recording manifest requires a SHA-256 value for {key}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"recording manifest has invalid SHA-256 for {key}") from exc
    return value.lower()


def verify_recording_artifact(
    recording: Path,
    *,
    portable_roots: Mapping[str, str | Path],
) -> ReplayArtifact:
    """Verify the finalized HDF, snapshot and camera bindings without importing Kit."""
    recording = recording.expanduser().resolve()
    if not recording.is_file():
        raise FileNotFoundError(f"recording HDF5 not found: {recording}")
    artifact_dir = recording.parent
    manifest_path = artifact_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"recording manifest not found: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"recording manifest is unreadable: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("recording manifest root must be an object")
    schema = manifest.get("schema")
    if schema not in SUPPORTED_RECORDING_SCHEMAS:
        raise ValueError(
            f"unsupported recording manifest schema {schema!r}; "
            f"expected one of {sorted(SUPPORTED_RECORDING_SCHEMAS)}"
        )
    if manifest.get("artifact_state") != "finalized":
        raise ValueError("recording artifact is not finalized")
    state_path = artifact_dir / "recording_state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"recording finalization marker not found: {state_path}")
    try:
        finalization = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"recording finalization marker is unreadable: {state_path}") from exc
    if finalization.get("artifact_state") != "finalized":
        raise ValueError("recording finalization marker is not finalized")
    committed_frames = manifest.get("committed_frames")
    if type(committed_frames) is not int or committed_frames <= 0:
        raise ValueError("finalized recording must declare a positive committed_frames count")
    if finalization.get("committed_frames") != committed_frames:
        raise ValueError("recording manifest and finalization marker frame counts differ")
    outcome = manifest.get("outcome")
    if outcome not in {"success", "operator_stopped"}:
        raise ValueError("finalized recording has no accepted terminal outcome")
    if finalization.get("outcome") != outcome:
        raise ValueError("recording manifest and finalization marker outcomes differ")
    if (
        manifest.get("pose_backend_requested") != "fabric"
        or manifest.get("pose_backend_effective") != "fabric"
    ):
        raise ValueError("recording did not prove the required Fabric pose backend")
    if manifest.get("transition_schema") != "piper_x_committed_transition_v2":
        raise ValueError("recording manifest has an unsupported transition schema")
    session_metadata = manifest.get("session_metadata")
    if (
        not isinstance(session_metadata, dict)
        or session_metadata.get("source_profile") != "isaac_human_vr_offline_rgb_v1"
    ):
        raise ValueError("recording manifest has an unsupported source profile")

    declared_hdf = manifest.get("hdf5")
    if declared_hdf is not None and declared_hdf != recording.name:
        raise ValueError(
            f"recording filename {recording.name!r} does not match manifest {declared_hdf!r}"
        )
    hdf5_sha256 = _required_digest(manifest, "hdf5_sha256")
    if finalization.get("hdf5_sha256") != hdf5_sha256:
        raise ValueError("recording manifest and finalization marker HDF hashes differ")
    actual_hdf5_sha256 = _sha256(recording)
    if actual_hdf5_sha256 != hdf5_sha256:
        raise ValueError(
            f"recording HDF5 digest mismatch: expected {hdf5_sha256}, got {actual_hdf5_sha256}"
        )

    snapshot_name = manifest.get("stage_snapshot")
    if not isinstance(snapshot_name, str) or not snapshot_name:
        raise ValueError("recording manifest requires stage_snapshot")
    snapshot_relative = Path(snapshot_name)
    if snapshot_relative.is_absolute() or ".." in snapshot_relative.parts:
        raise ValueError("stage_snapshot must be a safe artifact-relative path")
    snapshot = (artifact_dir / snapshot_relative).resolve()
    if not snapshot.is_relative_to(artifact_dir):
        raise ValueError("stage_snapshot escapes the recording artifact directory")
    if not snapshot.is_file():
        raise FileNotFoundError(f"recording stage snapshot not found: {snapshot}")
    snapshot_sha256 = _required_digest(manifest, "stage_snapshot_sha256")
    actual_snapshot_sha256 = _sha256(snapshot)
    if actual_snapshot_sha256 != snapshot_sha256:
        raise ValueError(
            f"stage snapshot digest mismatch: expected {snapshot_sha256}, got {actual_snapshot_sha256}"
        )

    asset_closure_name = manifest.get("asset_closure")
    if not isinstance(asset_closure_name, str) or not asset_closure_name:
        raise ValueError("recording manifest requires asset_closure")
    asset_closure_relative = Path(asset_closure_name)
    if asset_closure_relative.is_absolute() or ".." in asset_closure_relative.parts:
        raise ValueError("asset_closure must be a safe artifact-relative path")
    asset_closure_path = (artifact_dir / asset_closure_relative).resolve()
    if not asset_closure_path.is_relative_to(artifact_dir):
        raise ValueError("asset_closure escapes the recording artifact directory")
    if not asset_closure_path.is_file():
        raise FileNotFoundError(f"recording asset closure not found: {asset_closure_path}")
    asset_closure_sha256 = _required_digest(manifest, "asset_closure_sha256")
    try:
        asset_closure = verify_asset_closure_manifest(
            asset_closure_path,
            portable_roots=portable_roots,
            expected_stage_snapshot=snapshot,
        )
    except AssetClosureError as exc:
        raise ValueError(f"recording asset closure verification failed: {exc}") from exc
    if asset_closure["asset_closure_sha256"] != asset_closure_sha256:
        raise ValueError("recording manifest and asset closure aggregate hashes differ")

    visual_provenance = manifest.get("visual_provenance")
    if not isinstance(visual_provenance, dict):
        raise ValueError("recording manifest requires visual_provenance")
    visual_provenance_sha256 = _required_digest(manifest, "visual_provenance_sha256")
    try:
        verified_visual_provenance = verify_visual_provenance(visual_provenance)
    except VisualProvenanceError as exc:
        raise ValueError(f"recording visual provenance verification failed: {exc}") from exc
    if verified_visual_provenance["visual_provenance_sha256"] != visual_provenance_sha256:
        raise ValueError("recording manifest and visual provenance hashes differ")

    camera_paths = manifest.get("camera_roles")
    if not isinstance(camera_paths, dict) or set(camera_paths) != set(CANONICAL_CAMERA_ROLES):
        raise ValueError(
            f"recording camera_roles must contain exactly {list(CANONICAL_CAMERA_ROLES)}"
        )
    normalized_camera_paths: dict[str, str] = {}
    for role in CANONICAL_CAMERA_ROLES:
        path = camera_paths[role]
        if not isinstance(path, str) or not path.startswith("/") or "//" in path:
            raise ValueError(f"recording camera path for {role} is not an absolute USD prim path")
        normalized_camera_paths[role] = path
    if len(set(normalized_camera_paths.values())) != len(normalized_camera_paths):
        raise ValueError("recording camera prim paths must be unique")
    provenance_camera_paths = {
        str(entry["role"]): str(entry["prim_path"])
        for entry in verified_visual_provenance["camera_roles"]
    }
    if provenance_camera_paths != normalized_camera_paths:
        raise ValueError("recording camera roles disagree with visual provenance")

    terminal = manifest.get("terminal_successor")
    if not isinstance(terminal, dict):
        raise ValueError("finalized recording requires a terminal successor artifact")
    if terminal.get("file") != "terminal_successor.npz":
        raise ValueError("recording terminal successor has an unsupported filename")
    terminal_path = (artifact_dir / "terminal_successor.npz").resolve()
    if not terminal_path.is_relative_to(artifact_dir):
        raise ValueError("terminal successor escapes the recording artifact directory")
    terminal_sha256 = _required_digest(terminal, "sha256")
    try:
        from isaac_vr_recording import verify_terminal_successor_snapshot
    except ImportError:
        from tools.isaac_vr_recording import verify_terminal_successor_snapshot
    try:
        verified_terminal = verify_terminal_successor_snapshot(
            terminal_path,
            expected_artifact_sha256=terminal_sha256,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(f"recording terminal successor verification failed: {exc}") from exc
    if terminal.get("schema") != "piper_x_terminal_successor_v1":
        raise ValueError("recording terminal successor schema is unsupported")
    if terminal.get("scene_state_snapshot_id") != verified_terminal.token.scene_state_snapshot_id:
        raise ValueError("recording manifest terminal successor identity mismatch")
    if (
        terminal.get("scene_state_snapshot_sha256")
        != verified_terminal.token.scene_state_snapshot_sha256
    ):
        raise ValueError("recording manifest terminal successor digest mismatch")
    if terminal.get("capture_sequence") != verified_terminal.token.capture_sequence:
        raise ValueError("recording manifest terminal successor sequence mismatch")

    return ReplayArtifact(
        recording=recording,
        snapshot=snapshot,
        manifest_path=manifest_path,
        manifest=manifest,
        hdf5_sha256=hdf5_sha256,
        snapshot_sha256=snapshot_sha256,
        asset_closure_path=asset_closure_path,
        asset_closure_sha256=asset_closure_sha256,
        visual_provenance=verified_visual_provenance,
        visual_provenance_sha256=visual_provenance_sha256,
        terminal_successor_path=terminal_path,
        terminal_successor_sha256=terminal_sha256,
        camera_paths=normalized_camera_paths,
        committed_frames=committed_frames,
        outcome=outcome,
    )


def _validate_session(reader: Any, artifact: ReplayArtifact, episode: int) -> ReplaySession:
    episodes = reader.list_episodes()
    if not episodes:
        raise RuntimeError("recording contains no episodes")
    episode_name = reader.normalize_episode(episode)
    frames = reader.num_frames(episode_name)
    if frames <= 0:
        raise RuntimeError("recording episode contains no committed frames")
    if frames != artifact.committed_frames:
        raise RuntimeError(
            f"HDF frame count {frames} != finalized manifest {artifact.committed_frames}"
        )
    manifest = reader.manifest()
    tracks = tuple(dict(track) for track in manifest.tracks)
    track_groups = {str(track.get("group")) for track in tracks}
    if len(track_groups) != len(tracks):
        raise RuntimeError("recording manifest contains duplicate track groups")
    missing = REQUIRED_TRACKS - track_groups
    if missing:
        raise RuntimeError(f"recording missing required tracks: {sorted(missing)}")
    track_types = {str(track.get("group")): track.get("type") for track in tracks}
    mismatched_types = {
        group: {"expected": expected, "actual": track_types.get(group)}
        for group, expected in REQUIRED_TRACK_TYPES.items()
        if track_types.get(group) != expected
    }
    if mismatched_types:
        raise RuntimeError(f"recording required track types mismatch: {mismatched_types}")

    hdf_session = dict(manifest.session)
    external_session = artifact.manifest["session_metadata"]
    for key in ("run_id", "session_id", "episode_id", "source_profile"):
        if hdf_session.get(key) != external_session.get(key):
            raise RuntimeError(f"HDF/public manifest session identity mismatch for {key}")
    if hdf_session.get("stage_snapshot") != artifact.snapshot.name:
        raise RuntimeError("HDF public manifest does not bind the verified stage snapshot")
    if hdf_session.get("stage_snapshot_sha256") != artifact.snapshot_sha256:
        raise RuntimeError("HDF public manifest does not bind the verified snapshot digest")
    if hdf_session.get("asset_closure_sha256") != artifact.asset_closure_sha256:
        raise RuntimeError("HDF public manifest does not bind the verified asset closure")
    if hdf_session.get("visual_provenance_sha256") != artifact.visual_provenance_sha256:
        raise RuntimeError("HDF public manifest does not bind the verified visual provenance")
    sampling = dict(manifest.sampling)
    if (
        sampling.get("pose_backend") != "fabric"
        or sampling.get("mode") != "explicit_committed_control_boundary"
    ):
        raise RuntimeError("HDF public manifest has unsupported sampling provenance")
    attrs = reader.episode_attrs(episode_name)
    if int(attrs.get("num_frames", frames)) != frames:
        raise RuntimeError("HDF episode attributes disagree with the frame count")

    d0 = reader.read_group_all_frames(episode_name, "d0/committed_transition")
    try:
        from isaac_vr_recording import (
            _empty_d0_sample,
            canonical_committed_transition,
            verify_committed_transition_sample,
        )
    except ImportError:  # Unit tests import through the repository package.
        from tools.isaac_vr_recording import (
            _empty_d0_sample,
            canonical_committed_transition,
            verify_committed_transition_sample,
        )
    expected_channels = set(_empty_d0_sample())
    if set(d0) != expected_channels:
        missing_channels = expected_channels - set(d0)
        extra_channels = set(d0) - expected_channels
        raise RuntimeError(
            "canonical D0 transition channels mismatch; "
            f"missing={sorted(missing_channels)}, extra={sorted(extra_channels)}"
        )
    arrays = {name: np.asarray(values) for name, values in d0.items()}
    malformed = sorted(name for name, values in arrays.items() if values.shape[:1] != (frames,))
    if malformed:
        raise RuntimeError(f"D0 channel frame dimensions are malformed: {malformed}")
    rows: list[dict[str, Any]] = []
    for frame in range(frames):
        raw = {name: values[frame] for name, values in arrays.items()}
        try:
            canonical = canonical_committed_transition(raw)
            verify_committed_transition_sample(canonical)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"D0 frame {frame} failed canonical verification: {exc}") from exc
        if int(canonical["frame_index"]) != frame:
            raise RuntimeError(f"D0 frame {frame} has a non-dense committed index")
        rows.append(canonical)

    def text(value: Any) -> str:
        return bytes(np.asarray(value).tobytes()).rstrip(b"\0").decode("utf-8")

    def digest(value: Any) -> bytes:
        return np.asarray(value, dtype=np.uint8).tobytes()

    observation_ids = tuple(text(row["obs_id"]) for row in rows)
    scene_state_snapshot_ids = tuple(text(row["scene_state_snapshot_id"]) for row in rows)
    scene_state_snapshot_sha256 = tuple(
        digest(row["scene_state_snapshot_sha256"]).hex() for row in rows
    )
    for field in ("obs_id", "dataset_action_id", "native_command_id", "transition_id"):
        identities = [text(row[field]) for row in rows]
        if len(identities) != len(set(identities)):
            raise RuntimeError(f"D0 reuses {field} within one episode")
    terminated_at = [index for index, row in enumerate(rows) if int(row["terminated"])]
    if terminated_at and terminated_at != [frames - 1]:
        raise RuntimeError("D0 terminal transition must be the final committed row")

    for index, (current, following) in enumerate(zip(rows, rows[1:], strict=False)):
        exact_text_pairs = (
            ("next_obs_id", "obs_id"),
            ("next_scene_state_snapshot_id", "scene_state_snapshot_id"),
        )
        for left, right in exact_text_pairs:
            if text(current[left]) != text(following[right]):
                raise RuntimeError(f"D0 successor continuity mismatch at frame {index}: {left}")
        exact_digest_pairs = (
            ("next_scene_state_snapshot_sha256", "scene_state_snapshot_sha256"),
            ("successor_payload_sha256", "observation_payload_sha256"),
        )
        for left, right in exact_digest_pairs:
            if digest(current[left]) != digest(following[right]):
                raise RuntimeError(f"D0 successor continuity mismatch at frame {index}: {left}")
        exact_numeric_pairs = (
            ("successor_observation_state", "observation_state"),
            ("successor_physics_step", "observation_physics_step"),
            ("successor_capture_sequence", "observation_capture_sequence"),
            ("successor_state_generation", "simulation_state_generation"),
            ("successor_reset_epoch", "reset_epoch"),
        )
        for left, right in exact_numeric_pairs:
            if not np.array_equal(current[left], following[right]):
                raise RuntimeError(f"D0 successor continuity mismatch at frame {index}: {left}")
        for counter in (
            "control_tick_id",
            "deviceio_update_epoch",
            "submitted_frame_id",
            "returned_frame_id",
        ):
            if int(following[counter]) != int(current[counter]) + 1:
                raise RuntimeError(f"D0 {counter} is not dense at frame {index}")
        for epoch_field in (
            "run_id",
            "session_id",
            "episode_id",
            "source_id",
            "source_epoch",
            "reset_epoch",
            "control_reference_epoch",
            "session_epoch",
        ):
            if not np.array_equal(current[epoch_field], following[epoch_field]):
                raise RuntimeError(f"D0 crosses {epoch_field} within one episode")

    committed = np.asarray([int(row["committed"]) for row in rows], dtype=bool)
    try:
        from isaac_vr_recording import verify_terminal_successor_snapshot
    except ImportError:
        from tools.isaac_vr_recording import verify_terminal_successor_snapshot
    try:
        verify_terminal_successor_snapshot(
            artifact.terminal_successor_path,
            expected_artifact_sha256=artifact.terminal_successor_sha256,
            committed_transition=rows[-1],
        )
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"terminal successor does not close the final D0 transition: {exc}"
        ) from exc
    return ReplaySession(
        episode_name=episode_name,
        frames=frames,
        tracks=tracks,
        observation_ids=observation_ids,
        scene_state_snapshot_ids=scene_state_snapshot_ids,
        scene_state_snapshot_sha256=scene_state_snapshot_sha256,
        committed_count=int(committed.sum()),
    )


def apply_replay_frames(
    replayer: Any,
    frames: int,
    *,
    pump: Callable[[], None],
    physics_steps: Callable[[], int] | None = None,
    materialize: Callable[[int], None] | None = None,
    assert_quiescent: Callable[[], None] | None = None,
) -> None:
    """Apply frames in order and fail at the first sign of simulation advancement."""
    before = physics_steps() if physics_steps is not None else None
    for frame in range(frames):
        replayer.apply_frame(frame)
        pump()
        if materialize is not None:
            materialize(frame)
        if assert_quiescent is not None:
            assert_quiescent()
    after = physics_steps() if physics_steps is not None else None
    if before is not None and after != before:
        raise RuntimeError(f"replay advanced physics: {before} -> {after}")


def _validate_render_coverage(rendered: list[dict[str, Any]], frames: int) -> None:
    expected = {(frame, role) for frame in range(frames) for role in CANONICAL_CAMERA_ROLES}
    actual = {(int(item["frame"]), str(item["role"])) for item in rendered}
    if actual != expected or len(rendered) != len(expected):
        raise RuntimeError(
            "offline RGB materialization is incomplete: "
            f"expected={len(expected)}, actual={len(rendered)}"
        )


def _bind_render_identity(
    rendered: list[dict[str, Any]],
    *,
    frame: int,
    session: ReplaySession,
    artifact: ReplayArtifact,
) -> None:
    """Bind every RGB to immutable D0, camera, renderer, and stage identities."""

    if not 0 <= frame < session.frames:
        raise IndexError(f"render frame {frame} is outside the replay session")
    cameras = {str(camera["role"]): camera for camera in artifact.visual_provenance["camera_roles"]}
    renderer_sha256 = artifact.visual_provenance["renderer"]["renderer_configuration_sha256"]
    materialization_revision = artifact.visual_provenance["materialization"][
        "materialization_revision"
    ]
    for item in rendered:
        role = str(item.get("role"))
        if int(item.get("frame", -1)) != frame or role not in cameras:
            raise RuntimeError("render output cannot be bound to the requested frame and camera")
        rgb_sha256 = item.get("sha256")
        if not isinstance(rgb_sha256, str) or len(rgb_sha256) != 64:
            raise RuntimeError("render output has no RGB SHA-256")
        camera = cameras[role]
        item.update(
            {
                "asset_closure_sha256": artifact.asset_closure_sha256,
                "camera_configuration_sha256": camera["camera_configuration_sha256"],
                "camera_prim_path": camera["prim_path"],
                "camera_role": role,
                "materialization_revision": materialization_revision,
                "obs_id": session.observation_ids[frame],
                "renderer_configuration_sha256": renderer_sha256,
                "rgb_sha256": rgb_sha256,
                "scene_state_snapshot_id": session.scene_state_snapshot_ids[frame],
                "scene_state_snapshot_sha256": session.scene_state_snapshot_sha256[frame],
                "stage_snapshot_sha256": artifact.snapshot_sha256,
            }
        )


class ReplayRuntimeGuard:
    """Stop automatic simulation and count every PhysX callback during replay."""

    def __init__(self) -> None:
        self._timeline: Any = None
        self._subscription: Any = None
        self.physics_callbacks: list[float] = []

    def configure(self) -> None:
        import carb.settings
        import omni.replicator.core as rep
        import omni.timeline

        settings = carb.settings.get_settings()
        settings.set("/app/player/playSimulations", False)
        rep.orchestrator.set_capture_on_play(False)
        self._timeline = omni.timeline.get_timeline_interface()
        self._timeline.stop()
        if self._timeline.is_playing():
            raise RuntimeError("failed to stop timeline before replay")

    def start_monitoring(self) -> None:
        import omni.physx

        if self._subscription is not None:
            raise RuntimeError("replay physics monitoring already started")
        self.physics_callbacks.clear()
        self._subscription = omni.physx.get_physx_interface().subscribe_physics_step_events(
            lambda dt: self.physics_callbacks.append(float(dt))
        )

    def assert_quiescent(self) -> None:
        if self._timeline is None or self._timeline.is_playing():
            raise RuntimeError("timeline started during state-only replay")
        if self.physics_callbacks:
            raise RuntimeError(f"replay emitted {len(self.physics_callbacks)} physics callbacks")

    def close(self) -> None:
        subscription, self._subscription = self._subscription, None
        if subscription is not None and hasattr(subscription, "unsubscribe"):
            subscription.unsubscribe()


class ReplayCameraMaterializer:
    """Own one persistent render product/annotator per recorded camera role."""

    def __init__(self, camera_paths: Mapping[str, str], output_dir: Path) -> None:
        self.camera_paths = dict(camera_paths)
        self.output_dir = output_dir
        self.products: dict[str, Any] = {}
        self.annotators: dict[str, Any] = {}
        self.attached_roles: set[str] = set()
        self._settings: Any = None
        self._previous_orchestrator_enabled: bool | None = None

    def open(self) -> None:
        import carb.settings
        import omni.replicator.core as rep

        if self.output_dir.exists() or self.output_dir.is_symlink():
            raise FileExistsError(f"render output directory already exists: {self.output_dir}")
        self.output_dir.mkdir(parents=True, mode=0o700)
        self.output_dir.chmod(0o700)
        self._settings = carb.settings.get_settings()
        self._previous_orchestrator_enabled = self._settings.get_as_bool(
            "/exts/omni.replicator.core/Orchestrator/enabled"
        )
        # State-only replay has no live Fabric simulation-time producer.  Turn
        # off the reference-time gate so attached RGB annotators expose each
        # explicitly rendered Hydra update without Replicator scheduling.
        self._settings.set("/exts/omni.replicator.core/Orchestrator/enabled", False)
        for role in CANONICAL_CAMERA_ROLES:
            self.products[role] = rep.create.render_product(
                self.camera_paths[role], (640, 480), force_new=True
            )
            annotator = rep.AnnotatorRegistry.get_annotator("rgb")
            self.annotators[role] = annotator
            annotator.attach(self.products[role])
            self.attached_roles.add(role)
        # Render products and SyntheticData graphs are initialized lazily.  A
        # bounded stopped-timeline warm-up mirrors the pinned Replicator's own
        # async-rendering integration test and prevents the first capture from
        # racing graph creation.
        import omni.kit.app

        for _ in range(3):
            omni.kit.app.get_app().update()

    def render(self, frame: int) -> list[dict[str, Any]]:
        import omni.kit.app
        from PIL import Image

        if set(self.annotators) != set(CANONICAL_CAMERA_ROLES):
            raise RuntimeError("all three canonical replay cameras must be prepared")
        for _ in range(4):
            omni.kit.app.get_app().update()
        rendered: list[dict[str, Any]] = []
        for role in CANONICAL_CAMERA_ROLES:
            image = np.asarray(self.annotators[role].get_data())
            if image.shape not in ((480, 640, 4), (480, 640, 3)) or image.dtype != np.uint8:
                raise RuntimeError(f"{role}: unexpected RGB buffer {image.shape} {image.dtype}")
            path = self.output_dir / f"frame_{frame:06d}_{role}.png"
            Image.fromarray(image[..., :3]).save(path)
            path.chmod(0o600)
            rendered.append(
                {
                    "dtype": "uint8",
                    "frame": frame,
                    "path": str(path),
                    "role": role,
                    "sha256": _sha256(path),
                    "shape": [480, 640, 3],
                }
            )
        return rendered

    def close(self) -> None:
        for role in tuple(self.attached_roles):
            self.annotators[role].detach()
            self.attached_roles.remove(role)
        for product in self.products.values():
            product.destroy()
        if self._settings is not None and self._previous_orchestrator_enabled is not None:
            self._settings.set(
                "/exts/omni.replicator.core/Orchestrator/enabled",
                self._previous_orchestrator_enabled,
            )
        self._settings = None
        self._previous_orchestrator_enabled = None
        self.annotators.clear()
        self.products.clear()


def _open_verified_snapshot(artifact: ReplayArtifact, simulation_app: Any) -> None:
    """Open and settle the verified snapshot before any Recordable is prepared."""
    import omni.usd

    context = omni.usd.get_context()
    result = context.open_stage(str(artifact.snapshot))
    if result is False:
        raise RuntimeError(f"failed to open recorded stage: {artifact.snapshot}")
    # Opening and renderer initialization are asynchronous in Kit.  These updates
    # happen with playSimulations=false and before replay monitoring starts.
    for _ in range(20):
        simulation_app.update()
    stage = context.get_stage()
    if stage is None:
        raise RuntimeError(f"recorded stage did not open: {artifact.snapshot}")
    root_identifier = Path(stage.GetRootLayer().realPath or stage.GetRootLayer().identifier)
    if root_identifier.resolve() != artifact.snapshot:
        raise RuntimeError(
            f"opened USD root {root_identifier} != verified snapshot {artifact.snapshot}"
        )
    try:
        assert_visual_provenance_matches(artifact.visual_provenance, stage)
    except VisualProvenanceError as exc:
        raise RuntimeError(f"replay visual provenance mismatch: {exc}") from exc


def replay_from_snapshot(
    simulation_app: Any,
    *,
    recording: Path,
    episode: int,
    render_cameras: Path | None,
    report_path: Path,
    portable_roots: Mapping[str, str | Path],
    physics_steps: Callable[[], int] | None = None,
) -> int:
    """Replay a verified artifact in Kit without constructing a current task scene."""
    artifact = verify_recording_artifact(recording, portable_roots=portable_roots)
    report_candidate = report_path.expanduser().resolve(strict=False)
    protected_inputs = {
        artifact.recording,
        artifact.snapshot,
        artifact.manifest_path,
        artifact.asset_closure_path,
        artifact.terminal_successor_path,
        artifact.recording.parent / "recording_state.json",
    }
    if report_candidate in protected_inputs:
        raise ValueError("replay report path would overwrite a verified input artifact")
    if report_candidate.exists() or report_candidate.is_symlink():
        raise FileExistsError(f"replay report path already exists: {report_candidate}")
    report_path = report_candidate

    from isaacsim.replicator.episode_recorder import (
        EpisodeReplayer,
        ReplayPolicy,
        SessionReader,
    )
    from isaac_vr_recording import ensure_d0_recordable

    ensure_d0_recordable()
    with SessionReader(str(artifact.recording)) as reader:
        session = _validate_session(reader, artifact, episode)

    guard = ReplayRuntimeGuard()
    replayer: Any = None
    materializer: ReplayCameraMaterializer | None = None
    rendered: list[dict[str, Any]] = []
    prepared_groups: tuple[str, ...] = ()
    try:
        guard.configure()
        _open_verified_snapshot(artifact, simulation_app)
        guard.start_monitoring()
        replayer = EpisodeReplayer(
            str(artifact.recording),
            policy=ReplayPolicy(strictness="strict"),
            pose_backend="usd",
        )
        replayer.prepare_episode(session.episode_name)
        # Pinned Episode Recorder 0.1.6 exposes the prepared list as a public
        # property, not a callable accessor.
        prepared_groups = tuple(recordable.group for recordable in replayer.prepared_recordables)
        recorded_groups = {str(track["group"]) for track in session.tracks}
        if set(prepared_groups) != recorded_groups or len(prepared_groups) != len(
            set(prepared_groups)
        ):
            raise RuntimeError(
                "strict replay did not prepare every recorded group exactly once: "
                f"prepared={sorted(prepared_groups)}, recorded={sorted(recorded_groups)}"
            )
        if render_cameras is not None:
            materializer = ReplayCameraMaterializer(artifact.camera_paths, render_cameras)
            materializer.open()

        def materialize(frame: int) -> None:
            if materializer is not None:
                frame_renders = materializer.render(frame)
                _bind_render_identity(
                    frame_renders,
                    frame=frame,
                    session=session,
                    artifact=artifact,
                )
                rendered.extend(frame_renders)

        apply_replay_frames(
            replayer,
            session.frames,
            pump=simulation_app.update,
            physics_steps=physics_steps,
            materialize=materialize,
            assert_quiescent=guard.assert_quiescent,
        )
        guard.assert_quiescent()
    finally:
        if materializer is not None:
            materializer.close()
        if replayer is not None:
            replayer.close()
        guard.close()

    if render_cameras is not None:
        _validate_render_coverage(rendered, session.frames)

    report = {
        "schema": "piper_x_isaac_vr_replay_report_v3",
        "recording": str(artifact.recording),
        "recording_sha256": artifact.hdf5_sha256,
        "stage_snapshot": str(artifact.snapshot),
        "stage_snapshot_sha256": artifact.snapshot_sha256,
        "asset_closure": str(artifact.asset_closure_path),
        "asset_closure_sha256": artifact.asset_closure_sha256,
        "visual_provenance_sha256": artifact.visual_provenance_sha256,
        "terminal_successor": str(artifact.terminal_successor_path),
        "terminal_successor_sha256": artifact.terminal_successor_sha256,
        "episode": session.episode_name,
        "frames_applied": session.frames,
        "physics_callbacks": len(guard.physics_callbacks),
        "native_action_replay": False,
        "strict_policy": True,
        "required_tracks": sorted(REQUIRED_TRACKS),
        "tracks": list(session.tracks),
        "prepared_groups": list(prepared_groups),
        "applied_group_frames": {group: session.frames for group in prepared_groups},
        "camera_paths": dict(artifact.camera_paths),
        "renders": rendered,
        "d0": {
            "observation_ids": list(session.observation_ids),
            "committed_count": session.committed_count,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("REPLAY_RESULT_JSON=" + json.dumps(report, sort_keys=True), flush=True)
    return 0


def replay(
    env: Any,
    simulation_app: Any,
    *,
    recording: Path,
    episode: int,
    render_cameras: Path | None,
    report_path: Path,
    portable_roots: Mapping[str, str | Path],
) -> int:
    """Compatibility wrapper pending the runtime's pre-scene integration."""
    return replay_from_snapshot(
        simulation_app,
        recording=recording,
        episode=episode,
        render_cameras=render_cameras,
        report_path=report_path,
        portable_roots=portable_roots,
        physics_steps=env.sim.get_physics_step_count,
    )
