"""Fail-closed projection and LeRobot materialization tests."""

from __future__ import annotations

import copy
import gc
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import weakref

import numpy as np
from PIL import Image
import pytest

from tools import isaac_vr_lerobot_materialize as materialize


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_direct_cli_bootstraps_repository_package_imports() -> None:
    result = subprocess.run(
        [sys.executable, str(Path(materialize.__file__).resolve()), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "orchestrate" in result.stdout


def _source() -> dict[str, object]:
    return {
        "recording": "/immutable/session.hdf5",
        "recording_sha256": "1" * 64,
        "episode": "episode_00000",
        "episode_id": "episode_000000",
        "run_id": "run",
        "session_id": "session",
        "source_profile": "isaac_human_vr_offline_rgb_v1",
        "task": "dual_cube_to_matching_plates",
        "outcome": "operator_stopped",
        "execution_profile": "isaac_vr_record_no_client_lifecycle_smoke",
        "stage_snapshot_sha256": "2" * 64,
        "asset_closure_sha256": "3" * 64,
        "visual_provenance_sha256": "4" * 64,
        "terminal_successor_sha256": "5" * 64,
        "visual_identity": {
            "camera_roles": {
                role: {
                    "prim_path": f"/World/{role}",
                    "camera_configuration_sha256": ("8", "9", "a")[index] * 64,
                }
                for index, role in enumerate(materialize.CAMERA_ROLES)
            },
            "renderer_configuration_sha256": "b" * 64,
            "materialization_revision": "piper_x_offline_rgb_materializer_v1",
        },
    }


def _arrays(frames: int = 2) -> dict[str, np.ndarray]:
    state = np.stack([np.arange(14, dtype=np.float32) + frame * 100 for frame in range(frames)])
    return {
        "frame_index": np.arange(frames, dtype=np.int64),
        "observation_state": state,
        "action": state + np.float32(1000),
        "obs_id": np.asarray([f"obs:{frame}" for frame in range(frames)], dtype=np.str_),
        "scene_state_snapshot_id": np.asarray(
            [f"snapshot:{frame}" for frame in range(frames)], dtype=np.str_
        ),
        "scene_state_snapshot_sha256": np.asarray(
            [hashlib.sha256(f"snapshot:{frame}".encode()).hexdigest() for frame in range(frames)],
            dtype=np.str_,
        ),
        "transition_id": np.asarray(
            [f"transition:{frame}" for frame in range(frames)], dtype=np.str_
        ),
        "transition_outcome": np.asarray(["advanced"] * frames, dtype=np.str_),
        "terminated": np.zeros(frames, dtype=np.uint8),
        "success": np.zeros(frames, dtype=np.uint8),
        "next_obs_id": np.asarray([f"obs:{frame + 1}" for frame in range(frames)], dtype=np.str_),
        "successor_observation_state": state + np.float32(1),
    }


def _bundle(
    tmp_path: Path,
    frames: int = 2,
    source_profile: str = "isaac_human_vr_offline_rgb_v1",
) -> tuple[Path, dict[str, np.ndarray]]:
    arrays = _arrays(frames)
    path = tmp_path / "bundle"
    source = _source()
    source["source_profile"] = source_profile
    materialize._write_projection_bundle(path, arrays, source)
    return path, arrays


def test_clutch_profile_projection_preserves_exact_row_count_and_order(tmp_path: Path) -> None:
    arrays = _arrays(3)
    source = _source()
    source["source_profile"] = "isaac_human_vr_offline_rgb_v2"
    bundle = tmp_path / "clutch_profile"
    materialize._write_projection_bundle(bundle, arrays, source)
    manifest, loaded = materialize.verify_projection_bundle(bundle)
    assert manifest["source"]["source_profile"] == "isaac_human_vr_offline_rgb_v2"
    assert manifest["frames"] == 3
    np.testing.assert_array_equal(loaded["frame_index"], [0, 1, 2])
    np.testing.assert_array_equal(loaded["action"], arrays["action"])


def _report(tmp_path: Path, arrays: dict[str, np.ndarray]) -> Path:
    images = tmp_path / "rgb"
    images.mkdir()
    renders: list[dict[str, object]] = []
    for frame in range(len(arrays["frame_index"])):
        for role_index, role in enumerate(materialize.CAMERA_ROLES):
            # Every stream and every frame has a distinguishable RGB digest.
            value = (20 + role_index * 70 + frame * 15) % 256
            pixels = np.full(materialize.IMAGE_SHAPE, value, dtype=np.uint8)
            path = images / f"{frame}-{role}.png"
            Image.fromarray(pixels).save(path)
            digest = _sha256(path)
            renders.append(
                {
                    "frame": frame,
                    "role": role,
                    "camera_role": role,
                    "path": str(path),
                    "dtype": "uint8",
                    "shape": list(materialize.IMAGE_SHAPE),
                    "sha256": digest,
                    "rgb_sha256": digest,
                    "obs_id": str(arrays["obs_id"][frame]),
                    "scene_state_snapshot_id": str(arrays["scene_state_snapshot_id"][frame]),
                    "scene_state_snapshot_sha256": str(
                        arrays["scene_state_snapshot_sha256"][frame]
                    ),
                    "camera_prim_path": f"/World/{role}",
                    "camera_configuration_sha256": ("8", "9", "a")[role_index] * 64,
                    "renderer_configuration_sha256": "b" * 64,
                    "stage_snapshot_sha256": _source()["stage_snapshot_sha256"],
                    "asset_closure_sha256": _source()["asset_closure_sha256"],
                    "materialization_revision": "piper_x_offline_rgb_materializer_v1",
                }
            )
    # Deliberately destroy list/frame order. Immutable identity must own the join.
    renders.reverse()
    report = {
        "schema": materialize.REPLAY_SCHEMA,
        "recording_sha256": _source()["recording_sha256"],
        "stage_snapshot_sha256": _source()["stage_snapshot_sha256"],
        "asset_closure_sha256": _source()["asset_closure_sha256"],
        "visual_provenance_sha256": _source()["visual_provenance_sha256"],
        "terminal_successor_sha256": _source()["terminal_successor_sha256"],
        "episode": _source()["episode"],
        "frames_applied": len(arrays["frame_index"]),
        "physics_callbacks": 0,
        "strict_policy": True,
        "native_action_replay": False,
        "camera_paths": {role: f"/World/{role}" for role in materialize.CAMERA_ROLES},
        "renders": renders,
        "d0": {"observation_ids": arrays["obs_id"].tolist()},
    }
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _rewrite_report(path: Path, mutation) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    mutation(report)
    path.write_text(json.dumps(report), encoding="utf-8")


def test_projection_bundle_is_self_hashed_and_rejects_payload_mutation(tmp_path: Path) -> None:
    bundle, arrays = _bundle(tmp_path)
    manifest, loaded = materialize.verify_projection_bundle(bundle)

    assert manifest["schema_fingerprint_sha256"] == materialize.SCHEMA_FINGERPRINT
    np.testing.assert_array_equal(loaded["observation_state"], arrays["observation_state"])

    with (bundle / materialize.PROJECTION_FILE).open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(materialize.MaterializationError, match="payload digest mismatch"):
        materialize.verify_projection_bundle(bundle)


def test_projection_rejects_nonfinite_training_values(tmp_path: Path) -> None:
    arrays = _arrays()
    arrays["action"][0, 0] = np.nan
    with pytest.raises(materialize.MaterializationError, match="NaN or Inf"):
        materialize._write_projection_bundle(tmp_path / "bundle", arrays, _source())
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda report: report.update(physics_callbacks=1), "physics callbacks"),
        (
            lambda report: report["renders"].append(copy.deepcopy(report["renders"][0])),
            "duplicates immutable image identity",
        ),
        (lambda report: report["renders"].pop(), "coverage mismatch"),
        (
            lambda report: report["renders"][0].update(scene_state_snapshot_id="wrong"),
            "mismatched snapshot ID",
        ),
        (
            lambda report: report["renders"][0].update(stage_snapshot_sha256="f" * 64),
            "wrong stage snapshot",
        ),
        (
            lambda report: report["renders"][0].update(camera_configuration_sha256="c" * 64),
            "wrong camera configuration",
        ),
        (
            lambda report: report["renders"][0].update(renderer_configuration_sha256="c" * 64),
            "wrong renderer configuration",
        ),
        (
            lambda report: report["renders"][0].update(materialization_revision="substituted"),
            "wrong materialization revision",
        ),
    ],
)
def test_image_join_fails_closed_without_publishing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation, message: str
) -> None:
    bundle, arrays = _bundle(tmp_path)
    report = _report(tmp_path, arrays)
    _rewrite_report(report, mutation)
    output = tmp_path / "dataset"
    monkeypatch.setattr(
        materialize, "_load_rgb", lambda *_: pytest.fail("invalid join decoded RGB")
    )

    with pytest.raises(materialize.MaterializationError, match=message):
        materialize.materialize_projection(
            bundle=bundle,
            replay_report=report,
            output=output,
            repo_id="tests/isaac-vr-invalid",
            task_id="dual_cube_to_matching_plates",
        )

    assert not output.exists()


