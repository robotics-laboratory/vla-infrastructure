"""Explicit human lifecycle checks without Isaac or Quest."""

import json
from pathlib import Path
import stat

import pytest

from tools.isaac_vr_episode_lifecycle import (
    RecordingLifecycle,
    RecordingState,
    publish_saved_demo,
    publish_unsaved_demo,
    technical_episode_output_dir,
)
from tools.isaac_vr_recording import prepare_private_output_dir

ROOT = Path(__file__).resolve().parents[1]


class Facade:
    def __init__(self):
        self.episodes = []
        self.rows = []
        self.seals = []
        self.resets = 0
        self.saved = []

    def tick(self, transition="motion", *, eligible=True):
        if not self.lifecycle.admits_recording:
            return
        if not eligible:
            if self.rows and self.episodes[-1]:
                self.episodes.append([])
            return
        if not self.episodes:
            self.episodes.append([])
        row = {"frame_index": len(self.episodes[-1]), "transition": transition}
        self.episodes[-1].append(row)
        self.rows.append(row)

    def make(self):
        self.lifecycle = RecordingLifecycle(
            seal=self.seals.append,
            publish=self.saved.append,
            reset=lambda: setattr(self, "resets", self.resets + 1),
        )
        return self.lifecycle


def press(lifecycle, button):
    values = {"x": False, "y": False, "b": False}
    values[button] = True
    lifecycle.buttons(**values)
    lifecycle.buttons(x=False, y=False, b=False)


def test_delayed_start_and_second_identity():
    recorder = Facade()
    lifecycle = recorder.make()
    for _ in range(120):
        recorder.tick()
    assert not recorder.episodes and lifecycle.demo_id is None
    press(lifecycle, "x")
    first = lifecycle.demo_id
    recorder.tick()
    assert recorder.rows[0]["frame_index"] == 0
    press(lifecycle, "y")
    assert lifecycle.state is RecordingState.REVIEW
    press(lifecycle, "b")
    assert lifecycle.state is RecordingState.WAITING and recorder.resets == 1
    press(lifecycle, "x")
    assert lifecycle.demo_id != first


def test_episode_directory_parent_uses_current_recorder_private_ownership(tmp_path):
    recordings_root = tmp_path / "recordings"
    recordings_root.mkdir(mode=0o700)
    first = recordings_root / "episode_000000"
    kwargs = {
        "first_dir": first,
        "recordings_root": recordings_root,
        "demo_id": "demo_a",
        "repository": ROOT,
        "min_free_bytes": 0,
    }
    assert technical_episode_output_dir(**kwargs, episode_index=0, prior_episodes=False) == first
    assert not (recordings_root / "demo_a").exists()
    next_path = technical_episode_output_dir(**kwargs, episode_index=1, prior_episodes=True)
    assert next_path == recordings_root / "demo_a" / "episode_000001"
    assert stat.S_IMODE(next_path.parent.stat().st_mode) == 0o700
    prepare_private_output_dir(next_path, repository=ROOT, min_free_bytes=0)
    assert next_path.is_dir()
    kwargs["demo_id"] = "demo_b"
    other = technical_episode_output_dir(**kwargs, episode_index=0, prior_episodes=True)
    assert other == recordings_root / "demo_b" / "episode_000000"
    assert other.parent != next_path.parent and other.parent.is_dir()


def test_clutch_stays_in_one_demo_and_episode():
    recorder = Facade()
    lifecycle = recorder.make()
    press(lifecycle, "x")
    demo_id = lifecycle.demo_id
    for transition in (
        "motion",
        "clutch_engaged",
        "clutch_held",
        "clutch_release_rebased",
        "motion",
    ):
        recorder.tick(transition)
        assert lifecycle.state is RecordingState.RECORDING
    assert lifecycle.demo_id == demo_id
    assert len(recorder.episodes) == 1 and recorder.seals == []


def test_tracking_gap_keeps_demo_until_explicit_stop():
    recorder = Facade()
    lifecycle = recorder.make()
    press(lifecycle, "x")
    demo_id = lifecycle.demo_id
    recorder.tick()
    recorder.tick(eligible=False)
    assert lifecycle.state is RecordingState.RECORDING
    recorder.tick()
    assert lifecycle.demo_id == demo_id and len(recorder.episodes) == 2
    assert recorder.episodes[1][0]["frame_index"] == 0
    press(lifecycle, "y")
    assert lifecycle.state is RecordingState.REVIEW and recorder.seals == ["explicit_stop"]


def test_stop_seals_and_menu_buttons_are_not_rows():
    recorder = Facade()
    lifecycle = recorder.make()
    press(lifecycle, "x")
    recorder.tick()
    press(lifecycle, "y")
    count = len(recorder.rows)
    recorder.tick("menu_x")
    lifecycle.buttons(x=False, y=True, b=False)  # held Y does not stop twice
    assert len(recorder.rows) == count
    assert recorder.seals == ["explicit_stop"]
    assert lifecycle.state is RecordingState.REVIEW


