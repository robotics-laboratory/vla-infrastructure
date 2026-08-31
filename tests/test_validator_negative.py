from __future__ import annotations
import importlib.util
import subprocess
import sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
VP = ROOT / "tools/validate_resolved_contract.py"
spec = importlib.util.spec_from_file_location("v52v", VP)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


def d():
    return yaml.safe_load((ROOT / "configs/resolved_contract.yaml").read_text())


def test01_hardware_missing():
    x = d()
    x["gates"]["R1"]["state"] = "accepted"
    del x["hardware"]
    errs = mod.validate_schema(x, ROOT / "configs/resolved_contract.schema.json")
    assert errs


def test02_bimanual_requires_r1():
    x = d()
    x["gates"]["R1B"]["state"] = "accepted"
    errs = mod.validate_gates(x, yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text()))
    assert any("prerequisite R1" in e for e in errs)


def test03_real_rollout_cannot_disable():
    x = d()
    x["requirements"]["capabilities"]["real_rollout"] = False
    errs = mod.validate_schema(x, ROOT / "configs/resolved_contract.schema.json")
    assert errs


def test04_r3_requires_hardware_chain():
    x = d()
    x["gates"]["R3"]["state"] = "accepted"
    errs = mod.validate_gates(x, yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text()))
    assert any("prerequisite R1B" in e for e in errs)


def test05_e1_requires_s1():
    x = d()
    x["gates"]["E1"]["state"] = "accepted"
    errs = mod.validate_gates(x, yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text()))
    assert any("prerequisite S1" in e for e in errs)


def test06_e2_requires_m1():
    x = d()
    x["gates"]["E2"]["state"] = "accepted"
    errs = mod.validate_gates(x, yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text()))
    assert any("prerequisite M1" in e for e in errs)


def test07_e3_requires_both_evals():
    x = d()
    x["gates"]["E3"]["state"] = "accepted"
    errs = mod.validate_gates(x, yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text()))
    assert any("prerequisite E1" in e for e in errs)


def test08_d2b_requires_real_dataset():
    x = d()
    x["gates"]["D2b"]["state"] = "accepted"
    errs = mod.validate_gates(x, yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text()))
    assert any("prerequisite R2" in e for e in errs)


def test09_false_final_ready():
    x = d()
    x["release"]["final_rc_state"] = "ready"
    ready, block = mod.derive_final(
        x, yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text())
    )
    assert not ready and block


def test10_b0_boolean_not_proof():
    x = d()
    x["gates"]["B0"]["state"] = "accepted"
    errs = mod.validate_gates(x, yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text()))
    assert any("prerequisite S0" in e for e in errs)


def test11_unknown_env_profile():
    x = d()
    x["execution_profiles"]["isaac_eval"]["environment"] = "unknown"
    assert any("unknown environment" in e for e in mod.validate_profiles(x))


def test12_legacy_alias_after_migration():
    x = d()
    x["migration"].update(
        {
            "mode": "from_v5_1",
            "state": "complete",
            "source_contract_artifact_id": "old",
            "legacy_alias_map": {"isaac:generated": "datagen"},
        }
    )
    assert any("legacy source aliases" in e for e in mod.validate_migration(x))


def test13_firmware_not_enough_for_r0():
    x = d()
    x["hardware"]["left"]["firmware_actual"] = "V189"
    x["hardware"]["right"]["firmware_actual"] = "V189"
    x["gates"]["R0"]["state"] = "accepted"
    errs = mod.validate_gates(x, yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text()))
    assert any("hardware.left.command_api" in e for e in errs)


def test14_d0_needs_causality():
    x = d()
    x["gates"]["D0"]["state"] = "accepted"
    x["dataset"]["temporal_semantics"]["causality_test_evidence_id"] = None
    errs = mod.validate_gates(x, yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text()))
    assert any("causality_test_evidence_id" in e or "causality test" in e for e in errs)