@pytest.mark.parametrize(
    "source_profile", ["isaac_human_vr_offline_rgb_v1", "isaac_human_vr_offline_rgb_v2"]
)
def test_materializes_v3_videos_and_full_reads_every_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_profile: str
) -> None:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    original_add = LeRobotDataset.add_frame
    staged_frames = 0

    def assert_synchronous_staging(self, sample: dict[str, object]) -> None:
        nonlocal staged_frames
        original_add(self, sample)
        staged_frames += 1
        for role in materialize.CAMERA_ROLES:
            staged = self.writer.episode_buffer[f"observation.images.{role}"][-1]
            assert isinstance(staged, str)
            assert Path(staged).is_file()

    monkeypatch.setattr(LeRobotDataset, "add_frame", assert_synchronous_staging)
    bundle, arrays = _bundle(tmp_path, source_profile=source_profile)
    report = _report(tmp_path, arrays)
    output = tmp_path / "dataset"
    task = "Move both cubes to their matching plates."

    result = materialize.materialize_projection(
        bundle=bundle,
        replay_report=report,
        output=output,
        repo_id="tests/isaac-vr-materialized",
        task_id="dual_cube_to_matching_plates",
    )

    assert result["frames"] == 2
    assert staged_frames == 2
    assert result["schema_fingerprint_sha256"] == materialize.SCHEMA_FINGERPRINT
    assert result["task_id"] == "dual_cube_to_matching_plates"
    assert result["task_label"] == task
    assert result["task_label_revision"] == materialize.TASK_LABEL_REVISION
    assert result["admission"] == {
        "dataset_admissible": False,
        "blocking_reasons": [
            "source_admission_requires_external_physical_vr_qualification",
            "source_outcome_is_not_success",
            "source_execution_profile_is_not_physical_human_vr",
        ],
    }
    assert result["image_join"] == {
        "key": ["obs_id", "scene_state_snapshot_sha256", "camera_role"],
        "positional_join": False,
        "verified_identities": 6,
        "required_identity_fields": list(materialize.IMAGE_IDENTITY_FIELDS),
    }
    assert result["qa"] == {
        "all_frames_read": 2,
        "all_video_frames_decoded": 6,
        "dataloader_batches": 1,
        "dataloader_frames": 2,
        "identical_rgb_digest_roles": [],
    }
    assert len(result["projection_image_join_ledger"]) == 2
    first_ledger = result["projection_image_join_ledger"][0]
    assert first_ledger["obs_id"] == "obs:0"
    assert set(first_ledger["images"]) == set(materialize.CAMERA_ROLES)
    assert first_ledger["images"]["scene"]["source_path"].endswith("0-scene.png")
    assert materialize.verify_materialization_manifest(output) == result
    assert len(list(output.glob("videos/*/chunk-000/file-000.mp4"))) == 3

    loaded = LeRobotDataset("tests/isaac-vr-materialized", root=output, video_backend="pyav")
    np.testing.assert_array_equal(
        loaded[0]["observation.state"].numpy(), arrays["observation_state"][0]
    )
    np.testing.assert_array_equal(loaded[1]["action"].numpy(), arrays["action"][1])
    assert loaded[0]["task"] == task
    # The reverse-ordered report still joined frame 0 to its darker identity.
    assert (
        loaded[0]["observation.images.scene"].mean().item()
        < loaded[1]["observation.images.scene"].mean().item()
    )


