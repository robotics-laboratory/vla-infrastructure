from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

from tools.d0_causal import CausalTransactionValidator, Epoch, PayloadIdentity, SourceIdentity


PATH = Path(__file__).parents[1] / "docs/experiments/20260921_vr_architecture_bakeoff/deferred_binding.py"
SPEC = importlib.util.spec_from_file_location("deferred_binding", PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def source(obs, tick, *, reset=0, reference=0, session=0, render=None):
    return module.RenderSourceIdentity(obs, tick, reset, reference, session, obs, 2 * obs, render or obs + 10)


def cameras(extraction, *, stale_role=None):
    return tuple(
        module.CameraExtractionIdentity(role, extraction if role != stale_role else extraction - 1,
                                        extraction, extraction)
        for role in module.ROLES
    )


def images():
    return {role: np.full((480, 640, 3), i, dtype=np.uint8) for i, role in enumerate(module.ROLES)}


def test_one_tick_binding_is_immutable_and_action_index_is_not_shifted():
    binder = module.OneTickDeferredBinder()
    actions = {}
    for tick in range(4):
        identity = source(tick, tick)
        binder.prepare(identity, tuple(float(tick * 100 + i) for i in range(14)))
        actions[tick] = tuple(float(1000 + tick * 100 + i) for i in range(14))
        snapshot = binder.complete(
            observed_source=identity,
            availability_control_tick=tick + 1,
            availability_render_generation=tick + 11,
            camera_identities=cameras(tick + 1),
            rgb=images(),
        )
        assert snapshot.source.control_tick_id == tick
        assert snapshot.state[0] == tick * 100
        assert actions[snapshot.source.control_tick_id][0] == 1000 + tick * 100
        assert all(not image.flags.writeable for image in snapshot.rgb)


@pytest.mark.parametrize("reason", ["reset", "recenter", "session_recreation", "runtime_reset"])
def test_epoch_change_aborts_pending(reason):
    binder = module.OneTickDeferredBinder()
    identity = source(0, 0)
    binder.prepare(identity, tuple(float(i) for i in range(14)))
    binder.abort(reason)
    with pytest.raises(module.DeferredBindingViolation, match="no_pending_observation"):
        binder.complete(observed_source=identity, availability_control_tick=1,
                        availability_render_generation=11, camera_identities=cameras(1), rgb=images())


def test_epoch_invalidation_restarts_camera_identity_floors():
    binder = module.OneTickDeferredBinder()
    first = source(0, 0, reset=1)
    binder.prepare(first, tuple(float(i) for i in range(14)))
    binder.complete(observed_source=first, availability_control_tick=1,
                    availability_render_generation=11, camera_identities=cameras(20), rgb=images())
    pending = source(1, 1, reset=1)
    binder.prepare(pending, tuple(float(i) for i in range(14)))
    binder.invalidate_epoch("reset_epoch_changed")
    restarted = source(2, 2, reset=2)
    binder.prepare(restarted, tuple(float(i) for i in range(14)))
    snapshot = binder.complete(observed_source=restarted, availability_control_tick=3,
                               availability_render_generation=13,
                               camera_identities=cameras(1), rgb=images())
    assert snapshot.source.reset_epoch == 2
    assert binder.invalidations == ["reset_epoch_changed"]


def test_missing_or_disagreeing_camera_fails_closed():
    binder = module.OneTickDeferredBinder()
    identity = source(0, 0)
    binder.prepare(identity, tuple(float(i) for i in range(14)))
    with pytest.raises(module.DeferredBindingViolation, match="incomplete_or_reordered"):
        binder.complete(observed_source=identity, availability_control_tick=1,
                        availability_render_generation=11, camera_identities=cameras(1)[:2], rgb=images())
    binder.abort("failed_bundle")
    binder.prepare(source(1, 1), tuple(float(i) for i in range(14)))
    disagree = list(cameras(2))
    disagree[-1] = module.CameraExtractionIdentity("scene", 2, 2, 3)
    with pytest.raises(module.DeferredBindingViolation, match="camera_extraction_disagreement"):
        binder.complete(observed_source=source(1, 1), availability_control_tick=2,
                        availability_render_generation=12, camera_identities=tuple(disagree), rgb=images())


def test_wrong_stale_and_duplicate_sources_fail_closed():
    binder = module.OneTickDeferredBinder()
    identity = source(1, 1)
    binder.prepare(identity, tuple(float(i) for i in range(14)))
    with pytest.raises(module.DeferredBindingViolation, match="unexpected_image_source"):
        binder.complete(observed_source=source(0, 0), availability_control_tick=2,
                        availability_render_generation=12, camera_identities=cameras(1), rgb=images())
    binder.abort("wrong_source")
    binder.prepare(source(2, 2), tuple(float(i) for i in range(14)))
    binder.complete(observed_source=source(2, 2), availability_control_tick=3,
                    availability_render_generation=13, camera_identities=cameras(2), rgb=images())
    binder.prepare(source(3, 3), tuple(float(i) for i in range(14)))
    with pytest.raises(module.DeferredBindingViolation, match="duplicate_or_stale"):
        binder.complete(observed_source=source(3, 3), availability_control_tick=4,
                        availability_render_generation=14,
                        camera_identities=cameras(3, stale_role="right_wrist"), rgb=images())
    binder.abort("one_camera_stale")
    with pytest.raises(module.DeferredBindingViolation, match="duplicate_observation_identity"):
        binder.prepare(source(2, 4, render=15), tuple(float(i) for i in range(14)))


def test_render_request_and_terminal_drain_rules():
    binder = module.OneTickDeferredBinder()
    identity = source(0, 0, render=20)
    binder.prepare(identity, tuple(float(i) for i in range(14)))
    with pytest.raises(module.DeferredBindingViolation, match="availability_tick_mismatch"):
        binder.complete(observed_source=identity, availability_control_tick=0,
                        availability_render_generation=21, camera_identities=cameras(1), rgb=images())
    binder.abort("active_tick_mismatch")
    terminal = source(1, 1, render=21)
    binder.prepare(terminal, tuple(float(i) for i in range(14)))
    with pytest.raises(module.DeferredBindingViolation, match="render_generation_slip"):
        binder.complete(observed_source=terminal, availability_control_tick=1,
                        availability_render_generation=23, camera_identities=cameras(2),
                        rgb=images(), drain=True)
    snapshot = binder.complete(observed_source=terminal, availability_control_tick=1,
                               availability_render_generation=22, camera_identities=cameras(2),
                               rgb=images(), drain=True)
    assert snapshot.source == terminal
    with pytest.raises(module.DeferredBindingViolation, match="duplicate_render_request_identity"):
        binder.prepare(source(2, 2, render=21), tuple(float(i) for i in range(14)))


def test_existing_validator_accepts_only_after_deferred_snapshot_is_complete():
    binder = module.OneTickDeferredBinder()
    source_identity = source(0, 0)
    binder.prepare(source_identity, tuple(float(i) for i in range(14)))
    snapshot = binder.complete(observed_source=source_identity, availability_control_tick=1,
                               availability_render_generation=11, camera_identities=cameras(1),
                               rgb=images())
    epoch = Epoch("run", "episode", "automated", 0, 0, "generator-epoch")
    observation_payload = (
        snapshot.state_sha256 + ":" + ":".join(snapshot.images.rgb_sha256)
    ).encode()
    action_payload = b"action-0"
    observation = PayloadIdentity.bind(epoch, 0, "observation-0", observation_payload)
    action = PayloadIdentity.bind(epoch, 0, "action-0", action_payload)
    names = ("simulation.state_generation", "camera.left_wrist", "camera.right_wrist",
             "camera.scene", "generator.decision")
    sources = tuple(
        SourceIdentity(name, PayloadIdentity.bind(epoch, 0, f"source-{i}", observation_payload), i + 1)
        for i, name in enumerate(names)
    )
    validator = CausalTransactionValidator("isaac", "scripted_expert", epoch)
    prepared = validator.prepare(observation, action, sources,
                                 observation_payload=observation_payload, action_payload=action_payload,
                                 generator_revision="probe-v1", generator_state="state-0", generator_seed=7)
    successor_payload = b"successor-1"
    validator.complete_transition(
        prepared,
        PayloadIdentity.bind(epoch, 0, "native-0", b"native-0"),
        "transition-0",
        PayloadIdentity.bind(epoch, 1, "observation-1", successor_payload),
        successful=True,
    )
    validator.commit(prepared, observation_payload=observation_payload, action_payload=action_payload)
    assert validator.accepted_transactions == 1
