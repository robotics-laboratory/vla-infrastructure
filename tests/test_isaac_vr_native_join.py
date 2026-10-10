"""Negative checks for renderer identity coverage, independent of physical clocks."""
import copy
import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / "docs/experiments/20261009_live_camera_recording_30hz/native_live/verify_native_join.py"
spec = importlib.util.spec_from_file_location("native_join_ledger", path)
join = importlib.util.module_from_spec(spec)
spec.loader.exec_module(join)


def frames():
    return [{"native_result_identifiers": {role: {"frameNumber": seq, "time": 42}
             for role in join.ROLES}} for seq in range(100, 103)]


def test_full_native_identity_coverage_never_infers_physics_alignment():
    receipt = join.verify_native_result_identifiers(frames())
    assert receipt["rows"] == 3 and receipt["consecutive"]
    assert not receipt["physics_clock_equality_inferred"]
    assert not receipt["pixel_alignment_proven"]
    assert join.verify_native_result_identifiers([{}, {}])["consecutive"] is None


@pytest.mark.parametrize("case", ["role", "mixed", "skip", "duplicate", "partial", "trailing", "bool"])
def test_corrupt_or_incomplete_callback_ledger_is_rejected(case):
    rows = copy.deepcopy(frames())
    identities = rows[1]["native_result_identifiers"]
    if case == "role":
        identities.pop("scene")
    elif case == "mixed":
        identities["scene"]["time"] += 1
    elif case in ("skip", "duplicate", "bool"):
        for value in identities.values():
            value["frameNumber"] = {"skip": 103, "duplicate": 100, "bool": True}[case]
    else:
        rows[0 if case == "partial" else -1].clear()
    with pytest.raises(ValueError):
        join.verify_native_result_identifiers(rows)
