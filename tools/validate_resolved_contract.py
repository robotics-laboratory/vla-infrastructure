#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    print(f"VALIDATOR DEPENDENCY ERROR: PyYAML unavailable: {exc}", file=sys.stderr)
    raise SystemExit(2)
try:
    import jsonschema
except ImportError as exc:
    print(f"VALIDATOR DEPENDENCY ERROR: jsonschema unavailable: {exc}", file=sys.stderr)
    raise SystemExit(2)

PLACEHOLDER_PREFIXES = ("DECIDE/PIN", "MIGRATE/PRESERVE")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
AUTOMATED = {"scripted_expert", "planner", "datagen", "policy_generated"}
REQUIRED_PROVENANCE = {
    "runtime",
    "source_class",
    "task_revision",
    "embodiment_revision",
    "processor_contract_revision",
    "dataset_revision",
    "conversion_revision",
}
EXPECTED_PROCESS_PROFILE_OWNERSHIP = {
    "offline_tests": ("single_process", ["core"]),
    "isaac_env": ("single_process", ["isaac"]),
    "isaac_vr": ("single_process", ["isaac"]),
    "isaac_generate": ("single_process", ["isaac"]),
    "isaac_dataset_convert": ("single_process", ["core"]),
    "isaac_eval": ("multi_process", ["core", "isaac"]),
    "mujoco_env": ("single_process", ["core"]),
    "mujoco_eval": ("single_process", ["core"]),
}
EXPECTED_EVAL_HANDSHAKE_FIELDS = [
    "protocol_revision",
    "run_id",
    "D0_contract_fingerprint",
    "environment_revision",
    "PIPER_X_asset_model_revision",
    "task_id",
    "task_revision",
    "processor_revision",
    "n_episodes",
    "horizon",
]
EXPECTED_EVAL_HANDSHAKE_RESPONSE_FIELDS = ["run_id", "endpoint_instance_id", "accepted"]
EXPECTED_EVAL_RESET_FIELDS = {
    "request_fields": ["run_id", "request_id", "episode_id", "seed", "task_id", "task_revision"],
    "response_fields": ["request_id", "canonical_D0_obs_0", "effective_seed"],
}
EXPECTED_EVAL_STEP_FIELDS = {
    "request_fields": ["run_id", "request_id", "episode_id", "step_index", "canonical_D0_action_t"],
    "response_fields": [
        "request_id",
        "canonical_D0_obs_t_plus_1",
        "reward_t",
        "terminated_t",
        "truncated_t",
        "success_t",
        "termination_reason",
    ],
}
EXPECTED_EVAL_LIFECYCLE_FIELDS = {
    "abort": {
        "request_fields": ["run_id", "request_id", "episode_id", "reason"],
        "response_fields": ["request_id", "abort_state"],
    },
    "close": {
        "request_fields": ["run_id", "request_id"],
        "response_fields": ["request_id", "close_state"],
    },
}
EXPECTED_EVAL_REQUEST_IDENTITY = {
    "field": "request_id",
    "generation_owner": "eval_client",
    "format": "opaque_nonempty_string_unique_within_run",
    "required_operations": ["reset", "step", "abort", "close"],
    "scope_fields": ["run_id", "request_id"],
    "response_echo_required": True,
    "reuse_with_different_operation_or_payload": "protocol_error_no_execution",
}
EXPECTED_EVAL_DEDUPLICATION = {
    "owner": "eval_runtime_endpoint",
    "key_fields": ["run_id", "request_id"],
    "request_fingerprint": "operation_plus_canonical_payload",
    "duplicate_same_fingerprint": "return_cached_response_without_reexecution",
    "duplicate_different_fingerprint": "protocol_error_no_execution",
    "survives_transport_reconnect": True,
    "survives_endpoint_restart": False,
    "endpoint_restart_behavior": "invalidate_run_and_classify_infrastructure_failure",
    "retention": "through_run_close_response",
    "capacity_bound": "declared_n_episodes_times_horizon_plus_reset_abort_and_close_requests",
    "implementation_state": "implemented",
}
EXPECTED_EVAL_IMPLEMENTATION = {
    "endpoint": "tools.isaac_eval_rpc.IsaacEvalEndpoint",
    "client": "tools.isaac_eval_rpc.UnixEvalClient",
    "server": "tools.isaac_eval_rpc.serve_unix_socket",
    "codec": "utf8_json_lines_allow_nan_false",
    "isaac_entrypoint": "tools/run_isaac_s1.py --eval-socket --eval-run-manifest",
}
EXPECTED_CONTROL_COMMAND_FIELDS = [
    "canonical_PIPER_X_command_semantics",
    "sequence",
    "source_timestamp",
    "clock_domain",
    "source_control_state",
]
EXPECTED_CONTROL_OBSERVATION_FIELDS = [
    "measured_canonical_observation_where_required",
    "sequence",
    "source_timestamp",
    "clock_domain",
    "age_ms",
    "health_state",
]
EXPECTED_SOURCE_TIMING_FIELDS = ["sequence", "source_timestamp", "clock_domain", "age_ms"]
EXPECTED_SOURCE_TIMING_FEATURE_SETS = [
    "observation.state",
    "observation.images.left_wrist",
    "observation.images.right_wrist",
    "observation.images.scene",
    "xr.left_pose",
    "xr.right_pose",
    "source_action",
]
EXPECTED_SOURCE_TIMING_BY_SOURCE_CLASS = {
    "human_vr": EXPECTED_SOURCE_TIMING_FEATURE_SETS,
    "automated": [
        "observation.state",
        "observation.images.left_wrist",
        "observation.images.right_wrist",
        "observation.images.scene",
        "source_action",
    ],
}
EXPECTED_CONTROL_EXCLUSIONS = [
    "reset",
    "seeds",
    "episode_metrics",
    "recording",
    "generation",
    "asset_management",
]


