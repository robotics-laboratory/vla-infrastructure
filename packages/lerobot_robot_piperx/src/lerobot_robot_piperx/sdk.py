"""Minimal PIPER SDK translation reused by the PIPER-X Robot classes."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast


PIPER_JOINT_NAMES = ("joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6")
PIPER_JOINT_ACTION_KEYS = tuple(f"{joint}.pos" for joint in PIPER_JOINT_NAMES)
PIPER_ACTION_KEYS = PIPER_JOINT_ACTION_KEYS + ("gripper.pos",)
PIPER_ROLE_FOLLOWER = 0xFC
_SYS_CLASS_NET = Path("/sys/class/net")


@dataclass(frozen=True)
class PiperTemporalObservationSnapshot:
    """Atomically copied PIPER feedback with per-CAN-component receipt time."""

    joint_values: tuple[int, int, int, int, int, int]
    joint_timestamps: tuple[float, float, float]
    joint_hz: float
    gripper_value: int
    gripper_timestamp: float
    gripper_hz: float
    identity: tuple[int, int, int, int]


def milli_to_unit(value: float | int) -> float:
    return float(value) * 1e-3


def unit_to_milli(value: float | int) -> int:
    return int(round(float(value) * 1e3))


@lru_cache(maxsize=1)
def _timestamped_piper_interface(base: type[Any]) -> type[Any]:
    """Add an atomic temporal snapshot without replacing the pinned SDK parser."""

    joint_frame_slices = {
        0x2A5: (0, ("joint_1", "joint_2")),
        0x2A6: (2, ("joint_3", "joint_4")),
        0x2A7: (4, ("joint_5", "joint_6")),
    }
    gripper_frame_id = 0x2A8

    class TimestampedPiperInterface(base):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._temporal_snapshot_lock = threading.Lock()
            self._temporal_joint_values: list[int | None] = [None] * 6
            self._temporal_joint_timestamps: list[float | None] = [None] * 3
            self._temporal_gripper_value: int | None = None
            self._temporal_gripper_timestamp: float | None = None
            self._temporal_component_sequences = [0, 0, 0, 0]
            super().__init__(*args, **kwargs)

        def ParseCANFrame(self, rx_message: Any) -> None:
            super().ParseCANFrame(rx_message)
            if rx_message is None:
                return
            frame_id = getattr(rx_message, "arbitration_id", None)
            timestamp = getattr(rx_message, "timestamp", None)
            if not isinstance(timestamp, (int, float)):
                return
            if frame_id in joint_frame_slices:
                offset, names = joint_frame_slices[frame_id]
                state = super().GetArmJointMsgs().joint_state
                values = tuple(getattr(state, name) for name in names)
                component = offset // 2
                with self._temporal_snapshot_lock:
                    self._temporal_joint_values[offset : offset + 2] = values
                    self._temporal_joint_timestamps[component] = float(timestamp)
                    self._temporal_component_sequences[component] += 1
            elif frame_id == gripper_frame_id:
                state = super().GetArmGripperMsgs().gripper_state
                value = getattr(state, "grippers_angle")
                with self._temporal_snapshot_lock:
                    self._temporal_gripper_value = value
                    self._temporal_gripper_timestamp = float(timestamp)
                    self._temporal_component_sequences[3] += 1

        def GetTemporalObservationSnapshot(self) -> PiperTemporalObservationSnapshot:
            joint_hz = float(super().GetArmJointMsgs().Hz)
            gripper_hz = float(super().GetArmGripperMsgs().Hz)
            with self._temporal_snapshot_lock:
                if (
                    any(value is None for value in self._temporal_joint_values)
                    or any(value is None for value in self._temporal_joint_timestamps)
                    or self._temporal_gripper_value is None
                    or self._temporal_gripper_timestamp is None
                ):
                    raise RuntimeError(
                        "PIPER-X temporal feedback is incomplete; all three joint-pair "
                        "frames and the gripper frame are required."
                    )
                joint_values = cast(
                    tuple[int, int, int, int, int, int],
                    tuple(self._temporal_joint_values),
                )
                joint_timestamps = cast(
                    tuple[float, float, float],
                    tuple(self._temporal_joint_timestamps),
                )
                identity = cast(
                    tuple[int, int, int, int],
                    tuple(self._temporal_component_sequences),
                )
                return PiperTemporalObservationSnapshot(
                    joint_values=joint_values,
                    joint_timestamps=joint_timestamps,
                    joint_hz=joint_hz,
                    gripper_value=self._temporal_gripper_value,
                    gripper_timestamp=self._temporal_gripper_timestamp,
                    gripper_hz=gripper_hz,
                    identity=identity,
                )

    TimestampedPiperInterface.__name__ = "TimestampedPiperInterface"
    TimestampedPiperInterface.__qualname__ = "TimestampedPiperInterface"
    return TimestampedPiperInterface


@lru_cache(maxsize=1)
def get_piper_sdk() -> tuple[type[Any], Any]:
    try:
        from piper_sdk import C_PiperInterface_V2, LogLevel
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("`piper-sdk==0.6.1` is required for PIPER-X robots.") from exc
    return _timestamped_piper_interface(C_PiperInterface_V2), LogLevel


def resolve_piper_can_interface(serial_number: str) -> str:
    """Resolve a USB-CAN adapter serial number to its SocketCAN interface."""
    for interface_path in _SYS_CLASS_NET.iterdir():
        try:
            if (interface_path / "type").read_text().strip() != "280":
                continue
        except OSError:
            continue
        try:
            result = subprocess.run(
                ["udevadm", "info", "--query=property", f"--path={interface_path}"],
                capture_output=True,
                check=False,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("`udevadm` is required to find the PIPER USB-CAN adapter.") from exc
        if f"ID_SERIAL_SHORT={serial_number}" in result.stdout.splitlines():
            return interface_path.name
    raise RuntimeError(f"No PIPER USB-CAN adapter found with serial '{serial_number}'.")


def parse_piper_log_level(level_name: str) -> Any:
    _, log_level_enum = get_piper_sdk()
    try:
        return getattr(log_level_enum, level_name.upper())
    except AttributeError as exc:
        raise ValueError(f"Invalid Piper log level '{level_name}'.") from exc


def wait_enable_piper(arm: Any, timeout_s: float, retry_interval_s: float = 0.2) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() < deadline:
        if bool(arm.EnablePiper()):
            return True
        time.sleep(min(max(0.01, retry_interval_s), deadline - time.monotonic()))
    return False
