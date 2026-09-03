"""Offline regression checks for the resolved-contract gate."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import yaml

from tools.validate_resolved_contract import (
    validate_contract,
    validate_gates,
    validate_process_architecture,
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
        self.assertNotIn("timing.max_xr_pose_age_ms", rules["B"]["required_paths"])
        self.assertIn("timing.max_xr_pose_age_ms", rules["R2"]["required_paths"])
        self.assertIn("timing.max_xr_pose_age_ms", rules["HIL"]["required_paths"])
        for gate_id in ("R2", "HIL"):
            probe = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
            probe["gates"][gate_id]["state"] = "accepted"
            self.assertIn(
                f"gate {gate_id}: unresolved required path timing.max_xr_pose_age_ms",
                validate_gates(probe, rules),
            )

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
        self.assertNotIn(
            "environments.isaac.spec_artifact_id", rules["S0"]["required_paths"]
        )
        self.assertNotIn(
            "execution_profiles.isaac_env.command", rules["S0"]["required_paths"]
        )
        self.assertIn(
            "execution_profiles.isaac_env.command", rules["S1"]["required_paths"]
        )
        self.assertEqual(
            rules["S1"]["required_evidence_kinds"],
            ["command_test", "artifact_validation"],
        )
        self.assertIn(
            "gate_s0_isaac_compatibility_remediation",
            data["gates"]["S0"]["artifact_ids"],
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
        self.assertEqual(
            architecture["control_boundary"]["transport_selection"], "deferred"
        )
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