def load_yaml(p: Path):
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def get_path(d: Any, path: str):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def walk(v, p=""):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from walk(x, f"{p}.{k}" if p else k)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from walk(x, f"{p}[{i}]")
    else:
        yield p, v


def resolved(v):
    return v is not None and (not isinstance(v, str) or bool(v.strip()))


def nonempty(v):
    return v is not None and (not isinstance(v, (str, list, dict)) or len(v) > 0)


def project_root(contract_path: Path):
    return contract_path.resolve().parent.parent


def validate_schema(d, schema_path):
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    val = jsonschema.Draft202012Validator(schema)
    out = []
    for e in sorted(val.iter_errors(d), key=lambda e: list(e.absolute_path)):
        loc = ".".join(str(x) for x in e.absolute_path) or "<root>"
        out.append(f"schema {loc}: {e.message}")
    return out


def validate_artifacts(d, root):
    out = []
    for aid, a in d["artifacts"].items():
        if not SHA_RE.fullmatch(a["sha256"]):
            out.append(f"artifact {aid}: invalid SHA-256 syntax")
            continue
        path = a.get("path")
        uri = a.get("uri")
        if not path and not uri:
            out.append(f"artifact {aid}: path or uri required")
        if path:
            p = Path(path).expanduser()
            p = p if p.is_absolute() else root / p
            if not p.exists():
                out.append(f"artifact {aid}: local path missing: {p}")
                continue
            if p.is_file():
                actual = hashlib.sha256(p.read_bytes()).hexdigest()
                if actual.lower() != a["sha256"].lower():
                    out.append(f"artifact {aid}: SHA-256 mismatch")
    return out


def validate_evidence(d):
    out = []
    arts = d["artifacts"]
    for eid, e in d["evidence"].items():
        for aid in e["artifact_ids"]:
            if aid not in arts:
                out.append(f"evidence {eid}: unknown artifact {aid}")
        if e["kind"] == "upstream_source":
            for k in ("repository", "revision_type", "revision", "path"):
                if not e.get(k):
                    out.append(f"evidence {eid}: upstream_source requires {k}")
            if (
                e.get("revision_type") == "commit"
                and e.get("revision")
                and not COMMIT_RE.fullmatch(e["revision"])
            ):
                out.append(f"evidence {eid}: invalid commit revision")
        if (
            e["kind"]
            in {"command_test", "artifact_validation", "human_gate", "hardware_observation", "run"}
            and e["status"] == "pass"
            and not e["artifact_ids"]
        ):
            out.append(f"evidence {eid}: passing {e['kind']} requires artifact_ids")
    return out


def validate_generic_refs(d):
    out = []
    arts = d["artifacts"]
    evs = d["evidence"]

    def rec(v, path=""):
        if isinstance(v, dict):
            for k, x in v.items():
                p = f"{path}.{k}" if path else k
                # migration inventory may refer to legacy evidence not in current registry.
                if p.startswith("migration.source_evidence_inventory") or p.startswith(
                    "migration.invalidated_evidence_ids"
                ):
                    pass
                elif k.endswith("_artifact_id") and x is not None and x not in arts:
                    out.append(f"{p}: unknown artifact {x}")
                elif k == "artifact_ids" and isinstance(x, list):
                    for a in x:
                        if a not in arts:
                            out.append(f"{p}: unknown artifact {a}")
                elif k.endswith("_evidence_id") and x is not None and x not in evs:
                    out.append(f"{p}: unknown evidence {x}")
                elif k == "evidence_ids" and isinstance(x, list):
                    for e in x:
                        if e not in evs:
                            out.append(f"{p}: unknown evidence {e}")
                rec(x, p)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                rec(x, f"{path}[{i}]")

    # Gate refs handled by gate validation; migration preserved ids can refer legacy inventory.
    for k, v in d.items():
        if k not in {"gates", "migration"}:
            rec(v, k)
    return out


def validate_profiles(d):
    out = []
    for n, p in d["execution_profiles"].items():
        if p["environment"] not in d["environments"]:
            out.append(f"execution profile {n}: unknown environment {p['environment']}")
    for name, environment in d["environments"].items():
        aid = environment["spec_artifact_id"]
        if (
            aid is not None
            and aid in d["artifacts"]
            and d["artifacts"][aid]["kind"] != "environment_spec"
        ):
            out.append(f"environment {name}: spec artifact {aid} must be environment_spec")
    recorder_profile = d["simulation"]["isaac"]["recorder"]["execution_profile"]
    if recorder_profile is not None:
        recorder = d["execution_profiles"].get(recorder_profile)
        if recorder is None or not recorder["command"]:
            out.append("Isaac recorder: execution_profile must reference a runnable profile")
        if recorder_profile == "isaac_vr":
            out.append("Isaac recorder: isaac_vr does not implement recording")
    return out


