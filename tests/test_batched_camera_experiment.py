"""Offline checks for the experiment-only one-owner batched capture adapter."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import torch


PATH = (
    Path(__file__).parents[1]
    / "docs/experiments/20260921_vr_architecture_bakeoff/batched_camera.py"
)
SPEC = importlib.util.spec_from_file_location("batched_camera_experiment", PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class Owner:
    def __init__(self, shape=(3, 480, 640, 4)) -> None:
        self.frame = torch.zeros(3, dtype=torch.int64)
        self._data_generation = 0
        self._data_generation_last_update = 0
        self.data = SimpleNamespace(output={"rgba": torch.zeros(shape, dtype=torch.uint8)})
        self.non_atomic = False

    def update(self, _dt, *, force_recompute=False) -> None:
        assert force_recompute
        self._data_generation += 1
        self._data_generation_last_update = self._data_generation
        self.frame += 1
        if self.non_atomic:
            self.frame[-1] -= 1


class Role:
    def __init__(self, owner, index) -> None:
        self.owner = owner
        self.batch_index = index


def bundle(shape=(3, 480, 640, 4)):
    owner = Owner(shape)
    roles = {role: Role(owner, index) for index, role in enumerate(module.ROLES)}
    boundary = SimpleNamespace(reset_epoch=1, physics_step=12, render_generation=3)
    capture = module.BatchedThreeCameraCapture(
        roles,
        lambda: boundary,
        lambda: (12, tuple(float(index) for index in range(14))),
    )
    return owner, capture


def test_one_owner_updates_once_and_freezes_three_owned_rgb_roles():
    owner, capture = bundle()
    snapshot = capture.capture(1 / 30)
    assert snapshot is not None
    assert owner._data_generation == 1
    assert [identity.frame for identity in snapshot.cameras] == [1, 1, 1]
    frozen = capture.freeze()
    for role in module.ROLES:
        image = frozen[f"observation.images.{role}"]
        assert image.shape == (480, 640, 3)
        assert image.flags.owndata


@pytest.mark.parametrize("fault", ["wrong_shape", "non_atomic", "replaced_buffer"])
def test_invalid_batch_fails_closed(fault):
    owner, capture = bundle((2, 480, 640, 4) if fault == "wrong_shape" else (3, 480, 640, 4))
    if fault == "non_atomic":
        owner.non_atomic = True
    result = capture.capture(1 / 30)
    if fault in ("wrong_shape", "non_atomic"):
        assert result is None
        with pytest.raises(RuntimeError):
            capture.latest()
        return
    assert result is not None
    owner.data.output["rgba"] = owner.data.output["rgba"].clone()
    with pytest.raises(RuntimeError, match="buffer replaced"):
        capture.freeze()
