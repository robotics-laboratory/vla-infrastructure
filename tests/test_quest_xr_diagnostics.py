from __future__ import annotations

import json

import numpy as np
import pytest

from tools import quest_xr_diagnostics as diagnostics


class FakeLauncher:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.stopped = False

    def stop(self):
        self.stopped = True


class FakeControllersSource:
    LEFT = "controller_left"
    RIGHT = "controller_right"

    def __init__(self, name):
        self.name = name

    def output(self, side):
        return f"output:{side}"


class FakeOutputCombiner:
    def __init__(self, outputs):
        self.outputs = outputs


class FakeSessionConfig:
    def __init__(self, *, app_name, pipeline):
        self.app_name = app_name
        self.pipeline = pipeline


class FakeStepInfo:
    frame_deadline_miss = False
    returned_age_frames = 0


class FakeSession:
    created = 0

    def __init__(self, config):
        type(self).created += 1
        self.config = config
        self.last_step_info = FakeStepInfo()
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.exited = True

    def step(self, *, execution_events):
        assert execution_events is not None
        return {"left": FakeController.none(), "right": FakeController.live()}


class FakeController:
    def __init__(self, values=None):
        self.is_none = values is None
        self.values = values or {}

    def __getitem__(self, index):
        return self.values[index]

    @classmethod
    def none(cls):
        return cls()

    @classmethod
    def live(cls):
        i = diagnostics.ControllerInputIndex
        return cls(
            {
                i.GRIP_POSITION: np.array([1.0, 2.0, 3.0]),
                i.GRIP_ORIENTATION: np.array([0.0, 0.0, 0.0, 1.0]),
                i.GRIP_IS_VALID: True,
                i.AIM_IS_VALID: True,
                i.PRIMARY_CLICK: 1.0,
                i.SECONDARY_CLICK: 0.0,
                i.THUMBSTICK_X: 0.25,
                i.THUMBSTICK_Y: -0.5,
                i.THUMBSTICK_CLICK: 1.0,
                i.MENU_CLICK: 0.0,
                i.SQUEEZE_VALUE: 0.75,
                i.TRIGGER_VALUE: 0.5,
            }
        )


def _install_fakes(monkeypatch) -> None:
    diagnostics.SharedQuestSession._active_owner = None
    diagnostics.SharedQuestSession._session_instances_created = 0
    FakeSession.created = 0
    monkeypatch.setattr(diagnostics, "CloudXRLauncher", FakeLauncher)
    monkeypatch.setattr(diagnostics, "ControllersSource", FakeControllersSource)
    monkeypatch.setattr(diagnostics, "OutputCombiner", FakeOutputCombiner)
    monkeypatch.setattr(diagnostics, "TeleopSessionConfig", FakeSessionConfig)
    monkeypatch.setattr(diagnostics, "TeleopSession", FakeSession)


def test_one_fake_session_provides_both_hands(monkeypatch) -> None:
    _install_fakes(monkeypatch)
    session = diagnostics.SharedQuestSession(monotonic_ns=lambda: 123456789)
    session.start()
    try:
        sample = session.poll()

        assert FakeSession.created == 1
        assert sample["lifecycle"]["process_local_session_instances_created"] == 1
        assert sample["left"]["availability"] == "unavailable"
        assert sample["left"]["grip_position"] is None
        assert sample["right"]["availability"] == "available"
        assert sample["right"]["grip_position"] == [1.0, 2.0, 3.0]
        assert sample["right"]["controls"]["squeeze_value"] == 0.75
        assert sample["right"]["host_receipt_monotonic_ns"] == 123456789
        encoded = json.dumps(sample, sort_keys=True, separators=(",", ":"))
        assert encoded == json.dumps(json.loads(encoded), sort_keys=True, separators=(",", ":"))
    finally:
        session.close()


def test_second_live_session_is_refused(monkeypatch) -> None:
    _install_fakes(monkeypatch)
    first = diagnostics.SharedQuestSession()
    second = diagnostics.SharedQuestSession()
    first.start()
    try:
        with pytest.raises(RuntimeError, match="already live"):
            second.start()
    finally:
        first.close()
