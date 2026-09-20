"""Gate A contract regressions for the fail-closed real PIPER-X adapter."""

from __future__ import annotations

import hashlib
import subprocess
import tomllib
from pathlib import Path

import yaml

from tools.validate_resolved_contract import validate_gates, validate_schema


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/resolved_contract.yaml"
SCHEMA_PATH = ROOT / "configs/resolved_contract.schema.json"
RULES_PATH = ROOT / "configs/gate_rules.yaml"


def load_contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_gate_a_selects_the_hardened_plugin_and_evidence() -> None:
    contract = load_contract()
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    plugin = contract["implementation"]["robot_plugin"]
    gate = contract["gates"]["A"]

    assert plugin == {
        "package": "lerobot_robot_piperx",
        "version": "0.2.2",
        "revision": "90b37c2d72376f544f4fbda3b0138badc83bc856",
        "single_arm_type": "piperx_follower",
        "bimanual_type": "bi_piperx_follower",
        "evidence_ids": [
            "v43_track_1b_package_boundary",
            "v43_a_plugin_tests",
            "gate_a_piperx_adapter_hardening_review",
            "gate_a_piperx_adapter_hardening_tests",
        ],
    }
    assert "gate_a_piperx_adapter_hardening_review" in gate["evidence_ids"]
    assert "gate_a_piperx_adapter_hardening_tests" in gate["evidence_ids"]
    assert "gate_a_piperx_adapter_hardening_audit" in gate["artifact_ids"]
    assert "gate_a_piperx_adapter_hardening_test_output" in gate["artifact_ids"]
    assert validate_gates(contract, rules) == []

    # An uncommitted reconciliation is rooted in HEAD plus MERGE_HEAD.
    # Ancestry alone is insufficient: also require the pinned adapter bytes.
    parents = ["HEAD"]
    merge_head = subprocess.run(
        ["git", "rev-parse", "--verify", "MERGE_HEAD"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if merge_head.returncode == 0:
        parents.append(merge_head.stdout.strip())
    assert any(
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", plugin["revision"], parent],
            cwd=ROOT, check=False,
        ).returncode == 0
        for parent in parents
    )
    for relative in (
        "pyproject.toml", "src/lerobot_robot_piperx/__init__.py",
        "src/lerobot_robot_piperx/piperx.py", "src/lerobot_robot_piperx/sdk.py",
    ):
        path = "packages/lerobot_robot_piperx/" + relative
        pinned = subprocess.check_output(
            ["git", "show", f"{plugin['revision']}:{path}"], cwd=ROOT
        )
        assert (ROOT / path).read_bytes() == pinned, path


def test_fail_closed_semantics_are_exact_and_schema_required() -> None:
    contract = load_contract()
    semantics = contract["robot_contract"]["adapter_fail_closed"]

    assert semantics["telemetry"] == {
        "required_sdk_envelope_fields": ["time_stamp", "Hz"],
        "envelope_validity": "positive_finite_time_stamp_and_rate",
        "required_sdk_fields": [
            "joint_1",
            "joint_2",
            "joint_3",
            "joint_4",
            "joint_5",
            "joint_6",
            "grippers_angle",
        ],
        "temporal_component_frames": ["joint_1_2", "joint_3_4", "joint_5_6", "gripper"],
        "temporal_snapshot_behavior": "require_complete_atomic_copy",
        "state_source_timestamp_behavior": "oldest_required_can_receive_timestamp_with_fail_closed_wall_to_monotonic_drift_check",
        "missing_behavior": "reject_observation",
        "synthetic_default_allowed": False,
    }
    assert semantics["action"]["partial_arm_behavior"] == (
        "reject_entire_action_before_any_sdk_command"
    )
    assert semantics["action"]["invalid_numeric_behavior"] == (
        "reject_entire_action_before_any_sdk_command"
    )
    assert semantics["readiness"] == {
        "states": ["connected", "configured", "enabled", "motion_ready"],
        "motion_ready_requires": ["connected", "configured", "enabled"],
        "enable_timeout_behavior": "fail_connect_disable_and_rollback",
        "send_action_requirement": "motion_ready",
    }
    assert semantics["bimanual_lifecycle"] == {
        "connect_failure_behavior": "rollback_connected_peer",
        "disconnect_failure_behavior": "attempt_cleanup_both_raise_first_error",
        "partial_disconnect_behavior": "cleanup_all_acquired_resources",
        "attempted_camera_connect_failure_behavior": "rollback_camera_and_arm",
        "pre_send_validation": "validate_and_convert_both_sides_before_any_sdk_command",
    }
    assert validate_schema(contract, SCHEMA_PATH) == []

    invalid = load_contract()
    invalid["robot_contract"]["adapter_fail_closed"]["telemetry"]["envelope_validity"] = (
        "fields_present_only"
    )
    assert validate_schema(invalid, SCHEMA_PATH)

    invalid = load_contract()
    invalid["robot_contract"]["adapter_fail_closed"]["telemetry"]["synthetic_default_allowed"] = (
        True
    )
    assert validate_schema(invalid, SCHEMA_PATH)

    invalid = load_contract()
    invalid["robot_contract"]["adapter_fail_closed"]["action"]["partial_arm_behavior"] = (
        "ignore_partial_action"
    )
    assert validate_schema(invalid, SCHEMA_PATH)

    invalid = load_contract()
    invalid["robot_contract"]["adapter_fail_closed"]["readiness"]["send_action_requirement"] = (
        "connected"
    )
    assert validate_schema(invalid, SCHEMA_PATH)


def test_gate_a_rules_require_every_fail_closed_boundary() -> None:
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))["A"]
    required = set(rules["required_paths"])

    assert {
        "implementation.robot_plugin.revision",
        "robot_contract.adapter_fail_closed.telemetry.required_sdk_envelope_fields",
        "robot_contract.adapter_fail_closed.telemetry.envelope_validity",
        "robot_contract.adapter_fail_closed.telemetry.missing_behavior",
        "robot_contract.adapter_fail_closed.telemetry.synthetic_default_allowed",
        "robot_contract.adapter_fail_closed.action.partial_arm_behavior",
        "robot_contract.adapter_fail_closed.action.invalid_numeric_behavior",
        "robot_contract.adapter_fail_closed.readiness.motion_ready_requires",
        "robot_contract.adapter_fail_closed.readiness.enable_timeout_behavior",
        "robot_contract.adapter_fail_closed.readiness.send_action_requirement",
        "robot_contract.adapter_fail_closed.bimanual_lifecycle.connect_failure_behavior",
        "robot_contract.adapter_fail_closed.bimanual_lifecycle.disconnect_failure_behavior",
        "robot_contract.adapter_fail_closed.bimanual_lifecycle.partial_disconnect_behavior",
        "robot_contract.adapter_fail_closed.bimanual_lifecycle.attempted_camera_connect_failure_behavior",
        "robot_contract.adapter_fail_closed.bimanual_lifecycle.pre_send_validation",
    }.issubset(required)
    assert rules["required_evidence_kinds"] == [
        "upstream_source",
        "command_test",
        "document_review",
    ]
    assert rules["required_artifact_kinds"] == ["test_output", "report"]


def test_package_lock_and_gate_a_artifact_hashes_match() -> None:
    contract = load_contract()
    package = tomllib.loads(
        (ROOT / "packages/lerobot_robot_piperx/pyproject.toml").read_text(encoding="utf-8")
    )
    assert package["project"]["version"] == "0.2.2"
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "lerobot-robot-piperx"\nversion = "0.2.2"' in lock

    for artifact_id in (
        "gate_a_piperx_adapter_hardening_audit",
        "gate_a_piperx_adapter_hardening_test_output",
    ):
        artifact = contract["artifacts"][artifact_id]
        path = ROOT / artifact["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
