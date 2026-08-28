#!/usr/bin/env python3
"""
Small gate validator for configs/resolved_contract.yaml.

v4.5 adds environment and staged Gate A invariants:
- core must exist;
- accepted stages must map to declared environments;
- special environments require a reason and reproducible spec;
- Track A requires pinned donor/upstream inputs and a concrete external-plugin boundary,
  while the project-local Track 1B artifact pin may remain intentionally deferred;
- completion flags cannot hide DECIDE/PIN values.

This is validation, not an environment-management framework.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required") from exc

PIN_PREFIX = "DECIDE/PIN"

def get_path(data, path):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur

def unresolved(value):
    if isinstance(value, str):
        return value.startswith(PIN_PREFIX)
    if isinstance(value, dict):
        return any(unresolved(v) for v in value.values())
    if isinstance(value, list):
        return any(unresolved(v) for v in value)
    return False

STATIC_REQUIRED = [
    "implementation.lerobot.version_or_commit",
    "implementation.robot_plugin.repository",
    "implementation.robot_plugin.commit",
    "implementation.driver.backend",
    "implementation.driver.version_or_commit",
    "implementation.driver.robot_model",
    "implementation.isaac_teleop.version_or_commit",
    "evidence.piper_x_support",
    "evidence.bimanual_support",
    "evidence.driver_firmware_behavior",
    "robot_contract.action_features",
    "robot_contract.observation_features",
    "robot_contract.joint_order",
    "robot_contract.units",
    "robot_contract.gripper",
    "model.urdf",
    "model.frames",
    "quest_mapping.calibration_artifact",
    "quest_mapping.clutch_rebase_implementation",
    "processors.deterministic_label_pipeline",
    "environments.core.manager_or_launcher",
    "environments.core.python_version",
    "environments.core.spec_artifact.path",
    "environments.core.canonical_launch_prefix",
]

TRACK_A_REQUIRED = [
    "implementation.lerobot.repository",
    "implementation.lerobot.version_or_commit",
    "implementation.robot_plugin.artifact_status",
    "implementation.robot_plugin.integration_form",
    "implementation.robot_plugin.planned_distribution_name",
    "implementation.robot_plugin.planned_import_package",
    "implementation.robot_plugin.discovery_prefix",
    "implementation.robot_plugin.configuration_registration",
    "implementation.robot_plugin.construction_boundary",
    "implementation.robot_plugin.single_arm_type",
    "implementation.robot_plugin.bimanual_type",
    "implementation.driver.backend",
    "implementation.driver.repository",
    "implementation.driver.version_or_commit",
    "implementation.driver.robot_model",
    "implementation.driver.expected_firmware_profile",
    "evidence.candidate_matrix",
    "evidence.piper_x_support",
    "evidence.bimanual_support",
    "evidence.driver_firmware_behavior",
    "evidence.fork_vs_drop_in",
    "evidence.selected_plugin_seam",
    "evidence.track_1b_package_boundary",
    "evidence.core_environment_compatibility",
    "robot_contract.action_features",
    "robot_contract.observation_features",
    "robot_contract.joint_order",
    "robot_contract.units",
    "robot_contract.gripper.meaning",
    "robot_contract.gripper.command_units",
    "robot_contract.gripper.observation_transform",
    "robot_contract.gripper.command_transform",
    "robot_contract.declared_joint_limits_artifact",
    "robot_contract.declared_send_action.clips_joint_limits",
    "robot_contract.declared_send_action.slew_limits",
    "robot_contract.declared_send_action.returns_changed_or_sent_action",
    "robot_contract.declared_send_action.transforms",
    "robot_contract.declared_send_action.residual_driver_behavior",
    "model.urdf",
    "model.frames",
    "processors.deterministic_label_pipeline.sequence",
    "processors.deterministic_label_pipeline.implementation_status",
    "environments.core.manager_or_launcher",
    "environments.core.python_version",
    "environments.core.spec_artifact",
    "environments.core.torch_version",
    "environments.core.cuda_runtime",
    "environments.core.canonical_launch_prefix",
    "execution_profiles.offline_tests",
]

HARDWARE_REQUIRED = [
    "hardware.left",
    "hardware.right",
    "timing.control_fps",
    "timing.max_xr_pose_age_ms",
    "timing.max_joint_state_age_ms",
    "timing.max_policy_action_age_ms",
    "timing.stale_behavior",
    "safety.max_joint_step_or_slew",
    "safety.takeover_jump_tolerance",
    "safety.low_level_fail_safe",
]

HARDWARE_VERIFY_FLAGS = [
    "hardware_validation.left_right_identity_verified",
    "hardware_validation.joint_direction_verified",
    "hardware_validation.joint_units_verified",
    "hardware_validation.gripper_polarity_verified",
    "hardware_validation.gripper_range_verified",
    "hardware_validation.clipping_verified",
    "hardware_validation.slew_behavior_verified",
    "hardware_validation.returned_or_accepted_command_verified",
    "hardware_validation.low_level_fail_safe_verified",
]

def validate_schema(data, contract_path):
    schema_path = contract_path.with_name("resolved_contract.schema.json")
    if not schema_path.exists():
        return [f"schema file missing: {schema_path}"]
    try:
        import jsonschema
    except ImportError:
        return []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        return [f"JSON Schema validation failed: {exc.message}"]
    return []

def validate_environments(data):
    errors = []
    envs = data.get("environments", {})
    core = envs.get("core")
    special = envs.get("special", {})
    profiles = data.get("execution_profiles", {})

    if not isinstance(core, dict):
        errors.append("environments.core is required")
        return errors

    if core.get("required") is not True:
        errors.append("environments.core.required must be true")

    # Every resolved execution profile must reference core or an existing special env.
    known = {"core"} | set(special.keys())
    for profile, env_id in profiles.items():
        if not isinstance(env_id, str):
            errors.append(f"execution profile {profile} must be a string environment id")
            continue
        if env_id.startswith("DECIDE/PIN"):
            continue
        if env_id not in known:
            errors.append(f"execution profile {profile} references unknown environment: {env_id}")

    # Any special env must justify itself and be reproducible.
    for env_id, spec in special.items():
        if not isinstance(spec, dict):
            errors.append(f"special environment {env_id} must be an object")
            continue
        for key in ("reason", "evidence", "manager_or_launcher", "python_version",
                    "spec_artifact", "canonical_launch_prefix"):
            if key not in spec or unresolved(spec[key]):
                errors.append(f"special environment {env_id} unresolved field: {key}")

    return errors

def validate_completion(data):
    errors = []

    if data.get("status", {}).get("track_a_gate_complete"):
        for path in TRACK_A_REQUIRED:
            value = get_path(data, path)
            if value is None or unresolved(value):
                errors.append(f"track_a_gate_complete=true but unresolved: {path}")
        if get_path(data, "execution_profiles.offline_tests") != "core":
            errors.append("track_a_gate_complete requires execution_profiles.offline_tests=core")
        if data.get("environments", {}).get("special"):
            errors.append("track_a_gate_complete must not create a special environment without evidence")

    if data.get("status", {}).get("static_resolution_complete"):
        for path in STATIC_REQUIRED:
            value = get_path(data, path)
            if value is None or unresolved(value):
                errors.append(f"static_resolution_complete=true but unresolved: {path}")

        # Core-relevant accepted profiles must no longer be unresolved.
        for profile in ("offline_tests", "core_runtime", "replay", "rollout", "hil"):
            value = get_path(data, f"execution_profiles.{profile}")
            if value is None or unresolved(value):
                errors.append(f"static_resolution_complete=true but unresolved execution profile: {profile}")

    if data.get("status", {}).get("hardware_validation_complete"):
        for path in HARDWARE_REQUIRED:
            value = get_path(data, path)
            if value is None or unresolved(value):
                errors.append(f"hardware_validation_complete=true but unresolved: {path}")
        for path in HARDWARE_VERIFY_FLAGS:
            if get_path(data, path) is not True:
                errors.append(f"hardware_validation_complete=true but not verified: {path}")
        for profile in ("piper_readonly", "piper_motion"):
            value = get_path(data, f"execution_profiles.{profile}")
            if value is None or unresolved(value):
                errors.append(f"hardware_validation_complete=true but unresolved execution profile: {profile}")

    if data.get("status", {}).get("bimanual_real_gate_complete"):
        if data.get("status", {}).get("hardware_validation_complete") is not True:
            errors.append("bimanual_real_gate_complete=true requires hardware_validation_complete=true")
        mode = get_path(data, "safety.bimanual_inter_arm.mode")
        if mode not in {"verified_collision_handling", "disjoint_workspaces"}:
            errors.append("bimanual_real_gate_complete requires verified collision handling or disjoint workspaces")

    return errors

def main():
    contract_path = Path(sys.argv[1] if len(sys.argv) > 1 else "configs/resolved_contract.yaml")
    data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))

    errors = []
    errors += validate_schema(data, contract_path)
    errors += validate_environments(data)
    errors += validate_completion(data)

    if errors:
        print("RESOLVED CONTRACT INVALID")
        for err in errors:
            print(f"- {err}")
        return 1

    print("RESOLVED CONTRACT OK")
    print("- core environment policy is structurally valid")
    if data["status"].get("track_a_gate_complete"):
        print("- Track A static resolution is complete")
    if not data["status"]["static_resolution_complete"]:
        print("- static resolution is intentionally incomplete")
    if not data["status"]["hardware_validation_complete"]:
        print("- hardware validation is intentionally incomplete")
    if not data["status"]["bimanual_real_gate_complete"]:
        print("- bimanual real-operation gate is intentionally incomplete")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
