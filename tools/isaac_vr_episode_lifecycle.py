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
    CLASSIFY_OUTCOME = "classify_outcome"
    RESETTING = "resetting"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RecordingLifecycle:
    """Interpret button edges; callbacks retain recorder and environment ownership."""

    def __init__(
        self,
        *,
        seal: Callable[[str], None],
        publish: Callable[[str, str], None],
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
                self.state = RecordingState.CLASSIFY_OUTCOME
                return "save"
            if edges["b"]:
                self._finish(outcome=None)
                return "discard"
        if self.state is RecordingState.CLASSIFY_OUTCOME:
            for button, outcome in (("x", "success"), ("y", "failure"), ("b", "incomplete")):
                if edges[button]:
                    self._finish(outcome=outcome)
                    return outcome
        return None

    def disconnect(self) -> None:
        self.interrupt("xr_disconnect")

    def interrupt(self, reason: str) -> None:
        if self.state not in (
            RecordingState.RECORDING, RecordingState.REVIEW, RecordingState.CLASSIFY_OUTCOME
        ):
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
            self._finish(outcome=None)
        elif self.state is RecordingState.REVIEW:
            self._finish(outcome=None)
        elif self.state is RecordingState.CLASSIFY_OUTCOME:
            self.interrupt("environment_reset_requested")

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

    def _finish(self, *, outcome: str | None) -> None:
        self.state = RecordingState.RESETTING
        try:
            if outcome is not None:
                assert self.demo_id is not None
                self.publish(self.demo_id, outcome)
            elif self.discard is not None:
                assert self.demo_id is not None
                self.discard(self.demo_id)
            self.reset()
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
    task_outcome: str,
) -> Path:
    """Atomically publish a classified demo without editing canonical manifests."""
    if task_outcome not in {"success", "failure", "incomplete"}:
        raise ValueError("task outcome must be success, failure, or incomplete")
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{demo_id}.json"
    if destination.exists():
        raise FileExistsError(destination)
    source_schema = None
    row_schema = None
    for episode in episodes:
        manifest = Path(episode["output_dir"]) / "manifest.json"
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if value["artifact_state"] != "finalized" or value["outcome"] != "operator_stopped":
            raise RuntimeError(f"episode is not conservatively finalized: {manifest}")
        identity = (value["schema"], value["transition_schema"])
        if source_schema is not None and identity != (source_schema, row_schema):
            raise RuntimeError(f"technical episode schema differs: {manifest}")
        source_schema, row_schema = identity
    if source_schema is None:
        raise RuntimeError("saved demonstration has no technical episodes")
    document = {
        "schema": "piper_x_isaac_vr_human_demo_v2",
        "demo_id": demo_id,
        "save_classification": "saved",
        "task_outcome": task_outcome,
        "lifecycle_disposition": "saved_and_classified",
        "source_profile": profile,
        "source_manifest_schema": source_schema,
        "committed_row_schema": row_schema,
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
