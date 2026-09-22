"""Small, testable owner for multi-episode record publication.

The XR stack remains the authority for Start/Reset.  This module owns only the
recording-specific states and the atomic temporary-to-published episode path.
It deliberately has no Isaac, OpenXR, or HDF5 dependency so its safety rules are
exercised by ordinary unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import shutil
from typing import Callable
from uuid import uuid4


class RecordingState(str, Enum):
    WAITING_FOR_MAIN_START = "waiting_for_main_start"
    RECORDING = "recording"
    SAVE_DISCARD_MENU = "save_discard_menu"
    FINALIZING = "finalizing"
    RESETTING = "resetting"
    SHUTDOWN = "shutdown"


class EpisodeStore:
    """Allocate public episode identities only when a complete episode saves."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def begin_temporary(self) -> Path:
        path = self.root / f".episode-tmp-{uuid4().hex}"
        path.mkdir()
        return path

    def publish(self, temporary: Path, manifest: dict) -> Path:
        self._require_temporary(temporary)
        number = self._next_number()
        final = self.root / f"episode_{number:06d}"
        manifest = {**manifest, "episode_number": number, "save_classification": "saved"}
        self._atomic_json(temporary / "manifest.json", manifest)
        try:
            os.replace(temporary, final)
        except FileExistsError as exc:
            raise RuntimeError(f"episode publication collision: {final}") from exc
        return final

    def discard(self, temporary: Path | None) -> None:
        if temporary is not None and temporary.exists():
            self._require_temporary(temporary)
            shutil.rmtree(temporary)

    def _next_number(self) -> int:
        numbers = []
        for path in self.root.glob("episode_*"):
            if path.is_dir() and path.name[8:].isdigit() and (path / "manifest.json").is_file():
                numbers.append(int(path.name[8:]))
        return max(numbers, default=-1) + 1

    def _require_temporary(self, path: Path) -> None:
        if path.parent != self.root or not path.name.startswith(".episode-tmp-"):
            raise ValueError(f"refusing to alter non-temporary episode path: {path}")

    @staticmethod
    def _atomic_json(path: Path, value: dict) -> None:
        replacement = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        replacement.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(replacement, path)


@dataclass
class RecordingCallbacks:
    begin: Callable[[Path], None]
    finalize: Callable[[], dict]
    abort: Callable[[], None]
    reset: Callable[[], None]
    stop_main_teleop: Callable[[], None]
    menu_visible: Callable[[bool], None]


class RecordingLifecycle:
    """Recording gate around authoritative upstream lifecycle events.

    ``on_main_active`` is called with the post-advance `ControlEvents.is_active`
    value.  It never synthesizes a Start event; after every local transition the
    upstream menu must produce a fresh active event before a new episode begins.
    """

    def __init__(self, store: EpisodeStore, callbacks: RecordingCallbacks) -> None:
        self.store = store
        self.callbacks = callbacks
        self.state = RecordingState.WAITING_FOR_MAIN_START
        self.temporary: Path | None = None
        self._y_held = False

    @property
    def admits_control(self) -> bool:
        return self.state is RecordingState.RECORDING

    def on_main_active(self, active: bool | None) -> bool:
        """Start exactly one new episode only on the upstream active transition."""
        if active is True and self.state is RecordingState.WAITING_FOR_MAIN_START:
            self.temporary = self.store.begin_temporary()
            self.callbacks.begin(self.temporary)  # records initial O0
            self.state = RecordingState.RECORDING
            return True
        return False

    def on_y(self, pressed: bool) -> bool:
        edge = pressed and not self._y_held
        self._y_held = pressed
        if not edge or self.state is not RecordingState.RECORDING:
            return False
        # This is called after the current complete transition is committed.
        self.callbacks.stop_main_teleop()
        self.callbacks.menu_visible(True)
        self.state = RecordingState.SAVE_DISCARD_MENU
        return True

    def save(self) -> Path:
        self._require_menu()
        self.state = RecordingState.FINALIZING
        try:
            metadata = self.callbacks.finalize()
            assert self.temporary is not None
            published = self.store.publish(self.temporary, metadata)
            self.temporary = None
        finally:
            self.callbacks.menu_visible(False)
        self._reset_waiting()
        return published

    def discard(self) -> None:
        if self.state not in (RecordingState.RECORDING, RecordingState.SAVE_DISCARD_MENU):
            return
        self.callbacks.abort()
        self.store.discard(self.temporary)
        self.temporary = None
        self.callbacks.menu_visible(False)
        self._reset_waiting()

    def on_main_reset(self) -> None:
        if self.state in (RecordingState.RECORDING, RecordingState.SAVE_DISCARD_MENU):
            self.discard()
        elif self.state is RecordingState.WAITING_FOR_MAIN_START:
            self._reset_waiting()

    def on_disconnect(self) -> None:
        self.discard()

    def shutdown(self) -> None:
        if self.state in (RecordingState.RECORDING, RecordingState.SAVE_DISCARD_MENU):
            self.callbacks.abort()
            self.store.discard(self.temporary)
            self.temporary = None
        self.callbacks.menu_visible(False)
        self.state = RecordingState.SHUTDOWN

    def _reset_waiting(self) -> None:
        self.state = RecordingState.RESETTING
        self.callbacks.stop_main_teleop()
        self.callbacks.reset()
        self.state = RecordingState.WAITING_FOR_MAIN_START

    def _require_menu(self) -> None:
        if self.state is not RecordingState.SAVE_DISCARD_MENU or self.temporary is None:
            raise RuntimeError("Save is valid only for an active Save/Discard menu")
