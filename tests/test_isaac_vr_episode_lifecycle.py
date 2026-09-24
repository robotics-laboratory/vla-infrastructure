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
            publish=lambda demo_id, outcome: self.saved.append((demo_id, outcome)),
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


@pytest.mark.parametrize(
    ("button", "outcome"),
    [("x", "success"), ("y", "failure"), ("b", "incomplete")],
)
def test_save_requires_explicit_task_outcome_and_keeps_source(tmp_path, button, outcome):
    episode = tmp_path / "episode_000000"
    episode.mkdir()
    canonical = {
        "artifact_state": "finalized",
        "outcome": "operator_stopped",
        "dataset_admissible": False,
        "schema": "piper_x_isaac_vr_recording_manifest_v2",
        "transition_schema": "piper_x_committed_transition_v3",
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
        publish=lambda demo_id, task_outcome: saved.append(
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
                task_outcome=task_outcome,
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
    assert lifecycle.state is RecordingState.CLASSIFY_OUTCOME
    assert recorder.resets == 0 and saved == []
    assert not list((tmp_path / "saved_demos").glob("*.json"))
    press(lifecycle, button)
    document = json.loads(saved[0].read_text())
    assert document["save_classification"] == "saved"
    assert document["task_outcome"] == outcome
    assert document["lifecycle_disposition"] == "saved_and_classified"
    assert document["source_manifest_schema"] == canonical["schema"]
    assert document["committed_row_schema"] == canonical["transition_schema"]
    assert document["source_profile"] == "isaac_human_vr_offline_rgb_v2"
    assert (document["start_control_tick"], document["stop_control_tick"]) == (101, 105)
    assert document["technical_episodes"] == [
        {"episode_id": "episode_000000", "output_dir": str(episode)},
        {"episode_id": "episode_000001", "output_dir": str(second)},
    ]
    assert "dataset_admissible" not in document
    assert manifest.read_bytes() == before and second_manifest.read_bytes() == second_before
    assert lifecycle.state is RecordingState.WAITING and recorder.resets == 1
    press(lifecycle, "x")
    assert lifecycle.demo_id != document["demo_id"]


def test_discard_skips_classification(tmp_path):
    recorder = Facade()
    lifecycle = RecordingLifecycle(
        seal=recorder.seals.append,
        publish=lambda *_: pytest.fail("discard published saved demo"),
        reset=lambda: setattr(recorder, "resets", recorder.resets + 1),
        discard=lambda demo_id: publish_unsaved_demo(
            tmp_path, demo_id=demo_id, classification="discarded", episodes=[]
        ),
    )
    press(lifecycle, "x")
    press(lifecycle, "y")
    demo_id = lifecycle.demo_id
    press(lifecycle, "b")
    assert lifecycle.state is RecordingState.WAITING and recorder.resets == 1
    disposition = json.loads((tmp_path / "discarded_demos" / f"{demo_id}.json").read_text())
    assert disposition["classification"] == "discarded"
    assert "task_outcome" not in disposition
    assert not (tmp_path / "saved_demos").exists()


def test_held_save_button_cannot_classify_or_start_next_demo():
    recorder = Facade()
    lifecycle = recorder.make()
    press(lifecycle, "x")
    press(lifecycle, "y")
    assert lifecycle.buttons(x=True, y=False, b=False) == "save"
    assert lifecycle.state is RecordingState.CLASSIFY_OUTCOME
    assert lifecycle.buttons(x=True, y=False, b=False) is None
    assert lifecycle.state is RecordingState.CLASSIFY_OUTCOME and recorder.saved == []
    lifecycle.buttons(x=False, y=False, b=False)
    assert lifecycle.buttons(x=True, y=False, b=False) == "success"
    assert lifecycle.state is RecordingState.WAITING and len(recorder.saved) == 1
    assert lifecycle.buttons(x=True, y=False, b=False) is None
    assert lifecycle.demo_id is None


def test_disconnect_during_outcome_classification_is_forensic(tmp_path):
    lifecycle = RecordingLifecycle(
        seal=lambda _: None,
        publish=lambda *_: pytest.fail("interruption published saved demo"),
        reset=lambda: None,
        interrupted=lambda demo_id: publish_unsaved_demo(
            tmp_path, demo_id=demo_id, classification="interrupted", episodes=[]
        ),
    )
    press(lifecycle, "x")
    press(lifecycle, "y")
    press(lifecycle, "x")
    lifecycle.disconnect()
    assert lifecycle.state is RecordingState.INTERRUPTED
    assert not (tmp_path / "saved_demos").exists()
    assert list((tmp_path / "interrupted_demos").glob("*.json"))


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
        publish=lambda *_: pytest.fail("disconnect published saved demo"),
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

    lifecycle = RecordingLifecycle(seal=broken_seal, publish=lambda *_: None, reset=lambda: None)
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
        publish=lambda demo_id, task_outcome: publish_saved_demo(
            tmp_path / "saved_demos",
            demo_id=demo_id,
            episodes=[{"episode_id": "episode", "output_dir": str(episode)}],
            profile="isaac_human_vr_offline_rgb_v2",
            start_tick=1,
            stop_tick=2,
            task_outcome=task_outcome,
        ),
        reset=lambda: None,
    )
    press(lifecycle, "x")
    press(lifecycle, "y")
    press(lifecycle, "x")
    with pytest.raises(RuntimeError, match="not conservatively finalized"):
        lifecycle.buttons(x=False, y=True, b=False)
    assert lifecycle.state is RecordingState.FAILED
    assert not list((tmp_path / "saved_demos").glob("*.json"))


def test_publication_failure_keeps_canonical_artifact_and_fails_lifecycle(tmp_path, monkeypatch):
    episode = tmp_path / "episode"
    episode.mkdir()
    manifest = episode / "manifest.json"
    manifest.write_text(json.dumps({
        "artifact_state": "finalized", "outcome": "operator_stopped",
        "schema": "piper_x_isaac_vr_recording_manifest_v2",
        "transition_schema": "piper_x_committed_transition_v3",
    }))
    before = manifest.read_bytes()
    resets = []
    lifecycle = RecordingLifecycle(
        seal=lambda _: None,
        publish=lambda demo_id, task_outcome: publish_saved_demo(
            tmp_path / "saved_demos", demo_id=demo_id,
            episodes=[{"episode_id": "episode", "output_dir": str(episode)}],
            profile="isaac_human_vr_offline_rgb_v2", start_tick=1, stop_tick=2,
            task_outcome=task_outcome,
        ),
        reset=lambda: resets.append(True),
    )
    press(lifecycle, "x")
    press(lifecycle, "y")
    press(lifecycle, "x")
    monkeypatch.setattr("tools.isaac_vr_episode_lifecycle.os.link", lambda *_: (_ for _ in ()).throw(OSError("publication failed")))
    with pytest.raises(OSError, match="publication failed"):
        lifecycle.buttons(x=False, y=True, b=False)
    assert lifecycle.state is RecordingState.FAILED
    assert "publication failed" in lifecycle.error
    assert not resets and manifest.read_bytes() == before
    assert not list((tmp_path / "saved_demos").glob("*.json"))
