"""Materialize verified Isaac VR recordings as canonical LeRobotDataset v3 data.

The native Episode Recorder environment intentionally does not contain LeRobot,
and the project LeRobot environment intentionally does not contain ``h5py``.
This tool therefore has two fail-closed phases:

* ``extract`` runs in the pinned Isaac Python and emits an immutable projection
  bundle after verifying the finalized recording and every committed D0 row.
* ``materialize`` runs in the project environment, joins replayed RGB images by
  immutable observation/snapshot/camera identity, writes LeRobot v3 videos, and
  reads every frame and stream back through both the dataset and a DataLoader.

``orchestrate`` invokes ``extract`` through an explicitly supplied interpreter
and performs ``materialize`` in the current interpreter.  Image list position is
never used as a join key.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from uuid import uuid4

import numpy as np


# Direct execution places only ``tools/`` on sys.path.  The pure D0 verifier
# deliberately imports sibling modules through the repository ``tools`` package,
# so both the project and pinned Isaac interpreters need the repository root.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


BUNDLE_SCHEMA = "piper_x_isaac_vr_projection_bundle_v1"
MATERIALIZATION_SCHEMA = "piper_x_isaac_vr_lerobot_materialization_v1"
REPLAY_SCHEMA = "piper_x_isaac_vr_replay_report_v3"
SCHEMA_FINGERPRINT = "5926a9271f997202970f757738327593d22ed2ad2696c478cb69a75d35dd1ee1"
CONVERSION_REVISION = "piper_x_isaac_vr_lerobot_materializer_v1"
TASK_LABEL_REVISION = "piper_x_task_labels_v1"
TASK_LABELS = {
    "dual_cube_to_matching_plates": "Move both cubes to their matching plates.",
}
PROJECTION_FILE = "projection.npz"
BUNDLE_MANIFEST = "manifest.json"
MATERIALIZATION_MANIFEST = "isaac_vr_materialization_manifest.json"
FPS = 30
CAMERA_ROLES = ("left_wrist", "right_wrist", "scene")
IMAGE_SHAPE = (480, 640, 3)
VECTOR_SHAPE = (14,)
JOINT_NAMES = (
    "left_joint_1.pos",
    "left_joint_2.pos",
    "left_joint_3.pos",
    "left_joint_4.pos",
    "left_joint_5.pos",
    "left_joint_6.pos",
    "left_gripper.pos",
    "right_joint_1.pos",
    "right_joint_2.pos",
    "right_joint_3.pos",
    "right_joint_4.pos",
    "right_joint_5.pos",
    "right_joint_6.pos",
    "right_gripper.pos",
)
PROJECTION_ARRAYS = (
    "frame_index",
    "observation_state",
    "action",
    "obs_id",
    "scene_state_snapshot_id",
    "scene_state_snapshot_sha256",
    "transition_id",
    "transition_outcome",
    "terminated",
    "success",
    "next_obs_id",
    "successor_observation_state",
)
IMAGE_IDENTITY_FIELDS = (
    "obs_id",
    "scene_state_snapshot_id",
    "scene_state_snapshot_sha256",
    "camera_role",
    "camera_prim_path",
    "camera_configuration_sha256",
    "renderer_configuration_sha256",
    "stage_snapshot_sha256",
    "asset_closure_sha256",
    "materialization_revision",
    "rgb_sha256",
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class MaterializationError(RuntimeError):
    """The source cannot be admitted to the canonical materialized dataset."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_stable(path: Path) -> str:
    try:
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
    except OSError as exc:
        raise MaterializationError(f"cannot hash artifact: {path}") from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        raise MaterializationError(f"artifact changed while it was hashed: {path}")
    return digest.hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise MaterializationError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterializationError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise MaterializationError(f"{label} root must be an object")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _decode_text(value: Any) -> str:
    array = np.asarray(value)
    if array.shape != ():
        raise MaterializationError("native text identity is not scalar")
    raw = array.item()
    if isinstance(raw, bytes):
        text = raw.rstrip(b"\0").decode("utf-8")
    elif isinstance(raw, str):
        text = raw.rstrip("\0")
    else:
        raise MaterializationError(f"native text identity has unsupported type {type(raw)!r}")
    if not text:
        raise MaterializationError("native text identity is empty")
    return text


def _digest_hex(value: Any) -> str:
    raw = np.asarray(value, dtype=np.uint8)
    if raw.shape != (32,):
        raise MaterializationError(f"native digest has shape {raw.shape}, expected (32,)")
    return raw.tobytes().hex()


def _projection_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, np.ndarray]:
    if not rows:
        raise MaterializationError("native episode contains no committed D0 rows")
    frames = len(rows)
    frame_index = np.asarray([int(row["frame_index"]) for row in rows], dtype=np.int64)
    if not np.array_equal(frame_index, np.arange(frames, dtype=np.int64)):
        raise MaterializationError("native committed frame indices are not dense zero-based")

    def texts(field: str) -> np.ndarray:
        return np.asarray([_decode_text(row[field]) for row in rows], dtype=np.str_)

    def digests(field: str) -> np.ndarray:
        return np.asarray([_digest_hex(row[field]) for row in rows], dtype=np.str_)

    observation_state = np.stack(
        [np.asarray(row["observation_state"], dtype=np.float32) for row in rows]
    )
    action = np.stack([np.asarray(row["dataset_action"], dtype=np.float32) for row in rows])
    successor = np.stack(
        [np.asarray(row["successor_observation_state"], dtype=np.float32) for row in rows]
    )
    for field, values in (
        ("observation_state", observation_state),
        ("action", action),
        ("successor_observation_state", successor),
    ):
        if values.shape != (frames, *VECTOR_SHAPE) or values.dtype != np.float32:
            raise MaterializationError(f"{field} must be float32[{frames},14]")
        if not np.isfinite(values).all():
            raise MaterializationError(f"{field} contains NaN or Inf")

    result = {
        "frame_index": frame_index,
        "observation_state": observation_state,
        "action": action,
        "obs_id": texts("obs_id"),
        "scene_state_snapshot_id": texts("scene_state_snapshot_id"),
        "scene_state_snapshot_sha256": digests("scene_state_snapshot_sha256"),
        "transition_id": texts("transition_id"),
        "transition_outcome": texts("transition_outcome"),
        "terminated": np.asarray([int(row["terminated"]) for row in rows], dtype=np.uint8),
        "success": np.asarray([int(row["success"]) for row in rows], dtype=np.uint8),
        "next_obs_id": texts("next_obs_id"),
        "successor_observation_state": successor,
    }
    _validate_projection_arrays(result)
    return result


