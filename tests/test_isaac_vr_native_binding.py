"""CPU negative checks for exact rendered-source/canonical-token joins."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from isaac_vr_native_binding import NativeSourceBinding, ROLES


def token(seq, step=None, epoch=1):
    step = 120 + 4 * seq if step is None else step
    return SimpleNamespace(capture_sequence=seq, physics_step=step, state_generation=step,
                           reset_epoch=epoch, scene_state_snapshot_id=f"snapshot:{seq}",
                           scene_state_snapshot_sha256=f"{seq:064x}")


def proof(pub=1, step=120, epoch=1):
    return {role: dict(role=role, publication_id=pub, physics_step=step, reset_epoch=epoch,
                       geometry_matched=True, frame_identifier={"frameNumber": 63},
                       compared_bodies=25, body_matrix_max_error=1e-6,
                       camera_matrix_max_error=1e-7) for role in ROLES}


def test_exact_historical_join_duplicate_and_immutable_input():
    b = NativeSourceBinding()
    first = token(0)
    b.register(first)
    first.scene_state_snapshot_id = "mutated caller object"
    row = b.bind(0, proof())
    b.register(token(1))
    duplicate = b.bind(1, proof())
    assert row["scene_state_snapshot_id"] == "snapshot:0"
    assert duplicate["current_capture_sequence"] == 1
    assert duplicate["actual_capture_sequence"] == 0
    assert duplicate["duplicate_source"]
    assert duplicate["observed_lag_physics_steps"] == 4
    assert duplicate["optical_quality"] == "not_requested"
    assert not duplicate["optical_alignment_proven"] and not duplicate["dataset_admissible"]
    row["scene_state_snapshot_id"] = "mutated output"
    assert b.bind(2, proof())["scene_state_snapshot_id"] == "snapshot:0"
    assert b.receipt()["duplicates"] == 2
    assert b.receipt()["unbound_retained"][0]["capture_sequence"] == 1


def test_clock_scope_cannot_be_advertised_as_full_body_proof():
    p = proof()
    for row in p.values():
        row.update(proof_scope="publication_clock_camera", body_geometry_checked=False, compared_bodies=0)
    full = NativeSourceBinding()
    full.register(token(0))
    with pytest.raises(ValueError, match="scope"):
        full.bind(0, p)
    clock = NativeSourceBinding(clock_only=True)
    clock.register(token(0))
    with pytest.raises(ValueError, match="scope"):
        clock.bind(0, proof())
    mixed = deepcopy(p)
    mixed["scene"]["proof_scope"] = "full_native_body_camera"
    with pytest.raises(ValueError, match="scope"):
        clock.bind(0, mixed)
    row = clock.bind(0, p)
    assert row["proof_scope"] == "publication_clock_camera"
    assert not row["body_geometry_checked"] and not row["dataset_admissible"]


def test_empty_body_coverage_rejected_in_full_scope():
    b = NativeSourceBinding()
    b.register(token(0))
    p = proof()
    p["scene"]["compared_bodies"] = 0
    with pytest.raises(ValueError, match="coverage"):
        b.bind(0, p)


def test_attribute_camera_scope_requires_actual_native_scalar_and_no_body_claim():
    with pytest.raises(ValueError, match="clock-only"):
        NativeSourceBinding(attribute_only=True)
    p = proof()
    for row in p.values():
        row.update(proof_scope="publication_attribute_camera", compared_bodies=0,
                   body_geometry_checked=False, attribute_clock_matched=True,
                   attribute_publication_id=1)
    b = NativeSourceBinding(clock_only=True, attribute_only=True)
    b.register(token(0))
    for mutation in (dict(attribute_clock_matched=False), dict(attribute_publication_id=2),
                     dict(attribute_publication_id=True), dict(compared_bodies=25),
                     dict(body_geometry_checked=True), dict(proof_scope="publication_clock_camera")):
        bad = deepcopy(p)
        bad["scene"].update(mutation)
        with pytest.raises(ValueError):
            b.bind(0, bad)
    row = b.bind(0, p)
    assert row["proof_scope"] == "publication_attribute_camera"
    assert not row["body_geometry_checked"] and not row["dataset_admissible"]
    other = NativeSourceBinding(clock_only=True)
    other.register(token(0))
    with pytest.raises(ValueError, match="scope"):
        other.bind(0, p)


def test_identity_only_requires_exact_history_and_cannot_claim_geometry():
    with pytest.raises(ValueError, match="native publication"):
        NativeSourceBinding(identity_only=True)
    p = proof()
    for row in p.values():
        row.update(proof_scope="publication_attribute", compared_bodies=0,
                   body_geometry_checked=False, camera_geometry_checked=False,
                   geometry_matched=False, history_join_matched=True,
                   attribute_clock_matched=True, attribute_publication_id=1)
    b = NativeSourceBinding(clock_only=True, attribute_only=True, identity_only=True)
    b.register(token(0))
    for mutation in (dict(history_join_matched=False), dict(history_join_matched=1),
                     dict(geometry_matched=True), dict(camera_geometry_checked=True),
                     dict(attribute_publication_id=2), dict(attribute_clock_matched=False),
                     dict(compared_bodies=25), dict(proof_scope="publication_attribute_camera")):
        bad = deepcopy(p)
        bad["scene"].update(mutation)
        with pytest.raises(ValueError):
            b.bind(0, bad)
    row = b.bind(0, p)
    assert row["source_identity_matched"] and not row["camera_geometry_checked"]
    assert not row["body_geometry_checked"] and row["camera_geometry_quality"]["matched"] is None
    assert row["proof_scope"] == "publication_attribute" and not row["dataset_admissible"]
    assert b.receipt()["camera_geometry_checked"] is False


@pytest.mark.parametrize("mutation", [
    lambda p: p.pop("scene"),
    lambda p: p["scene"].update(role="left_wrist"),
    lambda p: p["scene"].update(geometry_matched=False),
    lambda p: p["scene"].update(geometry_matched=1),
    lambda p: p["scene"].update(failed_paths=["/Robot"]),
    lambda p: p["scene"].update(publication_id=2),
    lambda p: p["scene"].update(physics_step=124),
    lambda p: p["scene"].update(reset_epoch=2),
    lambda p: p["scene"].update(frame_identifier={}),
])
def test_invalid_triplet_rejected_without_consuming_ordinal(mutation):
    b = NativeSourceBinding()
    b.register(token(0))
    p = proof()
    mutation(p)
    with pytest.raises(ValueError):
        b.bind(0, p)
    assert b.receipt()["bindings"] == 0
    assert b.bind(0, proof())["packet_ordinal"] == 0


def test_no_current_token_future_epoch_missing_history_and_eviction_rejected():
    b = NativeSourceBinding(capacity=2)
    with pytest.raises(ValueError, match="Register"):
        b.bind(0, proof())
    b.register(token(0))
    b.register(token(1))
    evicted = b.register(token(2))
    assert evicted["token"]["capture_sequence"] == 0 and evicted["bindings"] == 0
    assert b.receipt()["evicted_unbound"] == 1
    for p in [proof(), proof(3, 132), proof(3, 128, 2), proof(3, 126)]:
        with pytest.raises(ValueError):
            b.bind(0, p)
    assert b.bind(0, proof(2, 124))["actual_capture_sequence"] == 1


def test_token_generation_epoch_and_ambiguous_sequence_rejected():
    b = NativeSourceBinding()
    b.register(token(0))
    assert b.register(token(0)) is None
    bad = token(1)
    bad.state_generation = 120
    for item in [bad, token(1, epoch=2), token(1, step=120), token(2)]:
        with pytest.raises(ValueError):
            b.register(item)
    assert b.receipt()["registered"] == 1


def test_publication_source_and_packet_identity_cannot_change_or_regress():
    b = NativeSourceBinding()
    b.register(token(0))
    b.bind(0, proof())
    b.register(token(1))
    for ordinal, p in [(0, proof()), (2, proof()), (1, proof(1, 124)), (1, proof(2, 120))]:
        with pytest.raises(ValueError):
            b.bind(ordinal, p)
    b.bind(1, proof(2, 124))
    with pytest.raises(ValueError, match="regressed"):
        b.bind(2, proof())


def test_optical_failures_separate_from_geometry_binding():
    b = NativeSourceBinding()
    b.register(token(0))
    p = proof()
    for row in p.values():
        row["optical"] = dict(optical_and_geometry_matched=True)
    p["right_wrist"]["optical"]["optical_and_geometry_matched"] = False
    original = deepcopy(p)
    result = b.bind(0, p)
    assert result["camera_geometry_quality"]["matched"]
    assert result["optical_quality"] == "failed" and not result["optical_quality_passed"]
    assert p == original