def validate_teleop_dependencies(d):
    """Keep Quest dependency pins owned by their actual execution environments."""
    out = []
    expected = {"real": "core", "isaac": "isaac"}
    for runtime, expected_environment in expected.items():
        binding = d["teleop"][runtime]
        profile_name = binding["execution_profile"]
        profile = d["execution_profiles"].get(profile_name)
        if profile is None:
            out.append(f"teleop.{runtime}: unknown execution profile {profile_name}")
        elif profile["environment"] != expected_environment:
            out.append(
                f"teleop.{runtime}: execution profile must use {expected_environment} environment"
            )

        environment = d["environments"][expected_environment]
        expected_artifact = environment["spec_artifact_id"]
        for name, dependency in binding["runtime_dependencies"].items():
            if dependency["package"] != name:
                out.append(f"teleop.{runtime}.runtime_dependencies.{name}: package name mismatch")
            if dependency["source_artifact_id"] != expected_artifact:
                out.append(
                    f"teleop.{runtime}.runtime_dependencies.{name}: source artifact must be "
                    f"{expected_artifact} for {expected_environment}"
                )
            if dependency["revision_type"] == "commit" and not COMMIT_RE.fullmatch(
                dependency["revision"] or ""
            ):
                out.append(f"teleop.{runtime}.runtime_dependencies.{name}: invalid commit revision")
    return out


def validate_process_architecture(d):
    out = []
    architecture = d["process_architecture"]
    shared = architecture["shared_semantic_boundary"]
    dataset = d["dataset"]
    if shared["contract_revision"] != dataset["policy_data_contract_revision"]:
        out.append("process architecture must reference the accepted D0 contract revision")
    if (
        shared["schema_fingerprint_sha256"]
        != dataset["common_training_view"]["schema_fingerprint_sha256"]
    ):
        out.append("process architecture D0 fingerprint mismatch")

    expected_process_environments = {"core_lerobot": "core", "isaac_native": "isaac"}
    for name, expected_environment in expected_process_environments.items():
        actual = architecture["processes"][name]["environment"]
        if actual != expected_environment:
            out.append(f"process architecture {name}: environment must be {expected_environment}")

    ownership = architecture["profile_ownership"]
    for name, (mode, environments) in EXPECTED_PROCESS_PROFILE_OWNERSHIP.items():
        record = ownership[name]
        if record["execution_mode"] != mode or record["environments"] != environments:
            out.append(
                f"process architecture profile {name}: expected {mode} environments={environments}"
            )
        if d["execution_profiles"][name]["environment"] != environments[0]:
            out.append(f"execution profile {name}: primary environment must be {environments[0]}")
        for environment in record["environments"]:
            if environment not in d["environments"]:
                out.append(
                    f"process architecture profile {name}: unknown environment {environment}"
                )

    eval_boundary = architecture["eval_boundary"]
    if eval_boundary["handshake_fields"] != EXPECTED_EVAL_HANDSHAKE_FIELDS:
        out.append("EVAL boundary handshake fields/order mismatch")
    if eval_boundary["handshake_response_fields"] != EXPECTED_EVAL_HANDSHAKE_RESPONSE_FIELDS:
        out.append("EVAL boundary handshake response fields/order mismatch")
    if eval_boundary["reset"] != EXPECTED_EVAL_RESET_FIELDS:
        out.append("EVAL boundary reset fields/order mismatch")
    if eval_boundary["step"] != EXPECTED_EVAL_STEP_FIELDS:
        out.append("EVAL boundary step fields/order mismatch")
    if eval_boundary["request_identity"] != EXPECTED_EVAL_REQUEST_IDENTITY:
        out.append("EVAL boundary request identity mismatch")
    if eval_boundary["deduplication"] != EXPECTED_EVAL_DEDUPLICATION:
        out.append("EVAL boundary deduplication mismatch")
    if eval_boundary["lifecycle"] != EXPECTED_EVAL_LIFECYCLE_FIELDS:
        out.append("EVAL boundary lifecycle fields/order mismatch")
    if eval_boundary["implementation"] != EXPECTED_EVAL_IMPLEMENTATION:
        out.append("EVAL boundary implementation binding mismatch")
    if eval_boundary["lifecycle_operations"] != ["abort", "close"]:
        out.append("EVAL boundary lifecycle operations must be abort, close")

    control = architecture["control_boundary"]
    if control["command_fields"] != EXPECTED_CONTROL_COMMAND_FIELDS:
        out.append("CONTROL boundary command fields/order mismatch")
    if control["observation_fields"] != EXPECTED_CONTROL_OBSERVATION_FIELDS:
        out.append("CONTROL boundary observation fields/order mismatch")
    if control["excluded_ownership"] != EXPECTED_CONTROL_EXCLUSIONS:
        out.append("CONTROL boundary excluded ownership mismatch")
    return out


def validate_migration(d):
    out = []
    m = d["migration"]
    if m["mode"] == "fresh" and m["state"] != "not_required":
        out.append("fresh migration mode requires state=not_required")
    if m["mode"] != "fresh":
        if m["state"] == "not_required":
            out.append("migrated project cannot use state=not_required")
        if not m["source_contract_artifact_id"]:
            out.append("migrated project requires source_contract_artifact_id")
        elif m["source_contract_artifact_id"] not in d["artifacts"]:
            out.append("migration source_contract_artifact_id must reference a registered artifact")
        elif d["artifacts"][m["source_contract_artifact_id"]]["kind"] != "source_bundle":
            out.append("migration source contract artifact must be kind=source_bundle")
    if m["state"] in {"complete", "not_required"} and m["legacy_alias_map"]:
        out.append("legacy source aliases forbidden after migration completion")
    if m["state"] == "complete":
        inv = {x for ids in m["source_evidence_inventory"].values() for x in ids}
        disp = set(m["preserved_evidence_ids"]) | set(m["invalidated_evidence_ids"])
        missing = sorted(inv - disp)
        if missing:
            out.append(f"migration silently discarded inventoried evidence: {missing}")
        for eid in m["preserved_evidence_ids"]:
            if eid not in d["evidence"]:
                out.append(
                    f"migration preserved evidence not registered in current evidence: {eid}"
                )
    return out


