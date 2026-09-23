"""Offline v4 proof: distinguishable payloads, transactions, epochs and profiles."""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import copy

import pytest
import yaml

from tools.d0_causal import (
    CausalTransactionValidator,
    Epoch,
    PayloadIdentity,
    SourceIdentity,
    SIM_SOURCES,
    XR_SOURCES,
    select_temporal_profile,
)
from tools.d0_temporal import PhysicalTimingValidator, SourceTiming, TemporalLimits
from tools.validate_resolved_contract import (
    canonical_training_schema_fingerprint,
    validate_dataset_contract,
    validate_gates,
)

ROOT = Path(__file__).resolve().parents[1]


def contract():
    return yaml.safe_load((ROOT / "configs/resolved_contract.yaml").read_text())


def validator(runtime="isaac", source_class="human_vr"):
    physical = None
    if runtime == "real":
        c = contract()
        timing = c["dataset"]["temporal_semantics"]["source_timing"]
        required = tuple(timing["required_feature_sets_by_source_class"]["human_vr"])
        physical = PhysicalTimingValidator(
            feature_sets=timing["feature_sets"],
            required_sources=required,
            limits=TemporalLimits.from_resolved_contract(c, required),
            accepted_clock_domains=("host_monotonic",),
        )
    return CausalTransactionValidator(
        runtime,
        source_class,
        Epoch("run", "episode", "source", 0, 0, "session0"),
        physical=physical,
    )


def identity(v, tick, role, payload):
    return PayloadIdentity.bind(v.epoch, tick, f"{role}-{tick}-{v.epoch}", payload)


def bundle(v, tick=0):
    obs_bytes, action_bytes = str(tick).encode(), str(1000 + tick).encode()
    obs, act = identity(v, tick, "obs", obs_bytes), identity(v, tick, "action", action_bytes)
    kwargs = dict(observation_payload=obs_bytes, action_payload=action_bytes)
    if v.profile == "isaac_automated_v4":
        names = SIM_SOURCES + ("generator.decision",)
        kwargs.update(
            generator_revision="pinned-revision", generator_state="state-digest", generator_seed=42
        )
    elif v.physical:
        names = v.physical.required_sources
        kwargs.update(
            tracking_valid=True,
            selection_timestamp=100.020 + tick,
            source_timing={
                name: SourceTiming(tick, 100.0 + tick, "host_monotonic") for name in names
            },
        )
    else:
        names = SIM_SOURCES + XR_SOURCES
        kwargs["tracking_valid"] = True
    sources = tuple(
        SourceIdentity(name, identity(v, tick, name, name.encode()), tick) for name in names
    )
    return obs, act, sources, kwargs


def prepare(v, tick=0):
    obs, act, sources, kwargs = bundle(v, tick)
    return v.prepare(obs, act, sources, **kwargs)


def complete(v, p, tick=0, **kwargs):
    return v.complete_transition(
        p,
        identity(v, tick, "native", b"clipped_native_not_label"),
        f"transition-{tick}",
        identity(v, tick + 1, "obs", str(tick + 1).encode()),
        successful=True,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("runtime", "source", "expected"),
    [
        ("isaac", "human_vr", "isaac_human_vr_v4"),
        *[
            ("isaac", s, "isaac_automated_v4")
            for s in ("scripted_expert", "planner", "datagen", "policy_generated")
        ],
        ("real", "human_vr", "real_human_vr_physical_v4"),
    ],
)
def test_profile_dispatch(runtime, source, expected):
    assert select_temporal_profile(runtime, source) == expected


@pytest.mark.parametrize(
    ("runtime", "source"),
    [
        ("real", "planner"),
        ("mujoco", "human_vr"),
        ("isaac", "replay_or_transform"),
        ("isaac", "human_vr_typo"),
    ],
)
def test_unadmitted_profile_rejected(runtime, source):
    with pytest.raises(ValueError, match="no admitted temporal profile"):
        select_temporal_profile(runtime, source)


@pytest.mark.parametrize(
    ("runtime", "source"), [("isaac", "human_vr"), ("isaac", "planner"), ("real", "human_vr")]
)
def test_causal_trajectory_exact_pairing_and_label_native_separation(runtime, source):
    v = validator(runtime, source)
    pairs = []
    for tick in range(4):
        p = prepare(v, tick)
        result = complete(v, p, tick)
        assert result.native_command.sha256 != p.dataset_action.sha256
        assert (
            v.commit(
                p, observation_payload=str(tick).encode(), action_payload=str(1000 + tick).encode()
            )
            == result
        )
        pairs.append((tick, 1000 + tick))
    assert pairs == [(0, 1000), (1, 1001), (2, 1002), (3, 1003)]
    assert v.accepted_transactions == 4


