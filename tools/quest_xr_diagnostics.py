#!/usr/bin/env python3
"""Host-side, bimanual Quest controller diagnostics for Gate B.

This module owns one NVIDIA ``TeleopSession`` per process and exposes the two
outputs of one ``ControllersSource``.  It deliberately has no Robot, CAN, IK,
frame-calibration, dataset, or action-send dependency.
"""

from __future__ import annotations

import argparse
import json
import socket
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Literal

import numpy as np

from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import ExecutionEvents, ExecutionState, OutputCombiner
from isaacteleop.retargeting_engine.tensor_types.indices import ControllerInputIndex
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig

Hand = Literal["left", "right"]

_CLOUDXR_WEB_CLIENT_URL = "https://nvidia.github.io/IsaacTeleop/client/release-1.4.x/"
_CLOUDXR_WSS_PORT = 48322


@dataclass(frozen=True)
class ControllerDiagnostic:
    """One raw controller sample, with validity kept distinct from availability."""

    hand: Hand
    availability: Literal["available", "unavailable", "malformed"]
    host_receipt_monotonic_ns: int
    grip_position: list[float] | None
    grip_orientation_xyzw: list[float] | None
    tracking: dict[str, bool | None]
    controls: dict[str, float | None]


class SharedQuestSession:
    """The sole Gate-B construction path for a shared left/right TeleopSession.

    ``ControllersSource`` creates one NVIDIA controller tracker and offers both
    outputs.  This class blocks a second live project instance in the process;
    it never creates a per-hand session.
    """

    _active_owner: "SharedQuestSession | None" = None
    _session_instances_created = 0

    def __init__(
        self,
        *,
        app_name: str = "PiperXQuest3BimanualDiagnostics",
        cloudxr_env_file: str | None = None,
        auto_launch_cloudxr: bool = True,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.app_name = app_name
        self.cloudxr_env_file = cloudxr_env_file
        self.auto_launch_cloudxr = auto_launch_cloudxr
        self._monotonic_ns = monotonic_ns
        self._cloudxr_launcher: CloudXRLauncher | None = None
        self._controllers: ControllersSource | None = None
        self._session: TeleopSession | None = None
        self._state = "new"
        self.events: list[dict[str, Any]] = []

    @property
    def session_instances_created(self) -> int:
        """Count of project TeleopSession constructions in this process."""
        return type(self)._session_instances_created

    @property
    def is_running(self) -> bool:
        return self._session is not None

    def lifecycle_status(self) -> dict[str, Any]:
        """Return only lifecycle facts observable by this host-side code."""
        return {
            "cloudxr_auto_launch": self.auto_launch_cloudxr,
            "cloudxr_launcher_owned": self._cloudxr_launcher is not None,
            "nvidia_client_connection_state": "not_exposed_by_pinned_api",
            "process_local_session_instances_created": self.session_instances_created,
            "session_state": self._state,
            "shared_controller_source": self._controllers is not None,
        }

    def start(self) -> None:
        """Start CloudXR (if owned) then construct and enter one shared session."""
        if self._session is not None:
            raise RuntimeError("Quest diagnostic session is already running.")
        if type(self)._active_owner not in (None, self):
            raise RuntimeError("A Gate-B TeleopSession is already live in this process.")

        self._state = "starting"
        try:
            if self.auto_launch_cloudxr:
                self._cloudxr_launcher = CloudXRLauncher(
                    install_dir=str(Path.home() / ".cloudxr"),
                    env_config=self.cloudxr_env_file,
                    accept_eula=False,
                )
                self._event("cloudxr_launcher_created")

            self._controllers = ControllersSource(name="quest_bimanual_controllers")
            pipeline = OutputCombiner(
                {
                    "left": self._controllers.output(ControllersSource.LEFT),
                    "right": self._controllers.output(ControllersSource.RIGHT),
                }
            )
            self._session = TeleopSession(TeleopSessionConfig(app_name=self.app_name, pipeline=pipeline))
            type(self)._session_instances_created += 1
            self._event("teleop_session_constructed")
            self._session.__enter__()
            type(self)._active_owner = self
            self._state = "running"
            self._event("teleop_session_started")
        except Exception:
            self._state = "failed"
            self._stop_after_failed_start()
            raise

    def poll(self) -> dict[str, Any]:
        """Read both streams from one session and stamp their host receipt time."""
        if self._session is None:
            raise RuntimeError("Quest diagnostic session is not running.")

        result = self._session.step(
            execution_events=ExecutionEvents(execution_state=ExecutionState.RUNNING, reset=False)
        )
        receipt_ns = self._monotonic_ns()
        left = self._extract_controller("left", result["left"], receipt_ns)
        right = self._extract_controller("right", result["right"], receipt_ns)
        step_info = self._session.last_step_info
        snapshot = {
            "event": "controller_sample",
            "lifecycle": self.lifecycle_status(),
            "left": asdict(left),
            "right": asdict(right),
            "session_step": {
                "frame_deadline_miss": getattr(step_info, "frame_deadline_miss", None),
                "returned_age_frames": getattr(step_info, "returned_age_frames", None),
            },
        }
        return snapshot

    def close(self) -> None:
        """Tear down the OpenXR session before the CloudXR runtime."""
        session, self._session = self._session, None
        try:
            if session is not None:
                session.__exit__(None, None, None)
                self._event("teleop_session_stopped")
        finally:
            if type(self)._active_owner is self:
                type(self)._active_owner = None
            self._stop_cloudxr()
            if self._state != "failed":
                self._state = "stopped"
                self._event("diagnostic_stopped")

    def _stop_after_failed_start(self) -> None:
        session, self._session = self._session, None
        try:
            if session is not None:
                session.__exit__(None, None, None)
        finally:
            self._stop_cloudxr()

    def _stop_cloudxr(self) -> None:
        launcher, self._cloudxr_launcher = self._cloudxr_launcher, None
        if launcher is not None:
            launcher.stop()
            self._event("cloudxr_launcher_stopped")

    def _event(self, event: str) -> None:
        self.events.append(
            {
                "event": event,
                "process_local_session_instances_created": self.session_instances_created,
                "session_state": self._state,
            }
        )

    @staticmethod
    def _extract_controller(hand: Hand, controller: Any, receipt_ns: int) -> ControllerDiagnostic:
        controls: dict[str, float | None] = {
            "primary_click": None,
            "secondary_click": None,
            "thumbstick_x": None,
            "thumbstick_y": None,
            "thumbstick_click": None,
            "menu_click": None,
            "squeeze_value": None,
            "trigger_value": None,
        }
        tracking: dict[str, bool | None] = {
            "controller_available": False,
            "grip_pose_valid": None,
            "aim_pose_valid": None,
        }
        if getattr(controller, "is_none", False):
            return ControllerDiagnostic(hand, "unavailable", receipt_ns, None, None, tracking, controls)

        tracking["controller_available"] = True
        try:
            position = np.asarray(controller[ControllerInputIndex.GRIP_POSITION], dtype=float).tolist()
            orientation = np.asarray(
                controller[ControllerInputIndex.GRIP_ORIENTATION], dtype=float
            ).tolist()
            tracking["grip_pose_valid"] = bool(controller[ControllerInputIndex.GRIP_IS_VALID])
            tracking["aim_pose_valid"] = bool(controller[ControllerInputIndex.AIM_IS_VALID])
            for name, index in (
                ("primary_click", ControllerInputIndex.PRIMARY_CLICK),
                ("secondary_click", ControllerInputIndex.SECONDARY_CLICK),
                ("thumbstick_x", ControllerInputIndex.THUMBSTICK_X),
                ("thumbstick_y", ControllerInputIndex.THUMBSTICK_Y),
                ("thumbstick_click", ControllerInputIndex.THUMBSTICK_CLICK),
                ("menu_click", ControllerInputIndex.MENU_CLICK),
                ("squeeze_value", ControllerInputIndex.SQUEEZE_VALUE),
                ("trigger_value", ControllerInputIndex.TRIGGER_VALUE),
            ):
                controls[name] = float(controller[index])
        except (IndexError, KeyError, TypeError, ValueError):
            return ControllerDiagnostic(hand, "malformed", receipt_ns, None, None, tracking, controls)
        return ControllerDiagnostic(hand, "available", receipt_ns, position, orientation, tracking, controls)


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _host_connection_hint() -> dict[str, Any]:
    """Reuse the official example's primary-IPv4 discovery for the CloudXR client."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("8.8.8.8", 80))
            host_ipv4: str | None = sock.getsockname()[0]
        except OSError:
            host_ipv4 = None
    return {
        "cloudxr_web_client_url": _CLOUDXR_WEB_CLIENT_URL,
        "host_ipv4": host_ipv4,
        "self_signed_certificate_url": (
            f"https://{host_ipv4}:{_CLOUDXR_WSS_PORT}/" if host_ipv4 is not None else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloudxr-env-file", default=None)
    parser.add_argument("--no-auto-launch-cloudxr", action="store_true")
    parser.add_argument("--sample-period-s", type=float, default=0.25)
    parser.add_argument("--max-samples", type=int, default=0, help="0 means run until Ctrl-C.")
    args = parser.parse_args()

    diagnostic = SharedQuestSession(
        cloudxr_env_file=args.cloudxr_env_file,
        auto_launch_cloudxr=not args.no_auto_launch_cloudxr,
    )
    _print_json(
        {
            "event": "diagnostic_created",
            "lifecycle": diagnostic.lifecycle_status(),
            "quest_connection": _host_connection_hint(),
        }
    )
    diagnostic.start()
    for event in diagnostic.events:
        _print_json(event)
    samples = 0
    try:
        while args.max_samples == 0 or samples < args.max_samples:
            _print_json(diagnostic.poll())
            samples += 1
            time.sleep(args.sample_period_s)
    except KeyboardInterrupt:
        _print_json({"event": "keyboard_interrupt"})
    finally:
        diagnostic.close()
        for event in diagnostic.events:
            if event["event"] in {"teleop_session_stopped", "cloudxr_launcher_stopped", "diagnostic_stopped"}:
                _print_json(event)


if __name__ == "__main__":
    main()