def validate_feature_contract(d):
    out = []
    rc = d["robot_contract"]
    for kind in ("action_features", "observation_features"):
        names = [f["name"] for f in rc[kind]]
        if len(names) != len(set(names)):
            out.append(f"robot_contract.{kind}: duplicate feature names")
    cls = d["dataset"]["feature_classification"]
    seen: dict[str, str] = {}
    for cat, names in cls.items():
        for name in names:
            if name in seen:
                out.append(f"dataset feature {name}: classified as both {seen[name]} and {cat}")
            seen[name] = cat
    inputs = set(d["dataset"]["common_training_view"]["input_features"])
    if inputs != set(cls["training_input"]):
        out.append("common training input feature set != feature_classification.training_input")
    if inputs & set(cls["privileged_debug"]):
        out.append("privileged_debug feature leaked into policy training inputs")
    return out


def validate_timing(d):
    out = []
    timing = d["timing"]
    inf = timing["inference"]
    mode = inf["mode"]
    if mode in {"chunked_sync", "rtc_async"}:
        for k in (
            "chunk_horizon",
            "execution_horizon",
            "interpolation_multiplier",
            "stale_chunk_rule",
            "action_age_reference",
        ):
            if not resolved(inf[k]):
                out.append(f"chunked inference requires timing.inference.{k}")

    policy_fps = timing["policy_fps"]
    command_fps = timing["command_fps"]
    multiplier = inf["interpolation_multiplier"]
    if resolved(command_fps):
        if not resolved(policy_fps) or not resolved(multiplier):
            out.append("timing.command_fps requires policy_fps and interpolation_multiplier")
        elif abs(command_fps - policy_fps * multiplier) > 1e-9:
            out.append(
                "timing.command_fps must equal policy_fps * "
                "timing.inference.interpolation_multiplier"
            )

    isaac_execution = d["simulation"]["isaac"]["execution"]
    physics_dt = isaac_execution["physics_dt_s"]
    control_dt = isaac_execution["control_dt_s"]
    isaac_physics_fps = timing["physics_fps"]["isaac"]
    if resolved(physics_dt):
        if not resolved(isaac_physics_fps):
            out.append("timing.physics_fps.isaac is required when Isaac physics_dt_s is resolved")
        elif abs(isaac_physics_fps - 1 / physics_dt) > 1e-9:
            out.append(
                "timing.physics_fps.isaac must equal 1 / simulation.isaac.execution.physics_dt_s"
            )
    isaac_control_fps = timing["control_fps"]["isaac"]
    if resolved(control_dt):
        if not resolved(isaac_control_fps):
            out.append("timing.control_fps.isaac is required when Isaac control_dt_s is resolved")
        elif abs(isaac_control_fps - 1 / control_dt) > 1e-9:
            out.append(
                "timing.control_fps.isaac must equal 1 / simulation.isaac.execution.control_dt_s"
            )
    return out


def validate_eval_run(d, name):
    out: list[str] = []
    run = d["evaluation"].get(name)
    if run is None:
        return out
    expected = {
        "checkpoint_artifact_id": "checkpoint",
        "policy_config_artifact_id": "policy_config",
        "preprocessor_artifact_id": "processor_config",
        "postprocessor_artifact_id": "processor_config",
        "run_manifest_artifact_id": "run_manifest",
        "result_artifact_id": "eval_result",
        "raw_log_artifact_id": "log",
    }
    for field, kind in expected.items():
        aid = run[field]
        a = d["artifacts"].get(aid)
        if not a:
            out.append(f"{name}: unknown artifact {field}={aid}")
        elif a["kind"] != kind:
            out.append(f"{name}: artifact {aid} must be {kind}, got {a['kind']}")
    cp = d["artifacts"].get(run["checkpoint_artifact_id"])
    if cp and cp["sha256"].lower() != run["checkpoint_sha256"].lower():
        out.append(f"{name}: checkpoint SHA mismatch")
    if run["execution_profile"] not in d["execution_profiles"]:
        out.append(f"{name}: unknown execution profile")
    expected_profile = "isaac_eval" if name == "isaac_run" else "mujoco_eval"
    if run["execution_profile"] != expected_profile:
        out.append(f"{name}: execution_profile must be {expected_profile}")
    return out


def validate_cross_sim(d):
    out = []
    a = d["evaluation"]["isaac_run"]
    m = d["evaluation"]["mujoco_run"]
    if a is None or m is None:
        return ["cross-sim acceptance requires both evaluation runs"]
    if a["checkpoint_sha256"].lower() != m["checkpoint_sha256"].lower():
        out.append("cross-sim evaluation uses different checkpoint SHA-256 values")
    if a["policy_contract_revision"] != m["policy_contract_revision"]:
        out.append("cross-sim evaluation uses different policy contract revisions")
    if (a["task_id"], a["task_revision"]) != (m["task_id"], m["task_revision"]):
        out.append("cross-sim evaluation uses different canonical task id/revision")
    return out


def has_source(d, runtime, source_class=None, automated=False):
    for s in d["dataset"]["sources"].values():
        if s["runtime"] != runtime:
            continue
        if source_class and s["source_class"] != source_class:
            continue
        if automated and s["source_class"] not in AUTOMATED:
            continue
        return True
    return False