def test_task_id_cannot_relabel_recorded_episode(tmp_path: Path) -> None:
    bundle, arrays = _bundle(tmp_path)
    report = _report(tmp_path, arrays)

    with pytest.raises(materialize.MaterializationError, match="does not match recorded task"):
        materialize.materialize_projection(
            bundle=bundle,
            replay_report=report,
            output=tmp_path / "dataset",
            repo_id="tests/task-substitution",
            task_id="different_task",
        )


def test_metadata_join_validates_all_images_without_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, arrays = _bundle(tmp_path, frames=4)
    report = _report(tmp_path, arrays)
    manifest, loaded = materialize.verify_projection_bundle(bundle)
    monkeypatch.setattr(materialize, "_load_rgb", lambda *_: pytest.fail("join decoded RGB"))

    joined, _ = materialize._validated_image_join(report, manifest, loaded)

    assert len(joined) == 12
    for entry in joined.values():
        assert "image" not in entry
        assert not any(isinstance(value, np.ndarray) for value in entry.values())
        assert Path(entry["path"]).is_file()
        assert entry["rgb_sha256"] == _sha256(Path(entry["path"]))
        with pytest.raises(TypeError):
            entry["path"] = "changed"


def test_frame_decode_is_on_demand_and_materializer_releases_previous_rgb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, arrays = _bundle(tmp_path, frames=5)
    report = _report(tmp_path, arrays)
    manifest, loaded = materialize.verify_projection_bundle(bundle)
    joined, _ = materialize._validated_image_join(report, manifest, loaded)
    original = materialize._load_rgb
    decoded: list[weakref.ReferenceType[np.ndarray]] = []
    calls: list[str] = []

    def observed_load(path: Path, digest: str) -> np.ndarray:
        image = original(path, digest)
        decoded.append(weakref.ref(image))
        calls.append(path.name)
        return image

    class NonRetainingDataset:
        def add_frame(self, sample: dict[str, object]) -> None:
            assert sum(isinstance(value, np.ndarray) for value in sample.values()) == 5

    monkeypatch.setattr(materialize, "_load_rgb", observed_load)
    assert calls == []
    dataset = NonRetainingDataset()
    for frame in range(5):
        materialize._add_projection_frame(dataset, frame, loaded, joined, "task")
        assert len(calls) == (frame + 1) * 3
        assert {name.split("-")[0] for name in calls} == {str(index) for index in range(frame + 1)}
        gc.collect()
        assert all(reference() is None for reference in decoded)