def _validate_projection_arrays(arrays: Mapping[str, np.ndarray]) -> int:
    if set(arrays) != set(PROJECTION_ARRAYS):
        raise MaterializationError(
            "projection arrays differ from schema: "
            f"missing={sorted(set(PROJECTION_ARRAYS) - set(arrays))}, "
            f"extra={sorted(set(arrays) - set(PROJECTION_ARRAYS))}"
        )
    frame_index = np.asarray(arrays["frame_index"])
    if frame_index.ndim != 1 or frame_index.dtype != np.int64 or len(frame_index) == 0:
        raise MaterializationError("projection frame_index must be a non-empty int64 vector")
    frames = len(frame_index)
    if not np.array_equal(frame_index, np.arange(frames, dtype=np.int64)):
        raise MaterializationError("projection frame_index must be dense and zero-based")
    for field in ("observation_state", "action", "successor_observation_state"):
        values = np.asarray(arrays[field])
        if values.dtype != np.float32 or values.shape != (frames, *VECTOR_SHAPE):
            raise MaterializationError(f"projection {field} must be float32[{frames},14]")
        if not np.isfinite(values).all():
            raise MaterializationError(f"projection {field} contains NaN or Inf")
    for field in (
        "obs_id",
        "scene_state_snapshot_id",
        "scene_state_snapshot_sha256",
        "transition_id",
        "transition_outcome",
        "next_obs_id",
    ):
        values = np.asarray(arrays[field])
        if values.shape != (frames,) or values.dtype.kind != "U":
            raise MaterializationError(f"projection {field} must be a Unicode vector")
        if any(not str(value) for value in values):
            raise MaterializationError(f"projection {field} contains an empty identity")
    for field in ("scene_state_snapshot_sha256",):
        for value in np.asarray(arrays[field]):
            _require_sha256(str(value), field=f"projection.{field}")
    for field in ("obs_id", "scene_state_snapshot_id", "transition_id"):
        values = [str(value) for value in np.asarray(arrays[field])]
        if len(values) != len(set(values)):
            raise MaterializationError(f"projection reuses {field}")
    for field in ("terminated", "success"):
        values = np.asarray(arrays[field])
        if values.shape != (frames,) or values.dtype != np.uint8:
            raise MaterializationError(f"projection {field} must be uint8[{frames}]")
        if not np.isin(values, (0, 1)).all():
            raise MaterializationError(f"projection {field} is not boolean-valued")
    if np.flatnonzero(np.asarray(arrays["terminated"])).tolist() not in ([], [frames - 1]):
        raise MaterializationError("a terminated transition must be the final committed row")
    return frames


def _validate_native_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, np.ndarray]:
    try:
        from tools.isaac_vr_recording import (
            canonical_committed_transition,
            verify_committed_transition_sample,
        )
    except ImportError:  # Isaac starts this module with tools/ on sys.path.
        from isaac_vr_recording import (  # type: ignore[no-redef]
            canonical_committed_transition,
            verify_committed_transition_sample,
        )

    canonical_rows: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        try:
            row = canonical_committed_transition(raw)
            verify_committed_transition_sample(row)
        except (TypeError, ValueError) as exc:
            raise MaterializationError(f"native D0 row {index} failed verification: {exc}") from exc
        if int(row["frame_index"]) != index:
            raise MaterializationError(f"native D0 row {index} has a non-dense frame index")
        if int(row["committed"]) != 1:
            raise MaterializationError(f"native D0 row {index} is not committed")
        canonical_rows.append(row)

    for index, (current, following) in enumerate(zip(canonical_rows, canonical_rows[1:])):
        if _decode_text(current["next_obs_id"]) != _decode_text(following["obs_id"]):
            raise MaterializationError(f"native successor obs_id mismatch at row {index}")
        if _decode_text(current["next_scene_state_snapshot_id"]) != _decode_text(
            following["scene_state_snapshot_id"]
        ):
            raise MaterializationError(f"native successor snapshot ID mismatch at row {index}")
        if _digest_hex(current["next_scene_state_snapshot_sha256"]) != _digest_hex(
            following["scene_state_snapshot_sha256"]
        ):
            raise MaterializationError(f"native successor snapshot digest mismatch at row {index}")
        if _digest_hex(current["successor_payload_sha256"]) != _digest_hex(
            following["observation_payload_sha256"]
        ):
            raise MaterializationError(f"native successor payload mismatch at row {index}")
        if not np.array_equal(
            current["successor_observation_state"], following["observation_state"]
        ):
            raise MaterializationError(f"native successor state mismatch at row {index}")
    return _projection_from_rows(canonical_rows)


def _atomic_directory(target: Path) -> Path:
    target = target.expanduser().resolve(strict=False)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid4().hex}"
    temporary.mkdir(mode=0o700)
    return temporary