def validate_materialization(d):
    out = []
    m = d["dataset"]["materialization"]
    sources = d["dataset"]["sources"]
    sel = m["selected_source_ids"]
    fps = m["projected_schema_fingerprints"]
    final = m["final_dataset"]["schema_fingerprint_sha256"]
    for sid in sel:
        if sid not in sources:
            out.append(f"dataset materialization selects unknown source {sid}")
        if sid not in fps:
            out.append(f"dataset materialization missing projected schema fingerprint for {sid}")
    vals = [fps[s] for s in sel if s in fps]
    if vals and len({v.lower() for v in vals}) != 1:
        out.append("projected source feature schemas differ")
    if vals and final and any(v.lower() != final.lower() for v in vals):
        out.append("projected source schema fingerprint != final dataset schema fingerprint")
    if final and final != canonical_training_schema_fingerprint(d):
        out.append("final materialized schema must equal the canonical three-camera schema")
    fd = m["final_dataset"]
    if fd["identity_type"] == "hub_revision" and (not fd["repo_id"] or not fd["revision"]):
        out.append("hub_revision final dataset identity requires repo_id and revision")
    if fd["manifest_artifact_id"] and fd["manifest_artifact_id"] not in d["artifacts"]:
        out.append("final dataset manifest artifact is not registered")
    elif (
        fd["manifest_artifact_id"]
        and d["artifacts"][fd["manifest_artifact_id"]]["kind"] != "dataset_manifest"
    ):
        out.append("final dataset manifest artifact must be kind=dataset_manifest")
    for runtime, sc in [("real", "human_vr"), ("isaac", "human_vr")]:
        if not any(
            s in sources and sources[s]["runtime"] == runtime and sources[s]["source_class"] == sc
            for s in sel
        ):
            out.append(f"materialization missing selected source runtime={runtime}, source={sc}")
    if not any(
        s in sources
        and sources[s]["runtime"] == "isaac"
        and sources[s]["source_class"] in AUTOMATED
        for s in sel
    ):
        out.append("materialization missing selected automated Isaac source")
    return out


