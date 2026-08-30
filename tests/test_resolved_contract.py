"""Offline regression checks for the resolved-contract gate."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import yaml

from tools.validate_resolved_contract import validate_contract, validate_gates


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


if __name__ == "__main__":
    unittest.main()