@pytest.mark.parametrize("shift", [-1, 1])
def test_reject_action_from_adjacent_tick(shift):
    v = validator()
    obs, act, sources, kwargs = bundle(v, 1)
    wrong = identity(v, 1 + shift, "action", str(1001 + shift).encode())
    kwargs["action_payload"] = str(1001 + shift).encode()
    with pytest.raises(ValueError, match="tick_mismatch"):
        v.prepare(obs, wrong, sources, **kwargs)


@pytest.mark.parametrize("field", ["observation_payload", "action_payload"])
def test_reject_payload_substitution_at_prepare_and_commit(field):
    v = validator()
    obs, act, sources, kwargs = bundle(v)
    wrong = dict(kwargs)
    wrong[field] = b"B"
    with pytest.raises(ValueError, match="payload_substitution"):
        v.prepare(obs, act, sources, **wrong)
    p = v.prepare(obs, act, sources, **kwargs)
    complete(v, p)
    payloads = dict(observation_payload=b"0", action_payload=b"1000")
    payloads[field] = b"B"
    with pytest.raises(ValueError, match="payload_substitution"):
        v.commit(p, **payloads)
    assert v.accepted_transactions == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "other"),
        ("episode_id", "other"),
        ("source_id", "other"),
        ("reset_epoch", 1),
        ("control_reference_epoch", 1),
        ("source_epoch", "session1"),
    ],
)
def test_epoch_crossing_rejected_in_action_and_completion(field, value):
    v = validator()
    obs, act, sources, kwargs = bundle(v)
    other = replace(v.epoch, **{field: value})
    with pytest.raises(ValueError, match="epoch_crossing"):
        v.prepare(obs, replace(act, epoch=other), sources, **kwargs)
    p = v.prepare(obs, act, sources, **kwargs)
    with pytest.raises(ValueError, match="epoch_crossing"):
        v.complete_transition(
            p,
            replace(identity(v, 0, "native", b"n"), epoch=other),
            "transition",
            identity(v, 1, "obs", b"1"),
            successful=True,
        )


@pytest.mark.parametrize(
    "field,value",
    [("reset_epoch", 1), ("control_reference_epoch", 1), ("source_epoch", "session1")],
)
def test_epoch_change_invalidates_prepared_transaction(field, value):
    v = validator()
    old = v.epoch
    p = prepare(v)
    v.begin_epoch(replace(old, **{field: value}))
    with pytest.raises(ValueError, match="transaction_not_pending"):
        complete(v, p)
    with pytest.raises(ValueError, match="epoch_reuse"):
        v.begin_epoch(old)


def test_transition_order_duplicate_commit_and_immutable_records():
    v = validator()
    p = prepare(v)
    with pytest.raises(FrozenInstanceError):
        p.observation = identity(v, 0, "bad", b"bad")
    with pytest.raises(ValueError, match="transition_not_completed"):
        v.commit(p, observation_payload=b"0", action_payload=b"1000")
    with pytest.raises(ValueError, match="tick_mismatch"):
        complete(v, p, 1)
    complete(v, p)
    with pytest.raises(ValueError, match="transition_incomplete_or_repeated"):
        complete(v, p)
    v.commit(p, observation_payload=b"0", action_payload=b"1000")
    with pytest.raises(ValueError, match="transaction_not_pending"):
        v.commit(p, observation_payload=b"0", action_payload=b"1000")
    p1 = prepare(v, 1)
    with pytest.raises(ValueError, match="transition_reuse"):
        v.complete_transition(
            p1,
            identity(v, 1, "native", b"n"),
            "transition-0",
            identity(v, 2, "obs", b"2"),
            successful=True,
        )


