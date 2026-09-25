"""CPU checks for demo-level admission and immutable segment mapping."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
import yaml

from tools import isaac_vr_admission as admission
from tools import isaac_vr_lerobot_materialize as materialize
from tools.isaac_vr_replay import verify_recording_artifact
from test_isaac_vr_replay import _artifact


def test_direct_cli_exposes_evaluate_and_verify():
    result = subprocess.run(
        [sys.executable, str(Path(admission.__file__)), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "evaluate" in result.stdout and "verify" in result.stdout


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _make_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, count: int = 1):
    demo_id = "demo_000042"
    source_entries = []
    projections = []
    outputs = []
    artifacts = []
    originals = []
    for index in range(count):
        episode_id = f"episode_{index:06d}"
        source_dir = tmp_path / "sources" / episode_id
        source_dir.mkdir(parents=True)
        recording = _artifact(source_dir)
        manifest_path = source_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["transition_schema"] = admission.ROW_SCHEMA
        manifest["committed_frames"] = 1
        manifest["session_metadata"].update(
            {
                "episode_id": episode_id,
                "source_profile": admission.SOURCE_PROFILE,
                "task": "dual_cube_to_matching_plates",
                "execution_profile": "isaac_vr_record",
                "runtime_config_sha256": "c" * 64,
                "d0_revision": "processor-v3",
                "environment_pins": {"isaac": "6.1"},
                "demo_id": demo_id,
            }
        )
        _write(manifest_path, manifest)
        marker_path = source_dir / "recording_state.json"
        marker = json.loads(marker_path.read_text())
        marker["committed_frames"] = 1
        _write(marker_path, marker)
        artifact = verify_recording_artifact(recording, portable_roots={"recording": source_dir})
        artifacts.append(artifact)
        originals.append((recording, source_dir, manifest))
        visual = artifact.visual_provenance
        source = {
            "recording": str(recording),
            "recording_sha256": artifact.hdf5_sha256,
            "episode": "episode_00000",
            "episode_id": episode_id,
            "run_id": "run",
            "session_id": "session",
            "source_profile": admission.SOURCE_PROFILE,
            "task": "dual_cube_to_matching_plates",
            "execution_profile": "isaac_vr_record",
            "outcome": "operator_stopped",
            "stage_snapshot_sha256": artifact.snapshot_sha256,
            "asset_closure_sha256": artifact.asset_closure_sha256,
            "visual_provenance_sha256": artifact.visual_provenance_sha256,
            "terminal_successor_sha256": artifact.terminal_successor_sha256,
            "visual_identity": {
                "camera_roles": {
                    item["role"]: {
                        "prim_path": item["prim_path"],
                        "camera_configuration_sha256": item["camera_configuration_sha256"],
                    }
                    for item in visual["camera_roles"]
                },
                "renderer_configuration_sha256": visual["renderer"][
                    "renderer_configuration_sha256"
                ],
                "materialization_revision": visual["materialization"]["materialization_revision"],
            },
        }
        state = np.arange(14, dtype=np.float32).reshape(1, 14)
        snapshot_hash = "a" * 64
        arrays = {
            "frame_index": np.asarray([0], dtype=np.int64),
            "observation_state": state,
            "action": state + 1,
            "obs_id": np.asarray([f"obs:{index}"]),
            "scene_state_snapshot_id": np.asarray([f"snapshot:{index}"]),
            "scene_state_snapshot_sha256": np.asarray([snapshot_hash]),
            "transition_id": np.asarray([f"transition:{index}"]),
            "transition_outcome": np.asarray(["advanced"]),
            "terminated": np.asarray([0], dtype=np.uint8),
            "success": np.asarray([0], dtype=np.uint8),
            "next_obs_id": np.asarray([f"obs:{index + 1}"]),
            "successor_observation_state": state + 2,
        }
        projection = tmp_path / "projections" / episode_id
        materialize._write_projection_bundle(projection, arrays, source)
        bundle, _ = materialize.verify_projection_bundle(projection)
        projections.append(projection)
        output = tmp_path / "outputs" / episode_id
        output.mkdir(parents=True)
        (output / "data.bin").write_bytes(b"LeRobot test fixture")
        report = tmp_path / "replays" / f"{episode_id}.json"
        _write(report, {"schema": materialize.REPLAY_SCHEMA, "fixture": episode_id})
        material_manifest = {
            "schema": materialize.MATERIALIZATION_SCHEMA,
            "conversion_revision": materialize.CONVERSION_REVISION,
            "frames": 1,
            "episodes": 1,
            "fps": 30,
            "task_id": source["task"],
            "source": {
                **source,
                "projection_manifest_sha256": bundle["manifest_sha256"],
                "projection_payload_sha256": bundle["projection"]["sha256"],
                "replay_report": str(report),
                "replay_report_sha256": admission._sha(report),
                "replay_schema": materialize.REPLAY_SCHEMA,
            },
            "admission": {
                "dataset_admissible": False,
                "blocking_reasons": ["requires_demo_admission_decision"],
            },
            "qa": {
                "all_frames_read": 1,
                "all_video_frames_decoded": 3,
                "dataloader_frames": 1,
                "dataloader_batches": 1,
            },
            "image_join": {"verified_identities": 3},
            "row_outcomes": [
                {
                    "frame_index": 0,
                    "transition_id": f"transition:{index}",
                    "transition_outcome": "advanced",
                    "terminated": False,
                    "success": False,
                }
            ],
            "projection_image_join_ledger": [
                {
                    "frame_index": 0,
                    "obs_id": f"obs:{index}",
                    "transition_id": f"transition:{index}",
                    "scene_state_snapshot_id": f"snapshot:{index}",
                    "scene_state_snapshot_sha256": snapshot_hash,
                    "observation_state_sha256": hashlib.sha256(
                        state.astype("<f4").tobytes()
                    ).hexdigest(),
                    "action_sha256": hashlib.sha256(
                        (state + 1).astype("<f4").tobytes()
                    ).hexdigest(),
                    "images": {role: {"rgb_sha256": "b" * 64} for role in materialize.CAMERA_ROLES},
                }
            ],
            "files": [
                {
                    "path": "data.bin",
                    "size_bytes": 20,
                    "sha256": admission._sha(output / "data.bin"),
                }
            ],
        }
        material_manifest["files"][0]["size_bytes"] = (output / "data.bin").stat().st_size
        material_manifest["manifest_sha256"] = materialize._canonical_sha256(material_manifest)
        _write(output / materialize.MATERIALIZATION_MANIFEST, material_manifest)
        materialize.verify_materialization_manifest(output)
        outputs.append(output)
        source_entries.append({"episode_id": episode_id, "output_dir": str(source_dir)})
    metadata = {
        "schema": admission.DEMO_SCHEMA,
        "demo_id": demo_id,
        "save_classification": "saved",
        "task_outcome": "success",
        "lifecycle_disposition": "saved_and_classified",
        "source_profile": admission.SOURCE_PROFILE,
        "source_manifest_schema": "piper_x_isaac_vr_recording_manifest_v2",
        "committed_row_schema": admission.ROW_SCHEMA,
        "technical_episodes": source_entries,
    }
    demo = tmp_path / "saved_demos" / f"{demo_id}.json"
    _write(demo, metadata)

    # The existing image-join verifier has independent strict replay/RGB tests.
    # Here the seam supplies already verified camera identities to exercise the
    # demo admission, mapping, and physical evidence boundary without video I/O.
    def verified_images(_path, bundle, arrays):
        images = {}
        for role in materialize.CAMERA_ROLES:
            images[
                (str(arrays["obs_id"][0]), str(arrays["scene_state_snapshot_sha256"][0]), role)
            ] = {"rgb_sha256": "b" * 64}
        return images, {"schema": materialize.REPLAY_SCHEMA}

    monkeypatch.setattr(admission, "_validated_image_join", verified_images)
    binding = {
        "task_id": "dual_cube_to_matching_plates",
        "source_profile": admission.SOURCE_PROFILE,
        "execution_profile": "isaac_vr_record",
        "runtime_config_sha256": "c" * 64,
        "processor_revision": "processor-v3",
        "environment_pins_sha256": admission._digest_json({"isaac": "6.1"}),
    }
    physical = tmp_path / "evidence" / "physical.json"
    record = {
        "schema": admission.PHYSICAL_SCHEMA,
        "result": "pass",
        "evidence_id": "test_physical_quest",
        "artifact_id": "test_physical_record",
        "binding": binding,
    }
    _write(physical, record)
    contract_path = tmp_path / "configs" / "resolved_contract.yaml"
    contract_path.parent.mkdir()
    contract = {
        "gates": {"S2": {"evidence_ids": ["test_physical_quest"]}},
        "evidence": {
            "test_physical_quest": {
                "kind": "human_gate",
                "status": "pass",
                "artifact_ids": ["test_physical_record"],
            }
        },
        "artifacts": {
            "test_physical_record": {
                "path": str(physical.relative_to(tmp_path)),
                "sha256": admission._sha(physical),
            }
        },
    }
    contract_path.write_text(yaml.safe_dump(contract))
    return {
        "demo": demo,
        "projections": projections,
        "materializations": outputs,
        "portable_roots": {"recording": tmp_path / "sources"},
        "physical_qualification": physical,
        "contract_path": contract_path,
    }


def test_success_is_blocked_only_by_missing_physical(tmp_path, monkeypatch):
    case = _make_case(tmp_path, monkeypatch)
    case["physical_qualification"] = None
    result = admission.evaluate_demo_admission(**case)
    assert result["admitted"] is False
    assert result["blocking_reasons"] == ["physical_qualification_missing"]
    assert result["ordered_source_technical_episodes"][0]["source_outcome"] == "operator_stopped"
    result["admitted"] = True
    with pytest.raises(admission.AdmissionError, match="differs from verified inputs"):
        admission.publish_decision(
            result,
            tmp_path / "manual-true.json",
            portable_roots=case["portable_roots"],
            contract_path=case["contract_path"],
        )


def test_positive_operator_stopped_and_multisegment_mapping(tmp_path, monkeypatch):
    case = _make_case(tmp_path, monkeypatch, count=3)
    result = admission.evaluate_demo_admission(**case)
    assert result["admitted"] is True
    assert result["blocking_reasons"] == []
    assert [x["episode_id"] for x in result["ordered_materialized_outputs"]] == [
        f"episode_{i:06d}" for i in range(3)
    ]
    assert all(
        x["source_outcome"] == "operator_stopped"
        for x in result["ordered_source_technical_episodes"]
    )


def test_legacy_materialization_blockers_do_not_override_human_success(tmp_path, monkeypatch):
    case = _make_case(tmp_path, monkeypatch)
    manifest_path = case["materializations"][0] / materialize.MATERIALIZATION_MANIFEST
    manifest = json.loads(manifest_path.read_text())
    manifest["admission"]["blocking_reasons"] = [
        "source_admission_requires_external_physical_vr_qualification",
        "source_outcome_is_not_success",
    ]
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = materialize._canonical_sha256(manifest)
    _write(manifest_path, manifest)
    assert admission.evaluate_demo_admission(**case)["admitted"] is True


@pytest.mark.parametrize("outcome", ["failure", "incomplete"])
def test_human_outcome_blocks(tmp_path, monkeypatch, outcome):
    case = _make_case(tmp_path, monkeypatch)
    metadata = json.loads(case["demo"].read_text())
    metadata["task_outcome"] = outcome
    _write(case["demo"], metadata)
    result = admission.evaluate_demo_admission(**case)
    assert not result["admitted"]
    assert result["blocking_reasons"] == [f"human_task_outcome_is_{outcome}"]


@pytest.mark.parametrize(
    "change",
    ["missing", "reorder", "duplicate", "wrong_digest", "wrong_demo", "corrupt_materialization"],
)
def test_invalid_mapping_or_artifact_fails_closed(tmp_path, monkeypatch, change):
    case = _make_case(tmp_path, monkeypatch, count=3)
    if change == "missing":
        case["materializations"] = case["materializations"][:-1]
    elif change == "reorder":
        case["materializations"] = list(reversed(case["materializations"]))
    elif change == "duplicate":
        case["materializations"][1] = case["materializations"][0]
    elif change == "wrong_digest":
        with (tmp_path / "sources/episode_000001/session.hdf5").open("ab") as stream:
            stream.write(b"changed")
    elif change == "wrong_demo":
        manifest_path = tmp_path / "sources/episode_000001/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["session_metadata"]["demo_id"] = "another_demo"
        _write(manifest_path, manifest)
    else:
        with (case["materializations"][0] / "data.bin").open("ab") as stream:
            stream.write(b"corrupt")
    with pytest.raises((admission.AdmissionError, ValueError, materialize.MaterializationError)):
        admission.evaluate_demo_admission(**case)


@pytest.mark.parametrize(
    "field,value",
    [("task_id", "other"), ("source_profile", "other"), ("runtime_config_sha256", "0" * 64)],
)
def test_incompatible_physical_binding_blocks(tmp_path, monkeypatch, field, value):
    case = _make_case(tmp_path, monkeypatch)
    physical = case["physical_qualification"]
    record = json.loads(physical.read_text())
    record["binding"][field] = value
    _write(physical, record)
    contract = yaml.safe_load(case["contract_path"].read_text())
    contract["artifacts"]["test_physical_record"]["sha256"] = admission._sha(physical)
    case["contract_path"].write_text(yaml.safe_dump(contract))
    result = admission.evaluate_demo_admission(**case)
    assert result["blocking_reasons"] == ["physical_qualification_incompatible"]


def test_unregistered_physical_pass_is_invalid(tmp_path, monkeypatch):
    case = _make_case(tmp_path, monkeypatch)
    contract = yaml.safe_load(case["contract_path"].read_text())
    contract["gates"]["S2"]["evidence_ids"] = []
    case["contract_path"].write_text(yaml.safe_dump(contract))
    with pytest.raises(admission.AdmissionError, match="registered S2 human PASS"):
        admission.evaluate_demo_admission(**case)


def test_published_decision_detects_later_manifest_change(tmp_path, monkeypatch):
    case = _make_case(tmp_path, monkeypatch)
    result = admission.evaluate_demo_admission(**case)
    decision = tmp_path / "decisions" / "admission.json"
    admission.publish_decision(
        result,
        decision,
        portable_roots=case["portable_roots"],
        contract_path=case["contract_path"],
    )
    assert (
        admission.verify_decision(
            decision, portable_roots=case["portable_roots"], contract_path=case["contract_path"]
        )
        == result
    )
    with pytest.raises(FileExistsError):
        admission.publish_decision(
            result,
            decision,
            portable_roots=case["portable_roots"],
            contract_path=case["contract_path"],
        )
    manifest = case["materializations"][0] / materialize.MATERIALIZATION_MANIFEST
    manifest.write_text(manifest.read_text() + " ")
    with pytest.raises(admission.AdmissionError, match="no longer matches"):
        admission.verify_decision(
            decision, portable_roots=case["portable_roots"], contract_path=case["contract_path"]
        )