def validate_dataset_contract(d):
    out = []
    prov = set(d["dataset"]["provenance_schema"]["fields"])
    miss = sorted(REQUIRED_PROVENANCE - prov)
    if miss:
        out.append(f"dataset provenance schema missing mandatory fields: {miss}")
    eid = d["dataset"]["temporal_semantics"]["causality_test_evidence_id"]
    ev = d["evidence"].get(eid) if eid else None
    if not ev or ev["kind"] != "command_test" or ev["status"] != "pass":
        out.append("dataset causality test must reference PASS command_test evidence")
    dataset = d["dataset"]
    action_names = [feature["name"] for feature in d["robot_contract"]["action_features"]]
    observation_names = [feature["name"] for feature in d["robot_contract"]["observation_features"]]
    action_units = [feature["units"] for feature in d["robot_contract"]["action_features"]]
    observation_units = [
        feature["units"] for feature in d["robot_contract"]["observation_features"]
    ]
    action = dataset["action_label_pipeline"]["dataset_action"]
    state = dataset["observation_contract"]["state"]
    source_action = dataset["action_label_pipeline"]["source_action"]
    if action["names"] != action_names or source_action["feature_names"] != action_names:
        out.append(
            "D0 action order must exactly match the accepted Gate A Robot.action_features order"
        )
    if state["names"] != observation_names:
        out.append(
            "D0 observation.state order must exactly match Gate A Robot.observation_features"
        )
    if action["units"] != action_units or source_action["units"] != action_units:
        out.append("D0 action units must exactly preserve the accepted Gate A units")
    if state["units"] != observation_units:
        out.append("D0 observation.state units must exactly preserve the accepted Gate A units")
    if action["shape"] != [len(action_names)] or state["shape"] != [len(observation_names)]:
        out.append("D0 state/action vector shapes must equal their ordered scalar counts")
    roles = ["left_wrist", "right_wrist", "scene"]
    if list(dataset["cameras"]) != roles:
        out.append("D0 camera roles/order must be left_wrist, right_wrist, scene")
    if dataset["policy_data_contract_revision"] != "piper_x_d0_policy_data_v4":
        out.append("D0 requires policy data contract v4")
    camera_features = [camera["feature_key"] for camera in dataset["cameras"].values()]
    expected_inputs = [
        state["feature_key"],
        *camera_features,
        dataset["common_training_view"]["task_feature"],
    ]
    if dataset["common_training_view"]["input_features"] != expected_inputs:
        out.append("D0 common training inputs must be ordered state, canonical cameras, then task")
    if dataset["common_training_view"]["target_features"] != [action["feature_key"]]:
        out.append("D0 common training target must be the one canonical dataset action")
    if dataset["observation_contract"]["policy_whitelist"] != expected_inputs:
        out.append("D0 policy whitelist must exactly equal the common training inputs")
    if dataset["processor_ownership"]["stateful_processors"]:
        out.append("D0 must not select stateful processors")
    if dataset["action_label_pipeline"]["label_processor"]["stateful"]:
        out.append("D0 identity label processor must be stateless")
    if dataset["action_label_pipeline"]["runtime_mapping"]["stored_label_mutation_allowed"]:
        out.append("runtime/device mapping must not mutate the stored D0 label")
    if dataset["action_label_pipeline"]["device_accepted_command"]["observable_at_d0"]:
        out.append("D0 must not claim unobserved hardware accepted-command evidence")
    fps = d["timing"]["dataset_fps"]
    if fps != dataset["resampling"]["canonical_fps"]:
        out.append("timing.dataset_fps must equal D0 resampling.canonical_fps")
    for role, camera in dataset["cameras"].items():
        if camera["nominal_fps"] != d["timing"]["camera_fps"].get(role):
            out.append(f"dataset camera {role} nominal_fps must equal timing.camera_fps.{role}")

    temporal = dataset["temporal_semantics"]
    dataset_timestamp = temporal["dataset_timestamp"]
    source_timing = temporal["source_timing"]
    expected_source_timing_implementation = {
        "recorder_adapter": "tools.d0_temporal.TemporalFrameRecorder",
        "production_dataset_adapter": ("tools.temporal_recording.TemporalLeRobotDatasetAdapter"),
        "record_loop_factory": (
            "tools.temporal_recording.wrap_lerobot_dataset_for_temporal_recording"
        ),
        "feature_spec_factory": "tools.d0_temporal.temporal_feature_specs",
        "qa_summary_method": "tools.d0_temporal.TemporalFrameRecorder.qa_summary",
    }
    if any(
        source_timing[key] != value for key, value in expected_source_timing_implementation.items()
    ):
        out.append("source timing runtime implementation binding mismatch")
    if source_timing["required_fields"] != EXPECTED_SOURCE_TIMING_FIELDS:
        out.append(
            "source timing fields/order must be sequence, source_timestamp, clock_domain, age_ms"
        )
    if list(source_timing["feature_sets"]) != EXPECTED_SOURCE_TIMING_FEATURE_SETS:
        out.append("source timing feature-set order/content mismatch")
    if source_timing["required_feature_sets_by_source_class"] != (
        EXPECTED_SOURCE_TIMING_BY_SOURCE_CLASS
    ):
        out.append("source timing requirements by source class mismatch")
    temporal_feature_keys = [
        key
        for feature_set in source_timing["feature_sets"].values()
        for key in feature_set.values()
    ] + [source_timing["cross_modal_skew_feature_key"]]
    if len(temporal_feature_keys) != len(set(temporal_feature_keys)):
        out.append("source timing feature keys must be unique")
    if dataset_timestamp["feature_key"] in temporal_feature_keys:
        out.append("logical dataset timestamp must not be reused as source timing metadata")
    classified = set(dataset["feature_classification"]["provenance_only"])
    missing_temporal = sorted(set(temporal_feature_keys) - classified)
    if missing_temporal:
        out.append(
            f"source timing features missing provenance_only classification: {missing_temporal}"
        )

    profiles = temporal["source_profiles"]
    for sid, source in dataset["sources"].items():
        profile = profiles.get(source.get("temporal_profile"), {})
        if profile.get("runtime") != source["runtime"] or source["source_class"] not in profile.get(
            "source_classes", []
        ):
            out.append(f"source {sid}: temporal profile selector mismatch")
        bindings = source.get("camera_bindings", [])
        if [b["canonical_feature_key"] for b in bindings] != camera_features or len(
            {b["physical_source_name"] for b in bindings}
        ) != 3:
            out.append(f"source {sid}: three distinct physical camera bindings required in order")
        if source["schema_fingerprint_sha256"] != canonical_training_schema_fingerprint(d):
            out.append(f"source {sid}: canonical three-camera fingerprint mismatch")
        if source["processor_contract_revision"] != dataset["policy_data_contract_revision"]:
            out.append(f"source {sid}: D0 profile revision mismatch")
        if not source.get("preprocessing_revision") or not source.get("calibration_artifact_ids"):
            out.append(f"source {sid}: preprocessing/calibration admission missing")
        for aid in source.get("calibration_artifact_ids", []):
            if d["artifacts"].get(aid, {}).get("kind") != "calibration":
                out.append(f"source {sid}: unregistered calibration artifact {aid}")
    if accepted(d, "D0"):
        if eid != "gate_d0_v4_causality" or eid not in d["gates"]["D0"]["evidence_ids"]:
            out.append("D0 v4 requires its registered v4 causality evidence attached to D0")
        elif ev and not set(ev["artifact_ids"]) <= set(d["gates"]["D0"]["artifact_ids"]):
            out.append("D0 v4 causality artifacts must be attached to D0")

    expected_fingerprint = canonical_training_schema_fingerprint(d)
    if dataset["common_training_view"]["schema_fingerprint_sha256"] != expected_fingerprint:
        out.append(
            f"D0 common training schema fingerprint mismatch: expected {expected_fingerprint}"
        )
    return out


def canonical_training_schema(d):
    """Return the exact ordered feature specification used by the project hash."""
    dataset = d["dataset"]
    state = dataset["observation_contract"]["state"]
    action = dataset["action_label_pipeline"]["dataset_action"]
    ordered_features = [
        {
            "feature_key": state["feature_key"],
            "dtype": state["dtype"],
            "shape": state["shape"],
            "names": state["names"],
            "units": state["units"],
            "semantics": state["semantics"],
        }
    ]
    for camera in dataset["cameras"].values():
        ordered_features.append(
            {
                "feature_key": camera["feature_key"],
                "storage_dtype": "video",
                "capture_dtype": camera["dtype"],
                "capture_shape": camera["shape"],
                "color_space": camera["color_space"],
                "policy_tensor_dtype": camera["policy_tensor_dtype"],
                "policy_tensor_shape": camera["policy_tensor_shape"],
                "policy_tensor_range": camera["policy_tensor_range"],
            }
        )
    ordered_features.append(
        {
            "feature_key": dataset["common_training_view"]["task_feature"],
            "dtype": "string",
            "semantic": "natural_language_instruction",
        }
    )
    ordered_features.append(
        {
            "feature_key": action["feature_key"],
            "dtype": action["dtype"],
            "shape": action["shape"],
            "names": action["names"],
            "units": action["units"],
            "semantics": action["semantics"],
        }
    )
    return ordered_features


