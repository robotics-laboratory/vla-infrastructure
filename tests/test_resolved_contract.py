"""Offline regression checks for the resolved-contract gate."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import yaml

from tools.validate_resolved_contract import (
    validate_contract,
    validate_dataset_contract,
    validate_gates,
    validate_process_architecture,
    validate_teleop_dependencies,
    validate_timing,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPOSITORY_ROOT / "configs" / "resolved_contract.yaml"
VALIDATOR = REPOSITORY_ROOT / "tools" / "validate_resolved_contract.py"


class ResolvedContractTests(unittest.TestCase):
    def test_validator_accepts_the_checked_in_contract(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(CONTRACT)],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CONTRACT STRUCTURALLY VALID", result.stdout)
        self.assertIn("CONTRACT SEMANTICALLY VALID", result.stdout)
        self.assertIn("FINAL RC NOT READY", result.stdout)

    def test_gate_a_accepts_the_implemented_plugin_artifact(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))

        self.assertEqual(data["gates"]["A"]["state"], "accepted")
        plugin = data["implementation"]["robot_plugin"]
        self.assertEqual(plugin["package"], "lerobot_robot_piperx")
        self.assertEqual(plugin["version"], "0.1.0")
        self.assertEqual(plugin["revision"], "c01076fc32794cffcc0eb10ea6157c34aeb8de24")
        errors, ready, blockers = validate_contract(CONTRACT)
        self.assertEqual(errors, [])
        self.assertFalse(ready)

    def test_gate_b_accepts_physical_q1_without_owning_robot_control_freshness(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        rules = yaml.safe_load(
            (REPOSITORY_ROOT / "configs" / "gate_rules.yaml").read_text(encoding="utf-8")
        )

        self.assertEqual(data["gates"]["B"]["state"], "accepted")
        real_dependency = data["teleop"]["real"]["runtime_dependencies"]["isaacteleop"]
        isaac_dependencies = data["teleop"]["isaac"]["runtime_dependencies"]
        self.assertEqual(real_dependency["version"], "1.3.131")
        self.assertEqual(
            real_dependency["revision"],
            "7002ed63d69454ae4f15c0ee19f803fd2846592b",
        )
        self.assertEqual(isaac_dependencies["isaacteleop"]["version"], "1.4.98rc1")
        self.assertEqual(isaac_dependencies["isaaclab_teleop"]["version"], "0.8.0")
        self.assertNotIn("isaac_teleop", data["implementation"])
        self.assertIn(
            "teleop.real.runtime_dependencies.isaacteleop.version",
            rules["B"]["required_paths"],
        )
        freshness_limits = {
            "timing.max_camera_age_ms",
            "timing.max_joint_age_ms",
            "timing.max_xr_age_ms",
            "timing.max_cross_modal_skew_ms",
        }
        self.assertTrue(freshness_limits.isdisjoint(rules["B"]["required_paths"]))
        for gate_id in ("D1", "R2", "HIL"):
            self.assertTrue(freshness_limits.issubset(rules[gate_id]["required_paths"]))
            probe = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
            probe["gates"][gate_id]["state"] = "accepted"
            errors = validate_gates(probe, rules)
            for path in freshness_limits:
                self.assertIn(
                    f"gate {gate_id}: unresolved required path {path}",
                    errors,
                )

    def test_temporal_contract_separates_logical_and_source_time(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        temporal = data["dataset"]["temporal_semantics"]

        self.assertEqual(
            data["dataset"]["policy_data_contract_revision"], "piper_x_d0_policy_data_v2"
        )
        self.assertEqual(temporal["dataset_timestamp"]["feature_key"], "timestamp")
        self.assertEqual(
            temporal["dataset_timestamp"]["computation"], "frame_index_div_dataset_fps"
        )
        self.assertFalse(temporal["dataset_timestamp"]["freshness_eligible"])
        self.assertEqual(
            temporal["source_timing"]["required_fields"],
            ["sequence", "source_timestamp", "clock_domain", "age_ms"],
        )
        self.assertEqual(
            temporal["freshness"]["enforcement_phase"],
            "after_source_selection_before_lerobot_dataset_add_frame",
        )
        by_source = temporal["source_timing"]["required_feature_sets_by_source_class"]
        self.assertIn("xr.left_pose", by_source["human_vr"])
        self.assertIn("xr.right_pose", by_source["human_vr"])
        self.assertNotIn("xr.left_pose", by_source["automated"])
        self.assertEqual(validate_dataset_contract(data), [])

        probe = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        probe["dataset"]["temporal_semantics"]["source_timing"]["feature_sets"][
            "observation.state"
        ]["source_timestamp"] = "timestamp"
        self.assertIn(
            "logical dataset timestamp must not be reused as source timing metadata",
            validate_dataset_contract(probe),
        )

    def test_rates_are_independent_and_command_rate_uses_interpolation(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        timing = data["timing"]

        self.assertEqual(timing["physics_fps"]["isaac"], 120)
        self.assertEqual(timing["control_fps"]["isaac"], 30)
        self.assertEqual(timing["dataset_fps"], 30)
        self.assertEqual(timing["xr_fps"]["real"], 30)

        probe = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        probe["timing"]["policy_fps"] = 10
        probe["timing"]["inference"]["interpolation_multiplier"] = 3
        probe["timing"]["command_fps"] = 30
        self.assertEqual(validate_timing(probe), [])
        probe["timing"]["command_fps"] = 29
        self.assertIn(
            "timing.command_fps must equal policy_fps * timing.inference.interpolation_multiplier",
            validate_timing(probe),
        )

    def test_camera_rate_is_not_forced_to_dataset_rate(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        data["timing"]["camera_fps"]["left_wrist"] = 15
        data["dataset"]["cameras"]["left_wrist"]["nominal_fps"] = 15

        self.assertEqual(validate_dataset_contract(data), [])

    def test_gate_a_rejects_an_unresolved_plugin_boundary(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        data["implementation"]["robot_plugin"]["package"] = None
        rules = yaml.safe_load(
            (REPOSITORY_ROOT / "configs" / "gate_rules.yaml").read_text(encoding="utf-8")
        )

        self.assertIn(
            "gate A: unresolved required path implementation.robot_plugin.package",
            validate_gates(data, rules),
        )

    def test_gate_s0_is_an_audit_selection_gate_not_an_isaac_runtime_gate(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        rules = yaml.safe_load(
            (REPOSITORY_ROOT / "configs" / "gate_rules.yaml").read_text(encoding="utf-8")
        )

        self.assertEqual(data["gates"]["S0"]["state"], "accepted")
        for gate_id in ("M0", "E0", "A", "B", "C", "D0"):
            self.assertEqual(data["gates"][gate_id]["state"], "accepted")
        self.assertEqual(
            rules["S0"]["required_evidence_kinds"],
            ["upstream_source", "document_review"],
        )
        self.assertEqual(rules["S0"]["required_artifact_kinds"], ["report"])
        self.assertNotIn("environments.isaac.spec_artifact_id", rules["S0"]["required_paths"])
        self.assertNotIn("execution_profiles.isaac_env.command", rules["S0"]["required_paths"])
        self.assertIn("execution_profiles.isaac_env.command", rules["S1"]["required_paths"])
        self.assertEqual(
            rules["S1"]["required_evidence_kinds"],
            ["command_test", "artifact_validation"],
        )
        self.assertIn(
            "gate_s0_isaac_compatibility_remediation",
            data["gates"]["S0"]["artifact_ids"],
        )
        self.assertIn(
            "teleop.isaac.runtime_dependencies.isaacteleop.version",
            rules["S0"]["required_paths"],
        )
        self.assertIn(
            "teleop.isaac.runtime_dependencies.isaaclab_teleop.version",
            rules["S0"]["required_paths"],
        )

    def test_teleop_dependencies_are_scoped_to_their_execution_environments(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))

        self.assertEqual(validate_teleop_dependencies(data), [])
        self.assertEqual(
            data["teleop"]["real"]["runtime_dependencies"]["isaacteleop"]["source_artifact_id"],
            data["environments"]["core"]["spec_artifact_id"],
        )
        self.assertEqual(
            data["teleop"]["isaac"]["runtime_dependencies"]["isaacteleop"]["source_artifact_id"],
            data["environments"]["isaac"]["spec_artifact_id"],
        )

        wrong_spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        wrong_spec["teleop"]["isaac"]["runtime_dependencies"]["isaacteleop"][
            "source_artifact_id"
        ] = "core_uv_lock"
        self.assertIn(
            "teleop.isaac.runtime_dependencies.isaacteleop: source artifact must be "
            "isaac_environment_selection for isaac",
            validate_teleop_dependencies(wrong_spec),
        )

        wrong_profile = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        wrong_profile["teleop"]["real"]["execution_profile"] = "isaac_vr_record"
        self.assertIn(
            "teleop.real: execution profile must use core environment",
            validate_teleop_dependencies(wrong_profile),
        )

    def test_gate_s2_cannot_accept_without_physical_human_evidence(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        rules = yaml.safe_load(
            (REPOSITORY_ROOT / "configs" / "gate_rules.yaml").read_text(encoding="utf-8")
        )

        self.assertEqual(data["gates"]["S2"]["state"], "unresolved")
        self.assertEqual(
            data["execution_profiles"]["isaac_vr_record"]["command"],
            ["python3", "tools/launch_isaac_s2.py"],
        )
        self.assertEqual(
            data["teleop"]["isaac"]["processor_revision"],
            "piper_x_isaac_s2_bimanual_relative_v2",
        )
        probe = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        probe["gates"]["S2"]["state"] = "accepted"
        errors = validate_gates(probe, rules)
        self.assertIn("gate S2: missing PASS evidence kind human_gate", errors)
        self.assertIn("gate S2: human evidence required", errors)

    def test_schema_rejects_the_ambiguous_global_isaac_teleop_field(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        data["implementation"]["isaac_teleop"] = {
            "version": "1.3.131",
            "revision": "7002ed63d69454ae4f15c0ee19f803fd2846592b",
            "evidence_ids": [],
        }

        errors, _, _ = validate_contract_from_data_for_schema_probe(data)
        self.assertTrue(
            any("Additional properties are not allowed" in error for error in errors),
            errors,
        )

    def test_process_architecture_keeps_eval_and_control_semantics_distinct(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        architecture = data["process_architecture"]

        self.assertEqual(validate_process_architecture(data), [])
        self.assertEqual(
            architecture["profile_ownership"]["isaac_eval"],
            {"execution_mode": "multi_process", "environments": ["core", "isaac"]},
        )
        self.assertEqual(
            architecture["eval_boundary"]["semantics"],
            "synchronous_episode_sensitive",
        )
        self.assertEqual(
            architecture["control_boundary"]["semantics"],
            "asynchronous_freshness_sensitive",
        )
        self.assertTrue(architecture["control_boundary"]["independent_of_eval"])
        self.assertEqual(architecture["eval_boundary"]["transport_selection"], "deferred")
        self.assertEqual(architecture["control_boundary"]["transport_selection"], "deferred")
        self.assertFalse(architecture["rpc_implementation_selected"])
        self.assertFalse(architecture["generic_simulator_api_exists"])

        probe = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        probe["process_architecture"]["eval_boundary"][
            "automatic_retry_after_ambiguous_timeout"
        ] = True
        errors, _, _ = validate_contract_from_data_for_schema_probe(probe)
        self.assertTrue(
            any("automatic_retry_after_ambiguous_timeout" in error for error in errors), errors
        )


def validate_contract_from_data_for_schema_probe(data: dict) -> tuple[list[str], bool, list[str]]:
    """Run the checked-in validator against an in-memory mutation via a temp contract."""
    import tempfile

    with tempfile.TemporaryDirectory(dir=REPOSITORY_ROOT) as directory:
        temp_contract = Path(directory) / "resolved_contract.yaml"
        temp_schema = Path(directory) / "resolved_contract.schema.json"
        temp_rules = Path(directory) / "gate_rules.yaml"
        temp_contract.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        temp_schema.write_bytes(
            (REPOSITORY_ROOT / "configs" / "resolved_contract.schema.json").read_bytes()
        )
        temp_rules.write_bytes((REPOSITORY_ROOT / "configs" / "gate_rules.yaml").read_bytes())
        return validate_contract(temp_contract, temp_rules)


if __name__ == "__main__":
    unittest.main()
