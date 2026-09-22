from __future__ import annotations

from pathlib import Path

import pytest

from tools.isaac_vr_episode_lifecycle import (
    EpisodeStore,
    RecordingCallbacks,
    RecordingLifecycle,
    RecordingState,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.begun: list[Path] = []

    def callbacks(self) -> RecordingCallbacks:
        return RecordingCallbacks(
            begin=lambda path: self.begun.append(path),
            finalize=lambda: {"hdf5": "session.hdf5", "frames": 3},
            abort=lambda: self.events.append("abort"),
            reset=lambda: self.events.append("reset"),
            stop_main_teleop=lambda: self.events.append("stop"),
            menu_visible=lambda visible: self.events.append(f"menu:{visible}"),
        )


def new_lifecycle(tmp_path: Path) -> tuple[RecordingLifecycle, FakeRuntime]:
    runtime = FakeRuntime()
    return RecordingLifecycle(EpisodeStore(tmp_path), runtime.callbacks()), runtime


def test_start_y_save_requires_fresh_main_start_and_publishes(tmp_path: Path) -> None:
    lifecycle, runtime = new_lifecycle(tmp_path)
    assert lifecycle.on_main_active(True)
    assert lifecycle.state is RecordingState.RECORDING
    assert lifecycle.on_y(True)
    assert lifecycle.state is RecordingState.SAVE_DISCARD_MENU
    assert not lifecycle.admits_control
    published = lifecycle.save()
    assert published.name == "episode_000000"
    assert lifecycle.state is RecordingState.WAITING_FOR_MAIN_START
    assert not lifecycle.on_main_active(False)
    assert lifecycle.on_main_active(True)
    assert len(runtime.begun) == 2
    assert runtime.events == ["stop", "menu:True", "menu:False", "stop", "reset"]


def test_y_is_debounced_and_discard_never_publishes(tmp_path: Path) -> None:
    lifecycle, runtime = new_lifecycle(tmp_path)
    lifecycle.on_main_active(True)
    assert lifecycle.on_y(True)
    assert not lifecycle.on_y(True)
    lifecycle.on_y(False)
    lifecycle.discard()
    assert not list(tmp_path.glob("episode_*"))
    assert lifecycle.state is RecordingState.WAITING_FOR_MAIN_START
    assert runtime.events == ["stop", "menu:True", "abort", "menu:False", "stop", "reset"]


@pytest.mark.parametrize("event", ["on_main_reset", "on_disconnect"])
def test_reset_and_disconnect_discard_active_episode(tmp_path: Path, event: str) -> None:
    lifecycle, runtime = new_lifecycle(tmp_path)
    lifecycle.on_main_active(True)
    getattr(lifecycle, event)()
    assert lifecycle.state is RecordingState.WAITING_FOR_MAIN_START
    assert not list(tmp_path.glob("episode_*"))
    assert runtime.events[-3:] == ["menu:False", "stop", "reset"]


def test_shutdown_keeps_previous_save_and_removes_current_temporary(tmp_path: Path) -> None:
    lifecycle, _ = new_lifecycle(tmp_path)
    lifecycle.on_main_active(True)
    lifecycle.on_y(True)
    lifecycle.save()
    lifecycle.on_main_active(True)
    lifecycle.shutdown()
    assert lifecycle.state is RecordingState.SHUTDOWN
    assert [path.name for path in tmp_path.glob("episode_*")] == ["episode_000000"]
    assert not list(tmp_path.glob(".episode-tmp-*"))


def test_next_public_number_survives_restart(tmp_path: Path) -> None:
    first, _ = new_lifecycle(tmp_path)
    first.on_main_active(True)
    first.on_y(True)
    first.save()
    second, _ = new_lifecycle(tmp_path)
    second.on_main_active(True)
    second.on_y(True)
    assert second.save().name == "episode_000001"