def test_save_and_discard_are_distinct_from_task_outcome(tmp_path):
    episode = tmp_path / "episode_000000"
    episode.mkdir()
    canonical = {
        "artifact_state": "finalized",
        "outcome": "operator_stopped",
        "dataset_admissible": False,
    }
    manifest = episode / "manifest.json"
    manifest.write_text(json.dumps(canonical))
    before = manifest.read_bytes()
    second = tmp_path / "episode_000001"
    second.mkdir()
    second_manifest = second / "manifest.json"
    second_manifest.write_text(json.dumps(canonical))
    second_before = second_manifest.read_bytes()
    recorder = Facade()
    saved = []
    lifecycle = RecordingLifecycle(
        seal=recorder.seals.append,
        publish=lambda demo_id: saved.append(
            publish_saved_demo(
                tmp_path / "saved_demos",
                demo_id=demo_id,
                episodes=[
                    {"episode_id": "episode_000000", "output_dir": str(episode)},
                    {"episode_id": "episode_000001", "output_dir": str(second)},
                ],
                profile="isaac_human_vr_offline_rgb_v2",
                start_tick=101,
                stop_tick=105,
            )
        ),
        reset=lambda: setattr(recorder, "resets", recorder.resets + 1),
        discard=lambda demo_id: publish_unsaved_demo(
            tmp_path,
            demo_id=demo_id,
            classification="discarded",
            episodes=[{"episode_id": "episode_000000", "output_dir": str(episode)}],
        ),
    )
    press(lifecycle, "x")
    press(lifecycle, "y")
    press(lifecycle, "x")
    document = json.loads(saved[0].read_text())
    assert document["classification"] == "saved"
    assert document["technical_episodes"] == [
        {"episode_id": "episode_000000", "output_dir": str(episode)},
        {"episode_id": "episode_000001", "output_dir": str(second)},
    ]
    assert "success" not in document and "dataset_admissible" not in document
    assert manifest.read_bytes() == before and second_manifest.read_bytes() == second_before
    assert lifecycle.state is RecordingState.WAITING and recorder.resets == 1
    press(lifecycle, "x")
    press(lifecycle, "y")
    discarded_id = lifecycle.demo_id
    press(lifecycle, "b")
    assert len(saved) == 1 and manifest.read_bytes() == before
    assert lifecycle.state is RecordingState.WAITING and recorder.resets == 2
    disposition = json.loads((tmp_path / "discarded_demos" / f"{discarded_id}.json").read_text())
    assert disposition["classification"] == "discarded"
    assert "success" not in disposition and "dataset_admissible" not in disposition


def test_disconnect_never_publishes_and_exits_recording():
    recorder = Facade()
    lifecycle = recorder.make()
    press(lifecycle, "x")
    recorder.tick()
    lifecycle.disconnect()
    assert lifecycle.state is RecordingState.INTERRUPTED
    assert recorder.seals == ["xr_disconnect"] and recorder.saved == []
    lifecycle.buttons(x=True, y=False, b=False)
    assert lifecycle.state is RecordingState.INTERRUPTED


def test_disconnect_disposition_is_forensic_not_saved(tmp_path):
    lifecycle = RecordingLifecycle(
        seal=lambda _: None,
        publish=lambda _: pytest.fail("disconnect published saved demo"),
        reset=lambda: None,
        interrupted=lambda demo_id: publish_unsaved_demo(
            tmp_path, demo_id=demo_id, classification="interrupted", episodes=[]
        ),
    )
    press(lifecycle, "x")
    demo_id = lifecycle.demo_id
    lifecycle.disconnect()
    assert lifecycle.state is RecordingState.INTERRUPTED
    assert (
        json.loads((tmp_path / "interrupted_demos" / f"{demo_id}.json").read_text())[
            "classification"
        ]
        == "interrupted"
    )
    assert not (tmp_path / "saved_demos").exists()


def test_finalize_and_save_fail_closed(tmp_path):
    def broken_seal(_):
        raise OSError("storage failed")

    lifecycle = RecordingLifecycle(seal=broken_seal, publish=lambda _: None, reset=lambda: None)
    press(lifecycle, "x")
    with pytest.raises(OSError, match="storage failed"):
        lifecycle.buttons(x=False, y=True, b=False)
    assert lifecycle.state is RecordingState.FAILED and "storage failed" in lifecycle.error

    episode = tmp_path / "episode"
    episode.mkdir()
    (episode / "manifest.json").write_text(
        json.dumps({"artifact_state": "failed", "outcome": "failure"})
    )
    lifecycle = RecordingLifecycle(
        seal=lambda _: None,
        publish=lambda demo_id: publish_saved_demo(
            tmp_path / "saved_demos",
            demo_id=demo_id,
            episodes=[{"episode_id": "episode", "output_dir": str(episode)}],
            profile="isaac_human_vr_offline_rgb_v2",
            start_tick=1,
            stop_tick=2,
        ),
        reset=lambda: None,
    )
    press(lifecycle, "x")
    press(lifecycle, "y")
    with pytest.raises(RuntimeError, match="not conservatively finalized"):
        lifecycle.buttons(x=True, y=False, b=False)
    assert lifecycle.state is RecordingState.FAILED
    assert not list((tmp_path / "saved_demos").glob("*.json"))