def test_abort_failure_forged_token_and_successor_pairing():
    v = validator()
    p = prepare(v)
    with pytest.raises(ValueError, match="transaction_not_pending"):
        complete(v, replace(p))
    with pytest.raises(ValueError, match="transition_incomplete_or_repeated"):
        v.complete_transition(
            p,
            identity(v, 0, "native", b"n"),
            "failure",
            identity(v, 1, "obs", b"1"),
            successful=False,
        )
    v.abort()
    with pytest.raises(ValueError, match="transaction_not_pending"):
        complete(v, p)
    with pytest.raises(ValueError, match="tick_reuse"):
        prepare(v)
    p = prepare(v, 1)
    complete(v, p, 1)
    v.commit(p, observation_payload=b"1", action_payload=b"1001")
    obs, act, sources, kwargs = bundle(v, 2)
    with pytest.raises(ValueError, match="successor_pairing_mismatch"):
        v.prepare(replace(obs, payload_id="different"), act, sources, **kwargs)


@pytest.mark.parametrize(
    "mutate",
    [
        "repeat_sequence",
        "regress_sequence",
        "reuse_payload_id",
        "wrong_epoch",
        "wrong_tick",
        "missing_scene",
    ],
)
def test_source_identity_reuse_and_camera_barrier(mutate):
    v = validator()
    p = prepare(v, 1)
    complete(v, p, 1)
    v.commit(p, observation_payload=b"1", action_payload=b"1001")
    obs, act, sources, kwargs = bundle(v, 2)
    sources = list(sources)
    if mutate == "repeat_sequence":
        sources[0] = replace(sources[0], sequence=1)
    if mutate == "regress_sequence":
        sources[0] = replace(sources[0], sequence=0)
    if mutate == "reuse_payload_id":
        sources[0] = replace(
            sources[0], sample=replace(sources[0].sample, payload_id=p.sources[0].sample.payload_id)
        )
    if mutate == "wrong_epoch":
        sources[0] = replace(
            sources[0], sample=replace(sources[0].sample, epoch=replace(v.epoch, reset_epoch=1))
        )
    if mutate == "wrong_tick":
        sources[0] = replace(sources[0], sample=replace(sources[0].sample, control_tick_id=1))
    if mutate == "missing_scene":
        sources = [s for s in sources if s.name != "camera.scene"]
    with pytest.raises(ValueError):
        v.prepare(obs, act, tuple(sources), **kwargs)


def test_profile_isolation():
    human = validator()
    p = prepare(human)
    assert p.physical is None
    auto = validator("isaac", "planner")
    p = prepare(auto)
    assert not any(s.name.startswith("xr.") for s in p.sources)
    assert p.generator == ("pinned-revision", "state-digest", 42)
    real = validator("real")
    obs, act, sources, kwargs = bundle(real)
    kwargs.pop("source_timing")
    with pytest.raises(ValueError, match="missing_timing_metadata"):
        real.prepare(obs, act, sources, **kwargs)
    auto.abort()
    obs, act, sources, kwargs = bundle(auto, 1)
    kwargs["tracking_valid"] = True
    with pytest.raises(ValueError, match="unexpected_xr"):
        auto.prepare(obs, act, sources, **kwargs)
    human.abort()
    obs, act, sources, kwargs = bundle(human, 1)
    kwargs["tracking_valid"] = False
    with pytest.raises(ValueError, match="tracking_invalid"):
        human.prepare(obs, act, sources, **kwargs)


@pytest.mark.parametrize(
    ("name", "timestamp", "domain", "reason"),
    [
        ("observation.images.scene", 99.9, "host_monotonic", "stale_source_sample"),
        ("xr.left_pose", 99.9, "host_monotonic", "stale_source_sample"),
        ("source_action", 100.03, "host_monotonic", "future_source_sample"),
        ("observation.state", 100.0, "device_clock", "clock_domain_mismatch"),
    ],
)
def test_real_physical_regression_through_causal_validator(name, timestamp, domain, reason):
    v = validator("real")
    obs, act, sources, kwargs = bundle(v)
    kwargs["source_timing"][name] = SourceTiming(0, timestamp, domain)
    with pytest.raises(ValueError, match=reason):
        v.prepare(obs, act, sources, **kwargs)


def test_real_xr_missing_and_physical_identity_binding():
    v = validator("real")
    obs, act, sources, kwargs = bundle(v)
    kwargs["source_timing"].pop("xr.left_pose")
    with pytest.raises(ValueError, match="missing_timing_metadata"):
        v.prepare(obs, act, sources, **kwargs)
    obs, act, sources, kwargs = bundle(v)
    kwargs["source_timing"]["source_action"] = SourceTiming(9, 100, "host_monotonic")
    with pytest.raises(ValueError, match="physical_identity_mismatch"):
        v.prepare(obs, act, sources, **kwargs)