def test_image_mutation_between_join_and_consume_fails(
    tmp_path: Path
) -> None:
    bundle, arrays = _bundle(tmp_path)
    report = _report(tmp_path, arrays)
    manifest, loaded = materialize.verify_projection_bundle(bundle)
    joined, _ = materialize._validated_image_join(report, manifest, loaded)
    entry = joined[("obs:0", str(arrays["scene_state_snapshot_sha256"][0]), "scene")]
    Path(entry["path"]).write_bytes(b"changed")

    class UnusedDataset:
        def add_frame(self, sample: dict[str, object]) -> None:
            pytest.fail("corrupt frame reached LeRobot")

    with pytest.raises(materialize.MaterializationError, match="digest mismatch"):
        materialize._add_projection_frame(UnusedDataset(), 0, loaded, joined, "task")


def test_image_mutation_during_decode_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, arrays = _bundle(tmp_path)
    report = _report(tmp_path, arrays)
    manifest, loaded = materialize.verify_projection_bundle(bundle)
    joined, _ = materialize._validated_image_join(report, manifest, loaded)
    entry = joined[("obs:0", str(arrays["scene_state_snapshot_sha256"][0]), "left_wrist")]
    path = Path(entry["path"])
    original = materialize._sha256_stable
    calls = 0

    def mutating_hash(candidate: Path) -> str:
        nonlocal calls
        if candidate == path:
            calls += 1
            if calls == 2:
                path.write_bytes(b"changed after decode")
        return original(candidate)

    monkeypatch.setattr(materialize, "_sha256_stable", mutating_hash)
    with pytest.raises(materialize.MaterializationError, match="changed while it was decoded"):
        materialize._load_rgb(path, entry["rgb_sha256"])


