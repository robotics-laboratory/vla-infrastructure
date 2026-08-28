"""Offline regression checks for the resolved-contract gate."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import yaml

from tools.validate_resolved_contract import validate_completion


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
        self.assertIn("RESOLVED CONTRACT OK", result.stdout)

    def test_gate_a_accepts_the_implemented_track_1b_artifact(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))

        self.assertTrue(data["status"]["track_a_gate_complete"])
        plugin = data["implementation"]["robot_plugin"]
        self.assertEqual(plugin["planned_distribution_name"], "lerobot_robot_piperx")
        self.assertEqual(plugin["package_version"], "0.1.0")
        self.assertEqual(plugin["commit"], "PENDING_PROJECT_GIT_COMMIT")
        self.assertEqual(validate_completion(data), [])

    def test_gate_a_rejects_an_unresolved_plugin_boundary(self) -> None:
        data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        data["implementation"]["robot_plugin"]["planned_distribution_name"] = "DECIDE/PIN"

        self.assertIn(
            "track_a_gate_complete=true but unresolved: "
            "implementation.robot_plugin.planned_distribution_name",
            validate_completion(data),
        )


if __name__ == "__main__":
    unittest.main()