def test_three_camera_schema_fingerprint_order_and_preserved_gates():
    c = contract()
    d = c["dataset"]
    assert list(d["cameras"]) == ["left_wrist", "right_wrist", "scene"]
    ordered = [
        "observation.state",
        "observation.images.left_wrist",
        "observation.images.right_wrist",
        "observation.images.scene",
        "task",
        "action",
    ]
    assert (
        d["common_training_view"]["input_features"] + d["common_training_view"]["target_features"]
        == ordered
    )
    assert d["observation_contract"]["policy_whitelist"] == ordered[:-1]
    assert (
        canonical_training_schema_fingerprint(c)
        == d["common_training_view"]["schema_fingerprint_sha256"]
    )
    for cam in d["cameras"].values():
        assert (cam["dtype"], cam["shape"], cam["color_space"]) == ("uint8", [480, 640, 3], "RGB")
        assert (
            cam["policy_tensor_dtype"],
            cam["policy_tensor_shape"],
            cam["policy_tensor_range"],
        ) == ("float32", [3, 480, 640], [0, 1])
        assert cam["canonical_transforms"] == dict(crop=False, resize=False, flip=False)
    assert d["sources"] == {}
    assert [c["gates"][g]["state"] for g in ("D0", "S0", "S1", "S2", "D1")] == [
        "accepted",
        "accepted",
        "accepted",
        "unresolved",
        "unresolved",
    ]
    rules = yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text())
    assert not validate_gates(c, rules)
    c["gates"]["D0"]["state"] = "unresolved"
    assert "gate S0: prerequisite D0 is not accepted" in validate_gates(c, rules)


def test_swapped_camera_order_is_invalid_even_if_rehashed():
    c = contract()
    cams = c["dataset"]["cameras"]
    c["dataset"]["cameras"] = {name: cams[name] for name in ("scene", "left_wrist", "right_wrist")}
    c["dataset"]["common_training_view"]["schema_fingerprint_sha256"] = (
        canonical_training_schema_fingerprint(c)
    )
    assert (
        "D0 camera roles/order must be left_wrist, right_wrist, scene"
        in validate_dataset_contract(c)
    )


def test_source_admission_rejects_wrong_profile_and_duplicate_bindings():
    c = contract()
    d = c["dataset"]
    source = dict(
        runtime="real",
        source_class="human_vr",
        temporal_profile="isaac_human_vr_v4",
        camera_bindings=[
            dict(physical_source_name="same", canonical_feature_key=f"observation.images.{r}")
            for r in d["cameras"]
        ],
        schema_fingerprint_sha256=d["common_training_view"]["schema_fingerprint_sha256"],
        processor_contract_revision=d["policy_data_contract_revision"],
        preprocessing_revision="identity-v1",
        calibration_artifact_ids=["not_registered"],
    )
    d["sources"]["synthetic_probe"] = source
    errors = validate_dataset_contract(c)
    assert any("selector mismatch" in e for e in errors)
    assert any("distinct physical camera" in e for e in errors)
    assert any("unregistered calibration" in e for e in errors)
    assert contract()["dataset"]["sources"] == {}


def test_no_universal_isaac_age_prerequisite_and_real_limits_unchanged():
    c = contract()
    rules = yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text())
    for gate in ("D1", "G1"):
        assert not any(p.startswith("timing.max_") for p in rules[gate]["required_paths"])
    for key, value in [
        ("max_camera_age_ms", 75),
        ("max_joint_age_ms", 45),
        ("max_xr_age_ms", 75),
        ("max_policy_action_age_ms", 45),
        ("max_cross_modal_skew_ms", 75),
    ]:
        assert c["timing"][key] == value
        assert f"timing.{key}" in rules["R2"]["required_paths"]
    probe = copy.deepcopy(c)
    probe["gates"]["D1"]["state"] = "accepted"
    assert any("resolved_xr_identity" in e for e in validate_gates(probe, rules))


