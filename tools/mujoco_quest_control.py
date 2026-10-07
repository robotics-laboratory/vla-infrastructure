"""Isaac-compatible WebXR Play/Stop/Reset control for the MuJoCo Quest profile."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from isaacteleop.retargeting_engine.deviceio_source_nodes import message_channel_config
from isaacteleop.retargeting_engine.interface import BaseRetargeter, RetargeterIOType
from isaacteleop.teleop_session_manager import DefaultTeleopStateManager


TELEOP_CONTROL_CHANNEL_UUID = uuid.uuid5(uuid.NAMESPACE_DNS, "teleop_command").bytes

_COMMAND_PATTERNS = (
    (re.compile(r"\breset\b", re.IGNORECASE), "reset"),
    (re.compile(r"\bstop\b", re.IGNORECASE), "stop"),
    (re.compile(r"\bstart\b", re.IGNORECASE), "start"),
)
_START_SEQUENCES = {
    "stopped": [True, False, True],
    "paused": [True],
    "running": [],
}
_STOP_SEQUENCES = {
    "stopped": [],
    "paused": [],
    "running": [True],
}
_TOGGLE_TRANSITIONS = {
    "stopped": "paused",
    "paused": "running",
    "running": "paused",
}


def _classify_command(text: str) -> str | None:
    for pattern, label in _COMMAND_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _extract_command(payload: Any) -> str | None:
    try:
        text = bytes(payload).decode("utf-8")
    except (TypeError, UnicodeDecodeError):
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(value, dict) or value.get("type") != "teleop_command":
        return None
    message = value.get("message")
    if isinstance(message, dict):
        command = message.get("command")
        return command if isinstance(command, str) else None
    return message if isinstance(message, str) else None


class MujocoQuestTeleopMessageProcessor(BaseRetargeter):
    """Translate the NVIDIA WebXR menu messages into upstream state-manager pulses."""

    INPUT_MESSAGES = "messages_tracked"

    def __init__(self, name: str) -> None:
        self._shadow_state = "stopped"
        self._toggle_queue: list[bool] = []
        self._previous_toggle = False
        self._host_reset_pending = False
        self._host_reset_pause = False
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        from isaacteleop.retargeting_engine.deviceio_source_nodes.deviceio_tensor_types import (
            MessageChannelMessagesTrackedGroup,
        )

        return {self.INPUT_MESSAGES: MessageChannelMessagesTrackedGroup()}

    def output_spec(self) -> RetargeterIOType:
        from isaacteleop.teleop_session_manager.teleop_state_manager_types import bool_signal

        return {
            "run_toggle": bool_signal("run_toggle"),
            "kill": bool_signal("kill"),
            "reset": bool_signal("reset"),
        }

    def inject_reset(self, *, pause: bool) -> None:
        """Schedule a host reset through the same execution-event path as the XR menu."""

        self._host_reset_pending = True
        self._host_reset_pause |= pause

    def _sequence(self, values: list[bool]) -> list[bool]:
        result = list(values)
        if result and self._previous_toggle:
            result.insert(0, False)
        return result

    def _apply(self, command: str | None) -> bool:
        if command == "start" and not self._toggle_queue:
            self._toggle_queue = self._sequence(_START_SEQUENCES[self._shadow_state])
        elif command == "stop" and not self._toggle_queue:
            self._toggle_queue = self._sequence(_STOP_SEQUENCES[self._shadow_state])
        return command == "reset"

    def _compute_fn(self, inputs: Any, outputs: Any, context: Any) -> None:
        del context
        reset = self._host_reset_pending
        pause_on_reset = self._host_reset_pause
        self._host_reset_pending = False
        self._host_reset_pause = False

        messages = getattr(inputs[self.INPUT_MESSAGES][0], "data", None) or ()
        for message in messages:
            payload = getattr(message, "payload", None)
            command_text = _extract_command(payload)
            command = _classify_command(command_text) if command_text is not None else None
            if self._apply(command):
                reset = True
                pause_on_reset = True

        if reset and pause_on_reset:
            self._toggle_queue = self._sequence(_STOP_SEQUENCES[self._shadow_state])

        run_toggle = self._toggle_queue.pop(0) if self._toggle_queue else False
        if run_toggle and not self._previous_toggle:
            self._shadow_state = _TOGGLE_TRANSITIONS[self._shadow_state]
        self._previous_toggle = run_toggle

        outputs["run_toggle"][0] = run_toggle
        outputs["kill"][0] = False
        outputs["reset"][0] = reset


def build_mujoco_quest_control_pipeline() -> tuple[Any, MujocoQuestTeleopMessageProcessor, Any]:
    """Build the same well-known message-channel/state-manager seam used by Isaac."""

    source, _unused_sink = message_channel_config(
        name="_teleop_control",
        channel_uuid=TELEOP_CONTROL_CHANNEL_UUID,
    )
    processor = MujocoQuestTeleopMessageProcessor(name="_teleop_message_processor")
    parsed = processor.connect(
        {processor.INPUT_MESSAGES: source.output("messages_tracked")}
    )
    state = DefaultTeleopStateManager(name="_teleop_state")
    pipeline = state.connect(
        {
            state.INPUT_KILL: parsed.output("kill"),
            state.INPUT_RUN_TOGGLE: parsed.output("run_toggle"),
            state.INPUT_RESET: parsed.output("reset"),
        }
    )
    return source, processor, pipeline