def canonical_training_schema_fingerprint(d):
    """Hash only the ordered, operational common-training feature specification."""
    encoded = json.dumps(
        canonical_training_schema(d), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_eval_binding(d, name):
    out = []
    run = d["evaluation"].get(name)
    if run is None:
        return [f"{name}: run manifest missing"]
    sim = "isaac" if name == "isaac_run" else "mujoco"
    task = d["simulation"][sim]["task"]
    if (run["task_id"], run["task_revision"]) != (task["task_id"], task["revision"]):
        out.append(f"{name}: run task does not match resolved {sim} task")
    shared = d["evaluation"]["shared_policy_contract_revision"]
    if shared and run["policy_contract_revision"] != shared:
        out.append(
            f"{name}: policy contract revision does not match evaluation.shared_policy_contract_revision"
        )
    return out


def validate_real_rollout(d):
    out = []
    rr = d["real_rollout"]
    exp = {
        "checkpoint_artifact_id": "checkpoint",
        "policy_config_artifact_id": "policy_config",
        "preprocessor_artifact_id": "processor_config",
        "postprocessor_artifact_id": "processor_config",
        "start_stop_procedure_artifact_id": "safety_report",
        "accepted_command_log_artifact_id": "hardware_log",
        "result_artifact_id": "rollout_result",
    }
    for f, k in exp.items():
        aid = rr[f]
        a = d["artifacts"].get(aid) if aid else None
        if not a:
            out.append(f"real_rollout: unknown/missing artifact {f}={aid}")
        elif a["kind"] != k:
            out.append(f"real_rollout: artifact {aid} must be {k}")
    cp = d["artifacts"].get(rr["checkpoint_artifact_id"]) if rr["checkpoint_artifact_id"] else None
    if cp and rr["checkpoint_sha256"] and cp["sha256"].lower() != rr["checkpoint_sha256"].lower():
        out.append("real_rollout checkpoint SHA mismatch")
    ev = (
        d["evidence"].get(rr["authorization_evidence_id"])
        if rr["authorization_evidence_id"]
        else None
    )
    if not ev or ev["kind"] != "human_gate" or ev["status"] != "pass":
        out.append("real_rollout requires PASS human authorization evidence")
    a = d["evaluation"]["isaac_run"]
    m = d["evaluation"]["mujoco_run"]
    if (
        a
        and rr["checkpoint_sha256"]
        and rr["checkpoint_sha256"].lower() != a["checkpoint_sha256"].lower()
    ):
        out.append("real_rollout checkpoint was not the checkpoint accepted by Isaac eval")
    if (
        m
        and rr["checkpoint_sha256"]
        and rr["checkpoint_sha256"].lower() != m["checkpoint_sha256"].lower()
    ):
        out.append("real_rollout checkpoint was not the checkpoint accepted by MuJoCo eval")
    return out


def validate_generation_summary(d):
    g = d["simulation"]["isaac"]["generator"]["report_summary"]
    out = []
    if all(isinstance(g[k], int) for k in ("attempted", "successful", "rejected")):
        if g["attempted"] < g["successful"] + g["rejected"]:
            out.append("generation report attempted < successful + rejected")
    return out


def mandatory(rule, d):
    return rule.get("mandatory") is True or (
        rule.get("mandatory_if") and get_path(d, rule["mandatory_if"]) is True
    )


def accepted(d, g):
    return d["gates"][g]["state"] == "accepted"


def ev_kinds(d, g):
    return {
        d["evidence"][e]["kind"]
        for e in d["gates"][g]["evidence_ids"]
        if e in d["evidence"] and d["evidence"][e]["status"] == "pass"
    }


def art_kinds(d, g):
    return {d["artifacts"][a]["kind"] for a in d["gates"][g]["artifact_ids"] if a in d["artifacts"]}


def validate_gates(d, rules):
    out = []
    if set(d["gates"]) != set(rules):
        return ["contract gate IDs and gate_rules IDs differ"]
    for gid, g in d["gates"].items():
        # Referential integrity applies even before a gate is ready for acceptance.
        for eid in g["evidence_ids"]:
            if eid not in d["evidence"]:
                out.append(f"gate {gid}: unknown evidence {eid}")
        for aid in g["artifact_ids"]:
            if aid not in d["artifacts"]:
                out.append(f"gate {gid}: unknown artifact {aid}")
        if g["state"] != "accepted":
            continue
        r = rules[gid]
        deps = list(r.get("prerequisites", []))
        for cond, ids in r.get("conditional_prerequisites", {}).items():
            if get_path(d, cond) is True:
                deps += ids
        for dep in deps:
            if not accepted(d, dep):
                out.append(f"gate {gid}: prerequisite {dep} is not accepted")
        for p in r.get("required_paths", []):
            if not resolved(get_path(d, p)):
                out.append(f"gate {gid}: unresolved required path {p}")
        for p in r.get("required_nonempty_paths", []):
            if not nonempty(get_path(d, p)):
                out.append(f"gate {gid}: empty required path {p}")
        for e in g["evidence_ids"]:
            if e in d["evidence"] and d["evidence"][e]["status"] != "pass":
                out.append(f"gate {gid}: evidence {e} is not PASS")
        ek = ev_kinds(d, gid)
        ak = art_kinds(d, gid)
        for k in r.get("required_evidence_kinds", []):
            if k not in ek:
                out.append(f"gate {gid}: missing PASS evidence kind {k}")
        for k in r.get("required_artifact_kinds", []):
            if k not in ak:
                out.append(f"gate {gid}: missing artifact kind {k}")
        if r.get("human_evidence_required") and "human_gate" not in ek:
            out.append(f"gate {gid}: human evidence required")
        if r.get("hardware_evidence_required") and "hardware_observation" not in ek:
            out.append(f"gate {gid}: hardware evidence required")
        ds = r.get("required_dataset_source")
        if ds:
            matches = [
                (sid, src)
                for sid, src in d["dataset"]["sources"].items()
                if src["runtime"] == ds["runtime"] and src["source_class"] == ds["source_class"]
            ]
            if not matches:
                out.append(f"gate {gid}: required dataset source missing: {ds}")
            elif matches[0][1]["manifest_artifact_id"] not in g["artifact_ids"]:
                out.append(
                    f"gate {gid}: dataset source manifest must be attached to gate artifacts"
                )
        if r.get("required_dataset_source_automated"):
            matches = [
                (sid, src)
                for sid, src in d["dataset"]["sources"].items()
                if src["runtime"] == r.get("required_dataset_source_runtime", "isaac")
                and src["source_class"] in AUTOMATED
            ]
            if not matches:
                out.append(f"gate {gid}: automated dataset source missing")
            elif matches[0][1]["manifest_artifact_id"] not in g["artifact_ids"]:
                out.append(
                    f"gate {gid}: automated dataset source manifest must be attached to gate artifacts"
                )
        for path in r.get("required_paths", []):
            if path.endswith("_evidence_id"):
                eid = get_path(d, path)
                if (
                    d["evidence"].get(eid, {}).get("status") != "pass"
                    or eid not in g["evidence_ids"]
                ):
                    out.append(f"gate {gid}: required PASS evidence not attached: {path}")
            if path.endswith("demonstration_quality_envelope_artifact_id"):
                aid = get_path(d, path)
                if aid not in d["artifacts"] or aid not in g["artifact_ids"]:
                    out.append(f"gate {gid}: demonstration quality envelope not attached")
        sp = r.get("special_check")
        if sp == "cross_sim":
            out += validate_cross_sim(d)
        elif sp == "dataset_materialization":
            out += validate_materialization(d)
        elif sp == "real_rollout":
            out += validate_real_rollout(d)
        elif sp == "dataset_contract":
            out += validate_dataset_contract(d)
        elif sp == "eval_isaac":
            out += validate_eval_binding(d, "isaac_run")
        elif sp == "eval_mujoco":
            out += validate_eval_binding(d, "mujoco_run")
    return out


def derive_final(d, rules):
    blockers = []
    if d["migration"]["state"] not in {"complete", "not_required"}:
        blockers.append("migration")
    for gid, r in rules.items():
        if mandatory(r, d) and not accepted(d, gid):
            blockers.append(gid)
    return not blockers, blockers


def validate_contract(contract_path: Path, rules_path: Path | None = None):
    d = load_yaml(contract_path)
    root = project_root(contract_path)
    schema_path = contract_path.parent / "resolved_contract.schema.json"
    rules = load_yaml(rules_path or contract_path.parent / "gate_rules.yaml")
    errors = validate_schema(d, schema_path)
    if errors:
        return errors, False, ["schema-invalid"]
    for p, v in walk(d):
        if isinstance(v, str) and v.startswith(PLACEHOLDER_PREFIXES):
            errors.append(f"{p}: legacy magic placeholder forbidden")
    errors += (
        validate_profiles(d)
        + validate_teleop_dependencies(d)
        + validate_process_architecture(d)
        + validate_artifacts(d, root)
        + validate_evidence(d)
        + validate_generic_refs(d)
        + validate_migration(d)
        + validate_feature_contract(d)
        + validate_timing(d)
        + validate_eval_run(d, "isaac_run")
        + validate_eval_run(d, "mujoco_run")
        + validate_generation_summary(d)
        + validate_gates(d, rules)
    )
    if (
        d["project"]["training_ready_claim"]
        != d["requirements"]["capabilities"]["training_compatibility_smoke"]
    ):
        errors.append("training_ready_claim must equal training_compatibility_smoke requirement")
    if d["requirements"]["capabilities"]["hil"] != d["hil"]["required"]:
        errors.append("requirements.capabilities.hil must equal hil.required")
    ready, blockers = derive_final(d, rules)
    asserted = d["release"]["final_rc_state"] == "ready"
    if asserted != ready:
        errors.append(
            f"release.final_rc_state inconsistent with derived readiness: asserted={d['release']['final_rc_state']} derived={'ready' if ready else 'not_ready'} blockers={blockers}"
        )
    return errors, ready, blockers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("contract", nargs="?", default="configs/resolved_contract.yaml")
    ap.add_argument("--rules")
    ap.add_argument("--require-final-rc", action="store_true")
    ap.add_argument("--require-gate")
    args = ap.parse_args()
    try:
        errors, ready, blockers = validate_contract(
            Path(args.contract), Path(args.rules) if args.rules else None
        )
    except Exception as exc:
        print(f"VALIDATOR INTERNAL/DEPENDENCY ERROR: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("CONTRACT INVALID")
        [print("-", e) for e in errors]
        return 1
    print("CONTRACT STRUCTURALLY VALID")
    print("CONTRACT SEMANTICALLY VALID")
    if ready:
        print("FINAL RC READY")
    else:
        print("FINAL RC NOT READY")
        print("BLOCKERS:", ", ".join(blockers))
    if args.require_gate:
        d = load_yaml(Path(args.contract))
        if (
            args.require_gate not in d["gates"]
            or d["gates"][args.require_gate]["state"] != "accepted"
        ):
            print(f"GATE NOT ACCEPTED: {args.require_gate}", file=sys.stderr)
            return 1
    if args.require_final_rc and not ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