@pytest.mark.parametrize("failure", ["missing_image", "add_frame"])
def test_late_frame_failure_does_not_publish_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    bundle, arrays = _bundle(tmp_path, frames=3)
    report = _report(tmp_path, arrays)
    output = tmp_path / "dataset"
    if failure == "missing_image":
        original_load = materialize._load_rgb

        def remove_later_image(path: Path, digest: str) -> np.ndarray:
            if path.name == "1-scene.png":
                path.unlink()
            return original_load(path, digest)

        monkeypatch.setattr(materialize, "_load_rgb", remove_later_image)
        expected = "file is missing"
    else:
        original_add = LeRobotDataset.add_frame
        calls = 0

        def failing_add(self, sample: dict[str, object]) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected add_frame failure")
            original_add(self, sample)

        monkeypatch.setattr(LeRobotDataset, "add_frame", failing_add)
        expected = "injected add_frame failure"

    with pytest.raises((materialize.MaterializationError, RuntimeError), match=expected):
        materialize.materialize_projection(
            bundle=bundle,
            replay_report=report,
            output=output,
            repo_id="tests/late-frame-failure",
            task_id="dual_cube_to_matching_plates",
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".dataset.tmp-*"))


def test_replay_report_mutation_during_materialization_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, arrays = _bundle(tmp_path)
    report = _report(tmp_path, arrays)
    original = materialize._load_rgb
    calls = 0

    def mutating_load(path: Path, digest: str) -> np.ndarray:
        nonlocal calls
        result = original(path, digest)
        calls += 1
        if calls == 1:
            report.write_text(report.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return result

    monkeypatch.setattr(materialize, "_load_rgb", mutating_load)
    output = tmp_path / "dataset"
    with pytest.raises(materialize.MaterializationError, match="report changed"):
        materialize.materialize_projection(
            bundle=bundle,
            replay_report=report,
            output=output,
            repo_id="tests/report-mutation",
            task_id="dual_cube_to_matching_plates",
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".dataset.tmp-*"))


def test_static_identical_rgb_is_qa_flag_not_geometry_failure(tmp_path: Path) -> None:
    bundle, arrays = _bundle(tmp_path)
    report_path = _report(tmp_path, arrays)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for role in materialize.CAMERA_ROLES:
        first = next(item for item in report["renders"] if item["role"] == role and item["frame"] == 0)
        second = next(item for item in report["renders"] if item["role"] == role and item["frame"] == 1)
        Path(second["path"]).write_bytes(Path(first["path"]).read_bytes())
        second["sha256"] = first["sha256"]
        second["rgb_sha256"] = first["rgb_sha256"]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    bundle_manifest, loaded = materialize.verify_projection_bundle(bundle)
    joined, verified = materialize._validated_image_join(report_path, bundle_manifest, loaded)
    assert len(joined) == 6
    assert verified["_identical_rgb_digest_roles"] == list(materialize.CAMERA_ROLES)
