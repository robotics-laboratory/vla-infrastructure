"""Human demonstration state and publication, above recorder-owned episodes."""

from __future__ import annotations

from enum import Enum
import json
import os
from pathlib import Path
from typing import Callable
from uuid import uuid4


class RecordingState(str, Enum):
    WAITING = "waiting"
    RECORDING = "recording"
    REVIEW = "review"
    RESETTING = "resetting"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RecordingLifecycle:
    """Interpret button edges; callbacks retain recorder and environment ownership."""

    def __init__(
        self,
        *,
        seal: Callable[[str], None],
        publish: Callable[[str], None],
        reset: Callable[[], None],
        discard: Callable[[str], None] | None = None,
        interrupted: Callable[[str], None] | None = None,
        identity: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self.seal, self.publish, self.reset = seal, publish, reset
        self.discard, self.interrupted = discard, interrupted
        self.identity = identity
        self.state = RecordingState.WAITING
        self.demo_id: str | None = None
        self.error: str | None = None
        self._held = {"x": False, "y": False, "b": False}

    @property
    def admits_recording(self) -> bool:
        return self.state is RecordingState.RECORDING

    def buttons(self, *, x: bool, y: bool, b: bool) -> str | None:
        values = {"x": x, "y": y, "b": b}
        edges = {key: value and not self._held[key] for key, value in values.items()}
        self._held.update(values)
        if self.state is RecordingState.WAITING and edges["x"]:
            self.demo_id = self.identity()
            self.state = RecordingState.RECORDING
            return "start"
        if self.state is RecordingState.RECORDING and edges["y"]:
            self._seal("explicit_stop")
            self.state = RecordingState.REVIEW
            return "stop"
        if self.state is RecordingState.REVIEW:
            if edges["x"]:
                self._finish(save=True)
                return "save"
            if edges["b"]:
                self._finish(save=False)
                return "discard"
        return None

    def disconnect(self) -> None:
        self.interrupt("xr_disconnect")

    def interrupt(self, reason: str) -> None:
        if self.state not in (RecordingState.RECORDING, RecordingState.REVIEW):
            return
        if self.state is RecordingState.RECORDING:
            self._seal(reason)
        try:
            if self.interrupted is not None:
                assert self.demo_id is not None
                self.interrupted(self.demo_id)
        except Exception as exc:
            self.fail(exc)
            raise
        self.state = RecordingState.INTERRUPTED

    def external_reset(self) -> None:
        if self.state is RecordingState.RECORDING:
            self._seal("environment_reset_requested")
        if self.state in (RecordingState.REVIEW, RecordingState.RESETTING):
            self._finish(save=False)

    def fail(self, exc: Exception) -> None:
        self.error = f"{type(exc).__name__}: {exc}"
        self.state = RecordingState.FAILED

    def _seal(self, reason: str) -> None:
        # Admission closes before any recorder finalization is attempted.
        self.state = RecordingState.RESETTING
        try:
            self.seal(reason)
        except Exception as exc:
            self.fail(exc)
            raise

    def _finish(self, *, save: bool) -> None:
        self.state = RecordingState.RESETTING
        try:
            self.reset()
            if save:
                assert self.demo_id is not None
                self.publish(self.demo_id)
            elif self.discard is not None:
                assert self.demo_id is not None
                self.discard(self.demo_id)
        except Exception as exc:
            self.fail(exc)
            raise
        self.demo_id = None
        self.state = RecordingState.WAITING


def publish_saved_demo(
    root: Path,
    *,
    demo_id: str,
    episodes: list[dict],
    profile: str,
    start_tick: int,
    stop_tick: int,
) -> Path:
    """Publish a separate user classification without editing canonical manifests."""
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{demo_id}.json"
    if destination.exists():
        raise FileExistsError(destination)
    for episode in episodes:
        manifest = Path(episode["output_dir"]) / "manifest.json"
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if value["artifact_state"] != "finalized" or value["outcome"] != "operator_stopped":
            raise RuntimeError(f"episode is not conservatively finalized: {manifest}")
    document = {
        "schema": "piper_x_isaac_vr_human_demo_v1",
        "demo_id": demo_id,
        "classification": "saved",
        "source_profile": profile,
        "start_control_tick": start_tick,
        "stop_control_tick": stop_tick,
        "technical_episodes": [
            {"episode_id": item["episode_id"], "output_dir": item["output_dir"]}
            for item in episodes
        ],
    }
    temporary = root / f".{demo_id}.{uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.link(temporary, destination)  # exclusive; never replace a prior classification
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def publish_unsaved_demo(
    root: Path, *, demo_id: str, classification: str, episodes: list[dict]
) -> Path:
    """Keep conservative operator disposition apart from saved demonstrations."""
    if classification not in {"discarded", "interrupted"}:
        raise ValueError("unsaved demonstration classification must be discarded or interrupted")
    destination_root = root / f"{classification}_demos"
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / f"{demo_id}.json"
    document = {
        "schema": "piper_x_isaac_vr_human_demo_v1",
        "demo_id": demo_id,
        "classification": classification,
        "technical_episodes": [
            {"episode_id": item["episode_id"], "output_dir": item["output_dir"]}
            for item in episodes
        ],
    }
    temporary = destination_root / f".{demo_id}.{uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def technical_episode_output_dir(
    *,
    first_dir: Path,
    recordings_root: Path | None,
    demo_id: str,
    episode_index: int,
    prior_episodes: bool,
    repository: Path,
    min_free_bytes: int = 1 << 30,
) -> Path:
    """Allocate only the demo parent; the current recorder owns episode dirs."""
    episode_id = f"episode_{episode_index:06d}"
    if episode_index == 0 and not prior_episodes:
        return first_dir
    if recordings_root is None:
        return Path(f"{first_dir}-{demo_id}-{episode_id}")
    demo_parent = recordings_root / demo_id
    if not demo_parent.exists():
        from tools.isaac_vr_recording import prepare_private_output_dir

        prepare_private_output_dir(
            demo_parent, repository=repository, min_free_bytes=min_free_bytes
        )
    return demo_parent / episode_id
