"""Governance checks for the selected Isaac snapshot/offline-RGB recording contract."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from tools.validate_resolved_contract import validate_dataset_contract, validate_schema


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs" / "resolved_contract.yaml"
SCHEMA_PATH = ROOT / "configs" / "resolved_contract.schema.json"


def contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_offline_rgb_profile_is_additive_selected_and_not_accepted_evidence() -> None:
    data = contract()
    temporal = data["dataset"]["temporal_semantics"]
    profiles = temporal["source_profiles"]

    # The accepted D0 live-camera profile is retained byte-for-byte in meaning;
    # the new D1 path is additive and has no inherited runtime acceptance.
    assert profiles["isaac_human_vr_v4"] == {
        "runtime": "isaac",
        "source_classes": ["human_vr"],
        "physical_timing_required": False,
        "required_source_identities": [
            "simulation.state_generation",
            "camera.left_wrist",
            "camera.right_wrist",
            "camera.scene",
            "xr.device_io_update",
            "xr.submitted_frame",
            "xr.returned_frame",
            "xr.resolved_input",
        ],
        "source_epoch_semantics": "XR session epoch",
        "tracking_valid_required": True,
        "persistence_call_phase": "after_successful_transition_and_successor_observation",
        "source_action": (
            "post-DifferentialIK desired joint target BEFORE native clipping, "
            "converted to canonical deg/mm"
        ),
        "runtime_binding_status": "pending_D1",
        "host_timestamps": "optional_QA_provenance_not_XR_physical_acquisition_time",
        "openxr_query_time": "optional_when_explicitly_exposed_by_source",
    }

    profile = profiles["isaac_human_vr_offline_rgb_v1"]
    assert data["simulation"]["isaac"]["recorder"]["source_profile"] == (
        "isaac_human_vr_offline_rgb_v1"
    )
    assert profile["runtime_binding_status"] == "pending_D1_implementation_and_evidence"
    assert profile["dataset_admissible_before_materialization_and_D1_evidence"] is False
    assert data["gates"]["D0"]["state"] == "accepted"
    assert data["gates"]["S2"]["state"] == "unresolved"
    assert data["gates"]["D1"]["state"] == "unresolved"
    assert data["dataset"]["sources"] == {}


def test_offline_rgb_profile_names_all_online_and_materialized_identities() -> None:
    profile = contract()["dataset"]["temporal_semantics"]["source_profiles"][
        "isaac_human_vr_offline_rgb_v1"
    ]

    assert profile["required_source_identities"] == [
        "simulation.scene_state_snapshot",
        "xr.device_io_update",
        "xr.submitted_frame",
        "xr.returned_frame",
        "xr.resolved_input",
    ]
    assert profile["scene_state_snapshot_identity_fields"] == [
        "run_id",
        "episode_id",
        "source_id",
        "reset_epoch",
        "control_reference_epoch",
        "source_epoch",
        "control_tick_id",
        "obs_id",
        "scene_state_snapshot_id",
        "scene_state_snapshot_sha256",
        "simulation_state_generation",
        "physics_step",
    ]
    assert profile["materialized_required_source_identities"] == [
        "offline_rgb.left_wrist",
        "offline_rgb.right_wrist",
        "offline_rgb.scene",
    ]
    assert profile["materialized_camera_identity_fields"] == [
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
    ]
    assert "positional_join_forbidden" in profile["materialized_camera_join"]


def test_native_hdf_row_is_one_committed_o_a_successor_transaction() -> None:
    row = contract()["dataset"]["temporal_semantics"]["native_recording_row"]

    assert row["revision"] == "isaac_vr_committed_transition_row_v1"
    assert row["applies_to_profile"] == "isaac_human_vr_offline_rgb_v1"
    assert row["admission"] == (
        "only_after_successful_transition_successor_observation_and_causal_commit"
    )
    assert row["cardinality"] == "one_hdf_row_per_committed_causal_transaction"
    assert list(row["fields"]) == [
        "observation_t",
        "dataset_action_t",
        "native_command_t",
        "transition_t",
        "next_observation_t_plus_1",
    ]
    assert row["fields"]["observation_t"]["identity_field"] == "obs_id"
    assert row["fields"]["observation_t"]["phase"] == "pre_decision_t"
    assert row["fields"]["dataset_action_t"]["identity_field"] == "dataset_action_id"
    assert "degrees_and_gripper_millimetres" in row["fields"]["dataset_action_t"]["units"]
    assert row["fields"]["native_command_t"]["units"] == (
        "ordered_joint_radians_and_gripper_metres"
    )
    assert row["fields"]["next_observation_t_plus_1"]["identity_field"] == "next_obs_id"
    assert "independent_of_control_tick_id" in row["hdf_row_index"]
    assert row["invalid_tick_policy"] == (
        "do_not_append_hdf_row_and_record_reason_in_episode_qa"
    )
    assert "never_as_invalid_tick_fill" in row["zero_action_policy"]
    assert "no_actionless_terminal_row" in row["terminal_state_policy"]
    assert row["missing_successor_policy"] == "abort_pending_transaction_and_do_not_append"
    assert row["episode_with_zero_commits"].endswith("dataset_admissible_false")


def test_d1_requires_selected_profile_and_row_semantics() -> None:
    rules = yaml.safe_load((ROOT / "configs" / "gate_rules.yaml").read_text(encoding="utf-8"))
    paths = rules["D1"]["required_paths"]

    assert "simulation.isaac.recorder.source_profile" in paths
    assert (
        "dataset.temporal_semantics.source_profiles."
        "isaac_human_vr_offline_rgb_v1.persistence_call_phase"
    ) in paths
    assert "dataset.temporal_semantics.native_recording_row.revision" in paths
    assert "dataset.temporal_semantics.native_recording_row.admission" in paths
    assert not any("source_profiles.isaac_human_vr_v4" in path for path in paths)


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (("native_recording_row", "admission"), "before_transition"),
        (("native_recording_row", "invalid_tick_policy"), "append_zero_fill"),
        (("native_recording_row", "terminal_state_policy"), "append_actionless_terminal"),
        (
            ("source_profiles", "isaac_human_vr_offline_rgb_v1", "materialized_camera_join"),
            "list_position",
        ),
        (
            (
                "source_profiles",
                "isaac_human_vr_offline_rgb_v1",
                "dataset_admissible_before_materialization_and_D1_evidence",
            ),
            True,
        ),
    ],
)
def test_schema_rejects_recording_contract_mutations(path: tuple[str, ...], bad_value: object) -> None:
    data = copy.deepcopy(contract())
    target = data["dataset"]["temporal_semantics"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad_value

    assert validate_schema(data, SCHEMA_PATH)


def test_checked_in_contract_remains_schema_and_dataset_valid() -> None:
    data = contract()
    assert validate_schema(data, SCHEMA_PATH) == []
    assert validate_dataset_contract(data) == []