def _publish_directory(temporary: Path, target: Path) -> None:
    target = target.expanduser().resolve(strict=False)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"output appeared during materialization: {target}")
    os.replace(temporary, target)


def _write_projection_bundle(
    output: Path,
    arrays: Mapping[str, np.ndarray],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    frames = _validate_projection_arrays(arrays)
    target = output.expanduser().resolve(strict=False)
    temporary = _atomic_directory(target)
    try:
        projection_path = temporary / PROJECTION_FILE
        np.savez_compressed(projection_path, **arrays)
        projection_path.chmod(0o600)
        manifest: dict[str, Any] = {
            "schema": BUNDLE_SCHEMA,
            "conversion_revision": CONVERSION_REVISION,
            "schema_fingerprint_sha256": SCHEMA_FINGERPRINT,
            "frames": frames,
            "projection": {
                "path": PROJECTION_FILE,
                "sha256": _sha256_stable(projection_path),
                "arrays": list(PROJECTION_ARRAYS),
            },
            "source": dict(source),
        }
        manifest["manifest_sha256"] = _canonical_sha256(manifest)
        _write_json(temporary / BUNDLE_MANIFEST, manifest)
        _publish_directory(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return verify_projection_bundle(target)[0]


def verify_projection_bundle(bundle: Path) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    bundle = bundle.expanduser().resolve()
    if not bundle.is_dir():
        raise MaterializationError(f"projection bundle is not a directory: {bundle}")
    manifest = _load_json_object(bundle / BUNDLE_MANIFEST, label="projection manifest")
    if manifest.get("schema") != BUNDLE_SCHEMA:
        raise MaterializationError("unsupported projection bundle schema")
    if manifest.get("conversion_revision") != CONVERSION_REVISION:
        raise MaterializationError("unsupported projection conversion revision")
    if manifest.get("schema_fingerprint_sha256") != SCHEMA_FINGERPRINT:
        raise MaterializationError("projection schema fingerprint mismatch")
    declared_self = _require_sha256(
        manifest.get("manifest_sha256"), field="projection manifest_sha256"
    )
    self_payload = dict(manifest)
    del self_payload["manifest_sha256"]
    if _canonical_sha256(self_payload) != declared_self:
        raise MaterializationError("projection manifest self-hash mismatch")
    projection = manifest.get("projection")
    if not isinstance(projection, dict) or projection.get("path") != PROJECTION_FILE:
        raise MaterializationError("projection manifest has an invalid projection entry")
    if projection.get("arrays") != list(PROJECTION_ARRAYS):
        raise MaterializationError("projection manifest array order differs from schema")
    projection_path = bundle / PROJECTION_FILE
    declared_projection = _require_sha256(projection.get("sha256"), field="projection.sha256")
    if _sha256_stable(projection_path) != declared_projection:
        raise MaterializationError("projection payload digest mismatch")
    try:
        with np.load(projection_path, allow_pickle=False) as archive:
            arrays = {name: np.array(archive[name], copy=True) for name in archive.files}
    except (OSError, ValueError, KeyError) as exc:
        raise MaterializationError("projection payload is unreadable") from exc
    frames = _validate_projection_arrays(arrays)
    if manifest.get("frames") != frames:
        raise MaterializationError("projection manifest frame count mismatch")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise MaterializationError("projection source metadata is missing")
    for field in (
        "recording_sha256",
        "stage_snapshot_sha256",
        "asset_closure_sha256",
        "visual_provenance_sha256",
        "terminal_successor_sha256",
    ):
        _require_sha256(source.get(field), field=f"projection.source.{field}")
    if source.get("source_profile") not in {
        "isaac_human_vr_offline_rgb_v1", "isaac_human_vr_offline_rgb_v2"
    }:
        raise MaterializationError("projection source profile is unsupported")
    visual_identity = source.get("visual_identity")
    if not isinstance(visual_identity, dict):
        raise MaterializationError("projection source visual identity is missing")
    cameras = visual_identity.get("camera_roles")
    if not isinstance(cameras, dict) or set(cameras) != set(CAMERA_ROLES):
        raise MaterializationError("projection source camera identities are incomplete")
    for role, camera in cameras.items():
        if not isinstance(camera, dict) or set(camera) != {
            "camera_configuration_sha256",
            "prim_path",
        }:
            raise MaterializationError(f"projection source camera identity is invalid for {role}")
        _require_sha256(
            camera["camera_configuration_sha256"],
            field=f"projection.source.visual_identity.camera_roles.{role}",
        )
        if not isinstance(camera["prim_path"], str) or not camera["prim_path"]:
            raise MaterializationError(f"projection source camera prim path is invalid for {role}")
    _require_sha256(
        visual_identity.get("renderer_configuration_sha256"),
        field="projection.source.visual_identity.renderer_configuration_sha256",
    )
    if (
        not isinstance(visual_identity.get("materialization_revision"), str)
        or not visual_identity["materialization_revision"]
    ):
        raise MaterializationError("projection source materialization revision is invalid")
    return manifest, arrays


def _extract_hdf_rows(recording: Path, episode: str | None) -> tuple[str, list[dict[str, Any]]]:
    try:
        import h5py  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MaterializationError(
            "extract requires h5py from the pinned Isaac environment"
        ) from exc
    try:
        with h5py.File(recording, "r") as handle:
            episodes = handle.get("episodes")
            if episodes is None:
                raise MaterializationError("native HDF has no episodes group")
            names = sorted(str(name) for name in episodes.keys())
            if episode is None:
                if len(names) != 1:
                    raise MaterializationError(
                        f"native HDF has {len(names)} episodes; select one explicitly"
                    )
                selected = names[0]
            else:
                selected = episode
                if selected not in names:
                    raise MaterializationError(f"native HDF has no episode {selected!r}")
            group = handle.get(f"episodes/{selected}/d0/committed_transition")
            if group is None:
                raise MaterializationError("native HDF has no committed D0 transition group")
            try:
                from tools.isaac_vr_recording import _empty_d0_sample
            except ImportError:
                from isaac_vr_recording import _empty_d0_sample  # type: ignore[no-redef]
            expected = set(_empty_d0_sample())
            actual = set(group.keys())
            if actual != expected:
                raise MaterializationError(
                    "native D0 channels differ from schema: "
                    f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
                )
            arrays = {name: np.asarray(group[name][...]) for name in expected}
            lengths = {values.shape[0] for values in arrays.values() if values.ndim >= 1}
            if len(lengths) != 1:
                raise MaterializationError("native D0 channels have inconsistent frame counts")
            frames = lengths.pop() if lengths else 0
            if frames <= 0:
                raise MaterializationError("native D0 group is empty")
            episode_group = handle[f"episodes/{selected}"]
            declared = int(episode_group.attrs.get("num_frames", -1))
            if declared != frames:
                raise MaterializationError("native episode num_frames disagrees with D0 channels")
            rows = [
                {name: values[index] for name, values in arrays.items()} for index in range(frames)
            ]
    except MaterializationError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise MaterializationError(f"native HDF is unreadable: {recording}") from exc
    return selected, rows


def extract_projection(
    *,
    recording: Path,
    output: Path,
    portable_roots: Mapping[str, Path],
    episode: str | None = None,
) -> dict[str, Any]:
    try:
        from tools.isaac_vr_replay import verify_recording_artifact
        from tools.isaac_vr_recording import verify_terminal_successor_snapshot
    except ImportError:
        from isaac_vr_replay import verify_recording_artifact  # type: ignore[no-redef]
        from isaac_vr_recording import (  # type: ignore[no-redef]
            verify_terminal_successor_snapshot,
        )

    recording = recording.expanduser().resolve()
    artifact = verify_recording_artifact(recording, portable_roots=portable_roots)
    selected, rows = _extract_hdf_rows(recording, episode)
    arrays = _validate_native_rows(rows)
    if len(rows) != artifact.committed_frames:
        raise MaterializationError("native D0 count disagrees with finalized recording manifest")
    try:
        verify_terminal_successor_snapshot(
            artifact.terminal_successor_path,
            expected_artifact_sha256=artifact.terminal_successor_sha256,
            committed_transition=rows[-1],
        )
    except (OSError, TypeError, ValueError) as exc:
        raise MaterializationError(f"terminal successor verification failed: {exc}") from exc
    if _sha256_stable(recording) != artifact.hdf5_sha256:
        raise MaterializationError("native recording changed during extraction")
    session = artifact.manifest.get("session_metadata")
    if not isinstance(session, dict):
        raise MaterializationError("native recording has no session metadata")
    row_episode_id = _decode_text(rows[0]["episode_id"])
    if session.get("episode_id") != row_episode_id:
        raise MaterializationError("native row episode identity disagrees with recording manifest")
    source = {
        "recording": str(recording),
        "recording_sha256": artifact.hdf5_sha256,
        "episode": selected,
        "episode_id": row_episode_id,
        "run_id": _decode_text(rows[0]["run_id"]),
        "session_id": _decode_text(rows[0]["session_id"]),
        "source_profile": session.get("source_profile"),
        "task": session.get("task"),
        "execution_profile": session.get("execution_profile"),
        "outcome": artifact.outcome,
        "stage_snapshot_sha256": artifact.snapshot_sha256,
        "asset_closure_sha256": artifact.asset_closure_sha256,
        "visual_provenance_sha256": artifact.visual_provenance_sha256,
        "terminal_successor_sha256": artifact.terminal_successor_sha256,
        "visual_identity": {
            "camera_roles": {
                str(camera["role"]): {
                    "prim_path": camera["prim_path"],
                    "camera_configuration_sha256": camera["camera_configuration_sha256"],
                }
                for camera in artifact.visual_provenance["camera_roles"]
            },
            "renderer_configuration_sha256": artifact.visual_provenance["renderer"][
                "renderer_configuration_sha256"
            ],
            "materialization_revision": artifact.visual_provenance["materialization"][
                "materialization_revision"
            ],
        },
    }
    return _write_projection_bundle(output, arrays, source)


def _load_rgb(path: Path, declared_sha256: str) -> np.ndarray:
    if not path.is_file():
        raise MaterializationError(f"materialized RGB file is missing: {path}")
    actual_sha256 = _sha256_stable(path)
    if actual_sha256 != declared_sha256:
        raise MaterializationError(
            f"materialized RGB digest mismatch for {path}: "
            f"expected {declared_sha256}, got {actual_sha256}"
        )
    try:
        from PIL import Image

        with Image.open(path) as image:
            array = np.asarray(image)
    except (OSError, ValueError) as exc:
        raise MaterializationError(f"materialized RGB is unreadable: {path}") from exc
    if array.dtype != np.uint8 or array.shape != IMAGE_SHAPE:
        raise MaterializationError(
            f"materialized RGB must be uint8{IMAGE_SHAPE}, got {array.dtype}{array.shape}"
        )
    if _sha256_stable(path) != declared_sha256:
        raise MaterializationError(f"materialized RGB changed while it was decoded: {path}")
    return np.array(array, copy=True)


def _validated_image_join(
    report_path: Path,
    bundle_manifest: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[str, Any]]:
    report_path = report_path.expanduser().resolve()
    report_sha256 = _sha256_stable(report_path)
    report = _load_json_object(report_path, label="replay report")
    if report.get("schema") != REPLAY_SCHEMA:
        raise MaterializationError("replay report is not schema v3")
    if report.get("physics_callbacks") != 0:
        raise MaterializationError("replay report observed physics callbacks")
    if report.get("strict_policy") is not True or report.get("native_action_replay") is not False:
        raise MaterializationError("replay report did not use strict state-only replay")
    frames = _validate_projection_arrays(arrays)
    source = bundle_manifest["source"]
    expected_top = {
        "recording_sha256": source["recording_sha256"],
        "stage_snapshot_sha256": source["stage_snapshot_sha256"],
        "asset_closure_sha256": source["asset_closure_sha256"],
        "visual_provenance_sha256": source["visual_provenance_sha256"],
        "terminal_successor_sha256": source["terminal_successor_sha256"],
        "episode": source["episode"],
        "frames_applied": frames,
    }
    for field, expected in expected_top.items():
        if report.get(field) != expected:
            raise MaterializationError(f"replay report {field} does not match projection source")
    renders = report.get("renders")
    if not isinstance(renders, list):
        raise MaterializationError("replay report renders must be a list")
    camera_paths = report.get("camera_paths")
    if not isinstance(camera_paths, dict) or set(camera_paths) != set(CAMERA_ROLES):
        raise MaterializationError("replay report camera role mapping is incomplete")
    visual_identity = source["visual_identity"]
    expected_cameras = visual_identity["camera_roles"]
    expected_renderer = visual_identity["renderer_configuration_sha256"]
    expected_materialization = visual_identity["materialization_revision"]
    if camera_paths != {role: expected_cameras[role]["prim_path"] for role in CAMERA_ROLES}:
        raise MaterializationError("replay report camera paths differ from recorded provenance")

    joined: dict[tuple[str, str, str], dict[str, Any]] = {}
    per_role_hashes = {role: set() for role in CAMERA_ROLES}
    for index, raw in enumerate(renders):
        if not isinstance(raw, dict):
            raise MaterializationError(f"replay render {index} is not an object")
        for field in IMAGE_IDENTITY_FIELDS:
            if field not in raw:
                raise MaterializationError(f"replay render {index} lacks identity field {field}")
        role = raw["camera_role"]
        if role not in CAMERA_ROLES or raw.get("role") != role:
            raise MaterializationError(f"replay render {index} has an invalid camera role")
        obs_id = raw["obs_id"]
        snapshot_sha256 = _require_sha256(
            raw["scene_state_snapshot_sha256"],
            field=f"replay.renders[{index}].scene_state_snapshot_sha256",
        )
        if not isinstance(obs_id, str) or not obs_id:
            raise MaterializationError(f"replay render {index} has an invalid obs_id")
        key = (obs_id, snapshot_sha256, role)
        if key in joined:
            raise MaterializationError(f"replay report duplicates immutable image identity {key}")
        for field in (
            "camera_configuration_sha256",
            "renderer_configuration_sha256",
            "stage_snapshot_sha256",
            "asset_closure_sha256",
            "rgb_sha256",
            "sha256",
        ):
            _require_sha256(raw.get(field), field=f"replay.renders[{index}].{field}")
        if raw["rgb_sha256"] != raw["sha256"]:
            raise MaterializationError(f"replay render {index} has divergent RGB digests")
        if raw["stage_snapshot_sha256"] != source["stage_snapshot_sha256"]:
            raise MaterializationError(f"replay render {index} has the wrong stage snapshot")
        if raw["asset_closure_sha256"] != source["asset_closure_sha256"]:
            raise MaterializationError(f"replay render {index} has the wrong asset closure")
        if raw["camera_prim_path"] != camera_paths[role]:
            raise MaterializationError(f"replay render {index} has the wrong camera prim path")
        if (
            raw["camera_configuration_sha256"]
            != expected_cameras[role]["camera_configuration_sha256"]
        ):
            raise MaterializationError(f"replay render {index} has the wrong camera configuration")
        if raw["renderer_configuration_sha256"] != expected_renderer:
            raise MaterializationError(
                f"replay render {index} has the wrong renderer configuration"
            )
        if raw["materialization_revision"] != expected_materialization:
            raise MaterializationError(
                f"replay render {index} has the wrong materialization revision"
            )
        if raw.get("dtype") != "uint8" or raw.get("shape") != list(IMAGE_SHAPE):
            raise MaterializationError(f"replay render {index} has the wrong RGB type or shape")
        if (
            not isinstance(raw["scene_state_snapshot_id"], str)
            or not raw["scene_state_snapshot_id"]
        ):
            raise MaterializationError(f"replay render {index} has an invalid snapshot ID")
        if (
            not isinstance(raw["materialization_revision"], str)
            or not raw["materialization_revision"]
        ):
            raise MaterializationError(f"replay render {index} has no materialization revision")
        image_path = Path(raw.get("path", "")).expanduser().resolve()
        image = _load_rgb(image_path, raw["rgb_sha256"])
        joined[key] = {**raw, "image": image, "path": str(image_path)}
        per_role_hashes[role].add(raw["rgb_sha256"])

    expected_keys: set[tuple[str, str, str]] = set()
    for frame in range(frames):
        obs_id = str(arrays["obs_id"][frame])
        snapshot_id = str(arrays["scene_state_snapshot_id"][frame])
        snapshot_sha256 = str(arrays["scene_state_snapshot_sha256"][frame])
        for role in CAMERA_ROLES:
            key = (obs_id, snapshot_sha256, role)
            expected_keys.add(key)
            item = joined.get(key)
            if item is None:
                continue
            if item["scene_state_snapshot_id"] != snapshot_id:
                raise MaterializationError(f"replay image {key} has a mismatched snapshot ID")
            if item.get("frame") != frame:
                raise MaterializationError(f"replay image {key} has a mismatched diagnostic frame")
    if set(joined) != expected_keys:
        missing = sorted(expected_keys - set(joined))
        extra = sorted(set(joined) - expected_keys)
        raise MaterializationError(
            f"replay RGB identity coverage mismatch: missing={missing}, extra={extra}"
        )
    renderer_digests = {str(item["renderer_configuration_sha256"]) for item in joined.values()}
    materialization_revisions = {str(item["materialization_revision"]) for item in joined.values()}
    if len(renderer_digests) != 1:
        raise MaterializationError("replay images use inconsistent renderer configurations")
    if len(materialization_revisions) != 1:
        raise MaterializationError("replay images use inconsistent materialization revisions")
    for role in CAMERA_ROLES:
        configurations = {
            str(item["camera_configuration_sha256"])
            for item in joined.values()
            if item["camera_role"] == role
        }
        if len(configurations) != 1:
            raise MaterializationError(
                f"replay images use inconsistent camera configurations for {role}"
            )
    # Equal PNG digests are a useful QA lead, not evidence of stale geometry:
    # a static camera facing an unchanged scene may legitimately repeat bytes.
    # The separate spatial alignment assay supplies an independent moving
    # witness when liveness is actually required.
    frozen = [role for role, hashes in per_role_hashes.items() if frames > 1 and len(hashes) == 1]
    report["_identical_rgb_digest_roles"] = frozen
    if _sha256_stable(report_path) != report_sha256:
        raise MaterializationError("replay report changed while its images were verified")
    report["_verified_file_sha256"] = report_sha256
    return joined, report


def canonical_lerobot_features() -> dict[str, dict[str, Any]]:
    features: dict[str, dict[str, Any]] = {
        "observation.state": {
            "dtype": "float32",
            "shape": VECTOR_SHAPE,
            "names": list(JOINT_NAMES),
        }
    }
    for role in CAMERA_ROLES:
        features[f"observation.images.{role}"] = {
            "dtype": "video",
            "shape": IMAGE_SHAPE,
            "names": ["height", "width", "channel"],
        }
    features["action"] = {
        "dtype": "float32",
        "shape": VECTOR_SHAPE,
        "names": list(JOINT_NAMES),
    }
    return features


def _qa_lerobot_dataset(
    root: Path,
    *,
    repo_id: str,
    arrays: Mapping[str, np.ndarray],
    task: str,
) -> dict[str, Any]:
    import torch
    from torch.utils.data import DataLoader

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    dataset = LeRobotDataset(repo_id, root=root, video_backend="pyav")
    frames = _validate_projection_arrays(arrays)
    if len(dataset) != frames:
        raise MaterializationError(
            f"LeRobot full-read frame count mismatch: expected {frames}, got {len(dataset)}"
        )
    expected_features = canonical_lerobot_features()
    for key, expected in expected_features.items():
        actual = dataset.features.get(key)
        if not isinstance(actual, dict):
            raise MaterializationError(f"LeRobot dataset lacks canonical feature {key}")
        for field in ("dtype", "shape", "names"):
            actual_value = tuple(actual[field]) if field == "shape" else actual[field]
            expected_value = tuple(expected[field]) if field == "shape" else expected[field]
            if actual_value != expected_value:
                raise MaterializationError(f"LeRobot feature {key}.{field} differs from schema")

    decoded = 0
    for index in range(frames):
        frame = dataset[index]
        state = frame["observation.state"]
        action = frame["action"]
        if state.dtype != torch.float32 or tuple(state.shape) != VECTOR_SHAPE:
            raise MaterializationError(f"LeRobot frame {index} has an invalid state tensor")
        if action.dtype != torch.float32 or tuple(action.shape) != VECTOR_SHAPE:
            raise MaterializationError(f"LeRobot frame {index} has an invalid action tensor")
        if not torch.isfinite(state).all() or not torch.isfinite(action).all():
            raise MaterializationError(f"LeRobot frame {index} contains NaN or Inf")
        if not np.array_equal(state.numpy(), arrays["observation_state"][index]):
            raise MaterializationError(f"LeRobot frame {index} state changed during persistence")
        if not np.array_equal(action.numpy(), arrays["action"][index]):
            raise MaterializationError(f"LeRobot frame {index} action changed during persistence")
        if frame.get("task") != task:
            raise MaterializationError(f"LeRobot frame {index} task identity mismatch")
        if int(frame["frame_index"].item()) != index:
            raise MaterializationError(f"LeRobot frame {index} has a non-dense logical index")
        expected_time = np.float32(index / FPS)
        if frame["timestamp"].item() != expected_time.item():
            raise MaterializationError(f"LeRobot frame {index} has a wrong logical timestamp")
        for role in CAMERA_ROLES:
            image = frame[f"observation.images.{role}"]
            if image.dtype != torch.float32 or tuple(image.shape) != (3, 480, 640):
                raise MaterializationError(f"LeRobot frame {index} {role} decode shape mismatch")
            if not torch.isfinite(image).all() or image.min().item() < 0 or image.max().item() > 1:
                raise MaterializationError(f"LeRobot frame {index} {role} decode range mismatch")
            decoded += 1

    loader = DataLoader(dataset, batch_size=min(2, frames), shuffle=False, num_workers=0)
    loader_frames = 0
    loader_batches = 0
    for batch in loader:
        batch_size = int(batch["observation.state"].shape[0])
        if tuple(batch["observation.state"].shape[1:]) != VECTOR_SHAPE:
            raise MaterializationError("DataLoader state batch shape mismatch")
        if tuple(batch["action"].shape[1:]) != VECTOR_SHAPE:
            raise MaterializationError("DataLoader action batch shape mismatch")
        for role in CAMERA_ROLES:
            image = batch[f"observation.images.{role}"]
            if tuple(image.shape[1:]) != (3, 480, 640) or image.dtype != torch.float32:
                raise MaterializationError(f"DataLoader {role} batch shape mismatch")
        if list(batch["task"]) != [task] * batch_size:
            raise MaterializationError("DataLoader task batch mismatch")
        loader_frames += batch_size
        loader_batches += 1
    if loader_frames != frames:
        raise MaterializationError("DataLoader did not visit every frame")
    return {
        "all_frames_read": frames,
        "all_video_frames_decoded": decoded,
        "dataloader_batches": loader_batches,
        "dataloader_frames": loader_frames,
    }


def _dataset_file_digests(root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise MaterializationError(f"materialized dataset contains a symlink: {path}")
        if not path.is_file() or path.name == MATERIALIZATION_MANIFEST:
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_stable(path),
            }
        )
    if not files:
        raise MaterializationError("materialized dataset contains no files")
    return files


def verify_materialization_manifest(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    manifest = _load_json_object(root / MATERIALIZATION_MANIFEST, label="materialization manifest")
    if manifest.get("schema") != MATERIALIZATION_SCHEMA:
        raise MaterializationError("unsupported materialization manifest schema")
    declared_self = _require_sha256(
        manifest.get("manifest_sha256"), field="materialization manifest_sha256"
    )
    payload = dict(manifest)
    del payload["manifest_sha256"]
    if _canonical_sha256(payload) != declared_self:
        raise MaterializationError("materialization manifest self-hash mismatch")
    declared_files = manifest.get("files")
    if not isinstance(declared_files, list):
        raise MaterializationError("materialization manifest files must be a list")
    if declared_files != _dataset_file_digests(root):
        raise MaterializationError("materialized dataset file inventory or digest mismatch")
    return manifest


def materialize_projection(
    *,
    bundle: Path,
    replay_report: Path,
    output: Path,
    repo_id: str,
    task_id: str,
) -> dict[str, Any]:
    if not repo_id or "/" not in repo_id:
        raise MaterializationError("repo_id must be a non-empty namespace/name")
    bundle_path = bundle.expanduser().resolve()
    report_path = replay_report.expanduser().resolve()
    bundle_manifest, arrays = verify_projection_bundle(bundle_path)
    source_task_id = bundle_manifest["source"].get("task")
    if task_id != source_task_id:
        raise MaterializationError(
            f"task_id {task_id!r} does not match recorded task {source_task_id!r}"
        )
    task = TASK_LABELS.get(task_id)
    if task is None:
        raise MaterializationError(f"recorded task {task_id!r} has no controlled label mapping")
    images, report = _validated_image_join(report_path, bundle_manifest, arrays)
    frames = _validate_projection_arrays(arrays)

    target = output.expanduser().resolve(strict=False)
    temporary = _atomic_directory(target)
    # LeRobot's create API deliberately requires an absent root.  Reserve a
    # collision-resistant sibling name above, then let LeRobot create it.
    temporary.rmdir()
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        dataset = LeRobotDataset.create(
            repo_id=repo_id,
            fps=FPS,
            features=canonical_lerobot_features(),
            root=temporary,
            use_videos=True,
            video_backend="pyav",
        )
        temporary.chmod(0o700)
        for frame in range(frames):
            obs_id = str(arrays["obs_id"][frame])
            snapshot_sha256 = str(arrays["scene_state_snapshot_sha256"][frame])
            sample: dict[str, Any] = {
                "observation.state": np.array(arrays["observation_state"][frame], copy=True),
                "action": np.array(arrays["action"][frame], copy=True),
                "task": task,
            }
            for role in CAMERA_ROLES:
                sample[f"observation.images.{role}"] = np.array(
                    images[(obs_id, snapshot_sha256, role)]["image"], copy=True
                )
            dataset.add_frame(sample)
        dataset.save_episode(parallel_encoding=False)
        dataset.finalize()
        qa = _qa_lerobot_dataset(
            temporary,
            repo_id=repo_id,
            arrays=arrays,
            task=task,
        )
        join_ledger = []
        for frame in range(frames):
            obs_id = str(arrays["obs_id"][frame])
            snapshot_sha256 = str(arrays["scene_state_snapshot_sha256"][frame])
            join_ledger.append(
                {
                    "frame_index": int(arrays["frame_index"][frame]),
                    "obs_id": obs_id,
                    "scene_state_snapshot_id": str(arrays["scene_state_snapshot_id"][frame]),
                    "scene_state_snapshot_sha256": snapshot_sha256,
                    "transition_id": str(arrays["transition_id"][frame]),
                    "observation_state_sha256": hashlib.sha256(
                        np.asarray(arrays["observation_state"][frame], dtype="<f4").tobytes()
                    ).hexdigest(),
                    "action_sha256": hashlib.sha256(
                        np.asarray(arrays["action"][frame], dtype="<f4").tobytes()
                    ).hexdigest(),
                    "images": {
                        role: {
                            **{
                                field: images[(obs_id, snapshot_sha256, role)][field]
                                for field in IMAGE_IDENTITY_FIELDS
                            },
                            "source_path": images[(obs_id, snapshot_sha256, role)]["path"],
                        }
                        for role in CAMERA_ROLES
                    },
                }
            )
        report_sha256 = report.pop("_verified_file_sha256")
        identical_digest_roles = report.pop("_identical_rgb_digest_roles")
        blocking_reasons = ["source_admission_requires_external_physical_vr_qualification"]
        if bundle_manifest["source"].get("outcome") != "success":
            blocking_reasons.append("source_outcome_is_not_success")
        execution_profile = bundle_manifest["source"].get("execution_profile")
        if not isinstance(execution_profile, str) or "smoke" in execution_profile:
            blocking_reasons.append("source_execution_profile_is_not_physical_human_vr")
        manifest: dict[str, Any] = {
            "schema": MATERIALIZATION_SCHEMA,
            "conversion_revision": CONVERSION_REVISION,
            "schema_fingerprint_sha256": SCHEMA_FINGERPRINT,
            "repo_id": repo_id,
            "fps": FPS,
            "frames": frames,
            "episodes": 1,
            "task_id": task_id,
            "task_label": task,
            "task_label_revision": TASK_LABEL_REVISION,
            "task_label_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
            "canonical_feature_order": [
                "observation.state",
                *(f"observation.images.{role}" for role in CAMERA_ROLES),
                "task",
                "action",
            ],
            "source": {
                **bundle_manifest["source"],
                "projection_manifest_sha256": bundle_manifest["manifest_sha256"],
                "projection_payload_sha256": bundle_manifest["projection"]["sha256"],
                "replay_report": str(report_path),
                "replay_report_sha256": report_sha256,
                "replay_schema": report["schema"],
            },
            "admission": {
                "dataset_admissible": False,
                "blocking_reasons": blocking_reasons,
            },
            "row_outcomes": [
                {
                    "frame_index": int(arrays["frame_index"][frame]),
                    "transition_id": str(arrays["transition_id"][frame]),
                    "transition_outcome": str(arrays["transition_outcome"][frame]),
                    "terminated": bool(arrays["terminated"][frame]),
                    "success": bool(arrays["success"][frame]),
                }
                for frame in range(frames)
            ],
            "image_join": {
                "key": ["obs_id", "scene_state_snapshot_sha256", "camera_role"],
                "positional_join": False,
                "verified_identities": len(images),
                "required_identity_fields": list(IMAGE_IDENTITY_FIELDS),
            },
            "projection_image_join_ledger": join_ledger,
            "qa": {**qa, "identical_rgb_digest_roles": identical_digest_roles},
            "files": _dataset_file_digests(temporary),
        }
        manifest["manifest_sha256"] = _canonical_sha256(manifest)
        _write_json(temporary / MATERIALIZATION_MANIFEST, manifest)
        verify_materialization_manifest(temporary)
        _publish_directory(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return verify_materialization_manifest(target)


def _portable_root(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("portable root must be NAME=PATH")
    name, raw_path = value.split("=", 1)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name):
        raise argparse.ArgumentTypeError(f"invalid portable root name: {name!r}")
    if not raw_path:
        raise argparse.ArgumentTypeError("portable root path is empty")
    return name, Path(raw_path).expanduser().resolve()


def _portable_root_map(values: Iterable[tuple[str, Path]]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for name, path in values:
        if name in roots:
            raise MaterializationError(f"portable root {name!r} was supplied more than once")
        roots[name] = path
    if not roots:
        raise MaterializationError("at least one --portable-root NAME=PATH is required")
    return roots


def _add_extract_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--episode")
    parser.add_argument(
        "--portable-root",
        action="append",
        default=[],
        type=_portable_root,
        metavar="NAME=PATH",
        help="repeat for every portable asset-closure root",
    )


def _add_materialize_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--replay-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--task-id", required=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract", help="verify HDF and emit a projection bundle")
    _add_extract_arguments(extract)
    materialize = subparsers.add_parser(
        "materialize", help="join replay RGB and create a LeRobotDataset v3"
    )
    _add_materialize_arguments(materialize)
    orchestrate = subparsers.add_parser(
        "orchestrate", help="run extraction in an explicit Python, then materialize here"
    )
    orchestrate.add_argument("--extract-python", type=Path, required=True)
    orchestrate.add_argument("--recording", type=Path, required=True)
    orchestrate.add_argument("--replay-report", type=Path, required=True)
    orchestrate.add_argument("--output", type=Path, required=True)
    orchestrate.add_argument("--repo-id", required=True)
    orchestrate.add_argument("--task-id", required=True)
    orchestrate.add_argument("--episode")
    orchestrate.add_argument(
        "--portable-root",
        action="append",
        default=[],
        type=_portable_root,
        metavar="NAME=PATH",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "extract":
        result = extract_projection(
            recording=args.recording,
            output=args.output,
            portable_roots=_portable_root_map(args.portable_root),
            episode=args.episode,
        )
    elif args.command == "materialize":
        result = materialize_projection(
            bundle=args.bundle,
            replay_report=args.replay_report,
            output=args.output,
            repo_id=args.repo_id,
            task_id=args.task_id,
        )
    else:
        roots = _portable_root_map(args.portable_root)
        # Do not resolve this path: venv ``python`` is commonly a symlink to the
        # base interpreter, and resolving it would silently discard the venv.
        extract_python = args.extract_python.expanduser()
        if not extract_python.is_absolute():
            extract_python = Path.cwd() / extract_python
        if not extract_python.is_file():
            raise MaterializationError(f"extract interpreter does not exist: {extract_python}")
        with tempfile.TemporaryDirectory(prefix="isaac-vr-projection-") as temp:
            bundle = Path(temp) / "bundle"
            command = [
                str(extract_python),
                str(Path(__file__).resolve()),
                "extract",
                "--recording",
                str(args.recording),
                "--output",
                str(bundle),
            ]
            if args.episode is not None:
                command.extend(("--episode", args.episode))
            for name, path in roots.items():
                command.extend(("--portable-root", f"{name}={path}"))
            subprocess.run(command, check=True)
            result = materialize_projection(
                bundle=bundle,
                replay_report=args.replay_report,
                output=args.output,
                repo_id=args.repo_id,
                task_id=args.task_id,
            )
    print("ISAAC_VR_LEROBOT_RESULT=" + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
