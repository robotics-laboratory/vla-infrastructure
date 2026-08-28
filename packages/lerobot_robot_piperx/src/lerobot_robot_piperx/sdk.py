"""Minimal PIPER SDK translation reused by the PIPER-X Robot classes."""

from __future__ import annotations

import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Any


PIPER_JOINT_NAMES = ("joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6")
PIPER_JOINT_ACTION_KEYS = tuple(f"{joint}.pos" for joint in PIPER_JOINT_NAMES)
PIPER_ACTION_KEYS = PIPER_JOINT_ACTION_KEYS + ("gripper.pos",)
PIPER_ROLE_FOLLOWER = 0xFC
_SYS_CLASS_NET = Path("/sys/class/net")


def milli_to_unit(value: float | int) -> float:
    return float(value) * 1e-3


def unit_to_milli(value: float | int) -> int:
    return int(round(float(value) * 1e3))


@lru_cache(maxsize=1)
def get_piper_sdk() -> tuple[type[Any], Any]:
    try:
        from piper_sdk import C_PiperInterface_V2, LogLevel
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("`piper-sdk==0.6.1` is required for PIPER-X robots.") from exc
    return C_PiperInterface_V2, LogLevel


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
