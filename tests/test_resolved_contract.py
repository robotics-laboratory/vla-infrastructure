"""Offline regression checks for the resolved-contract gate."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