def test15_materialization_schema_mismatch():
    x = d()
    x["dataset"]["sources"] = {
        "r": {
            "runtime": "real",
            "source_class": "human_vr",
            "dataset_artifact_id": None,
            "manifest_artifact_id": "m1",
            "repo_id": None,
            "revision": "1",
            "schema_fingerprint_sha256": "a" * 64,
            "task_id": "t",
            "task_revision": "1",
            "processor_contract_revision": "p",
            "lineage_artifact_id": None,
        },
        "h": {
            "runtime": "isaac",
            "source_class": "human_vr",
            "dataset_artifact_id": None,
            "manifest_artifact_id": "m2",
            "repo_id": None,
            "revision": "1",
            "schema_fingerprint_sha256": "a" * 64,
            "task_id": "t",
            "task_revision": "1",
            "processor_contract_revision": "p",
            "lineage_artifact_id": None,
        },
        "g": {
            "runtime": "isaac",
            "source_class": "datagen",
            "dataset_artifact_id": None,
            "manifest_artifact_id": "m3",
            "repo_id": None,
            "revision": "1",
            "schema_fingerprint_sha256": "a" * 64,
            "task_id": "t",
            "task_revision": "1",
            "processor_contract_revision": "p",
            "lineage_artifact_id": None,
        },
    }
    x["dataset"]["materialization"]["selected_source_ids"] = ["r", "h", "g"]
    x["dataset"]["materialization"]["projected_schema_fingerprints"] = {
        "r": "a" * 64,
        "h": "b" * 64,
        "g": "a" * 64,
    }
    x["dataset"]["materialization"]["final_dataset"]["schema_fingerprint_sha256"] = "a" * 64
    assert any("schemas differ" in e for e in mod.validate_materialization(x))


def test16_crosssim_same_checkpoint():
    x = d()
    base = {
        "checkpoint_artifact_id": "cp",
        "checkpoint_sha256": "a" * 64,
        "policy_config_artifact_id": "pc",
        "preprocessor_artifact_id": "pre",
        "postprocessor_artifact_id": "post",
        "policy_contract_revision": "p",
        "environment_revision": "e",
        "task_id": "t",
        "task_revision": "1",
        "seed_set": [1],
        "n_episodes": 1,
        "horizon": 10,
        "success_semantics_revision": "s",
        "timeout_semantics": "timeout",
        "execution_profile": "isaac_eval",
        "run_manifest_artifact_id": "rm",
        "result_artifact_id": "res",
        "raw_log_artifact_id": "log",
    }
    x["evaluation"]["isaac_run"] = dict(base)
    x["evaluation"]["mujoco_run"] = dict(
        base, checkpoint_sha256="b" * 64, execution_profile="mujoco_eval"
    )
    assert any("different checkpoint" in e for e in mod.validate_cross_sim(x))


def test17_bad_sha_schema():
    x = d()
    x["artifacts"]["x"] = {
        "kind": "log",
        "sha256": "dummy",
        "path": "x",
        "uri": None,
        "description": "x",
    }
    assert mod.validate_schema(x, ROOT / "configs/resolved_contract.schema.json")


def test18_missing_artifact_file(tmp_path):
    x = d()
    x["artifacts"]["x"] = {
        "kind": "log",
        "sha256": "a" * 64,
        "path": str(tmp_path / "missing"),
        "uri": None,
        "description": "x",
    }
    assert any("local path missing" in e for e in mod.validate_artifacts(x, ROOT))


def test19_jsonschema_fail_closed():
    code = f"""import builtins,runpy\nr=builtins.__import__\ndef f(n,*a,**k):\n    if n=='jsonschema' or n.startswith('jsonschema.'): raise ImportError('blocked')\n    return r(n,*a,**k)\nbuiltins.__import__=f\nrunpy.run_path({str(VP)!r},run_name='__main__')"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode != 0 and "jsonschema unavailable" in (r.stdout + r.stderr)


def test20_migration_no_silent_drop():
    x = d()
    x["migration"].update(
        {
            "mode": "from_v4_3",
            "state": "complete",
            "source_contract_artifact_id": "old",
            "source_evidence_inventory": {"safety": ["e_old"]},
            "preserved_evidence_ids": [],
            "invalidated_evidence_ids": [],
        }
    )
    assert any("silently discarded" in e for e in mod.validate_migration(x))


def test21_schema_rejects_typo_property():
    x = d()
    x["hardwrae"] = x["hardware"]
    errs = mod.validate_schema(x, ROOT / "configs/resolved_contract.schema.json")
    assert any("Additional properties" in e for e in errs)