def test_real_facade_binds_actual_frame_and_defers_causal_commit_until_successor():
    import numpy as np
    from tools.d0_temporal import TemporalFrameRecorder, frame_payloads, temporal_feature_specs

    c = contract()
    timing = c["dataset"]["temporal_semantics"]["source_timing"]
    required = tuple(timing["required_feature_sets_by_source_class"]["human_vr"])

    class Writer:
        features = temporal_feature_specs(timing["feature_sets"], required)

        def __init__(self):
            self.frames = []

        def add_frame(self, frame):
            self.frames.append(frame)

    writer = Writer()
    recorder = TemporalFrameRecorder.from_resolved_contract(writer, c, source_class="human_vr")
    v = CausalTransactionValidator(
        "real", "human_vr", Epoch("run", "episode", "source", 0, 0, "session"), physical=recorder
    )
    frame = {
        "observation.state": np.zeros(14, dtype=np.float32),
        "action": np.full(14, 1000, dtype=np.float32),
        "task": "synthetic",
        **{
            f"observation.images.{role}": np.zeros((2, 2, 3), dtype=np.uint8)
            for role in ("left_wrist", "right_wrist", "scene")
        },
    }
    obs_bytes, action_bytes = frame_payloads(frame)
    _, _, sources, kwargs = bundle(v)
    kwargs.update(observation_payload=obs_bytes, action_payload=action_bytes)
    p = v.prepare(
        identity(v, 0, "obs", obs_bytes), identity(v, 0, "action", action_bytes), sources, **kwargs
    )
    altered = dict(frame)
    altered["observation.images.scene"] = np.ones((2, 2, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="payload_substitution"):
        recorder.commit_transaction_frame(altered, v, p)
    assert not writer.frames
    recorder.commit_transaction_frame(frame, v, p)
    assert len(writer.frames) == 1
    assert recorder.accepted_frames == 1
    assert v.accepted_transactions == 0
    with pytest.raises(ValueError, match="transition_not_completed"):
        v.commit(p, observation_payload=obs_bytes, action_payload=action_bytes)
    with pytest.raises(ValueError, match="invalid_persistence_phase"):
        recorder.commit_transaction_frame(frame, v, p)
    complete(v, p)
    v.commit(p, observation_payload=obs_bytes, action_payload=action_bytes)
    assert recorder.accepted_frames == 1
    assert v.accepted_transactions == 1


def test_physical_prepared_bundle_cannot_cross_reset_or_be_mutated():
    v = validator("real")
    physical = v.physical
    _, _, _, kwargs = bundle(v)
    p = physical.prepare_frame(
        kwargs["source_timing"], selection_timestamp=kwargs["selection_timestamp"]
    )
    with pytest.raises(TypeError):
        p.accepted["source_action"] = SourceTiming(1, 100, "host_monotonic")
    with pytest.raises(ValueError):
        p.enrichment["temporal.source_action.sequence"][0] = 9
    physical.reset_episode()
    with pytest.raises(ValueError, match="prepared_frame_order"):
        physical.accept(p)


def test_new_reset_epoch_can_start_sequences_at_zero_with_new_sample_identities():
    v = validator()
    p = prepare(v, 3)
    complete(v, p, 3)
    v.commit(p, observation_payload=b"3", action_payload=b"1003")
    v.begin_epoch(replace(v.epoch, reset_epoch=1))
    p = prepare(v, 0)
    complete(v, p, 0)
    v.commit(p, observation_payload=b"0", action_payload=b"1000")
    assert v.accepted_transactions == 2


def test_chain_break_preserves_epoch_counts_ticks_and_consumed_identities():
    v = validator()
    p = prepare(v, 0)
    complete(v, p, 0)
    v.commit(p, observation_payload=b"0", action_payload=b"1000")
    epoch, ids, ticks = v.epoch, set(v._ids), dict(v._ticks)
    v.break_observation_chain()
    assert v.epoch == epoch and v.accepted_transactions == 1
    assert v._ids == ids and v._ticks == ticks
    with pytest.raises(ValueError, match="tick_reuse"):
        prepare(v, 0)
    p = prepare(v, 3)
    v.break_observation_chain()
    with pytest.raises(ValueError, match="transaction_not_pending"):
        complete(v, p, 3)
    assert v.accepted_transactions == 1
    with pytest.raises(ValueError, match="tick_reuse"):
        prepare(v, 3)
    p = prepare(v, 4)
    complete(v, p, 4)
    v.commit(p, observation_payload=b"4", action_payload=b"1004")
    assert v.accepted_transactions == 2
