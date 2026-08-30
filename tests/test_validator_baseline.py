from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
VP = ROOT / "tools/validate_resolved_contract.py"
spec = importlib.util.spec_from_file_location("v52baseline", VP)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


def test_live_contract_is_valid_but_not_ready():
    errors, ready, blockers = mod.validate_contract(ROOT / "configs/resolved_contract.yaml")
    assert errors == []
    assert not ready
    assert "B" not in blockers
    assert {"R2", "HIL", "R3"}.issubset(blockers)


def test_all_gates_accepted_without_evidence_is_not_false_green(tmp_path):
    import yaml

    d = yaml.safe_load((ROOT / "configs/resolved_contract.yaml").read_text())
    for g in d["gates"].values():
        g["state"] = "accepted"
    # derived gate states alone are not enough; accepted-gate validation must explode on missing prerequisites/fields/evidence.
    rules = yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text())
    errors = mod.validate_gates(d, rules)
    assert errors
    assert any("missing PASS evidence kind" in e or "unresolved required path" in e for e in errors)
