"""Thin production integration between LeRobot recording and the D0 temporal envelope.

The upstream ``record_loop`` remains responsible for observation/action processing,
actuation, pacing, and episode lifecycle.  This module only supplies timing at its
existing dataset boundary and delegates accepted frames to ``LeRobotDataset``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import time
from typing import Any, Protocol

from lerobot.teleoperators.teleoperator import Teleoperator

from tools.d0_temporal import SourceTiming, TemporalFrameRecorder


class ObservationTimingSource(Protocol):
    """Robot side-channel populated by the same ``get_observation`` call."""

    def latest_observation_timing(self) -> Mapping[str, SourceTiming]: ...


class FrameTimingProvider(Protocol):
    def current_frame_timing(self) -> Mapping[str, SourceTiming]: ...

    def reset_episode(self) -> None: ...


PoseTimingReader = Callable[[], Mapping[str, SourceTiming]]


class TimestampedTeleoperator(Teleoperator):
    """Delegate an upstream teleoperator while exposing action/XR acquisition timing.

    ``source_action`` is born when ``get_action`` returns, so stamping that event with
    the same host monotonic clock is acquisition time, not a fallback.  XR pose timing
    must be supplied by the XR source itself; host receipt time is deliberately not
    substituted when that metadata is absent.
    """

    def __init__(
        self,
        teleop: Teleoperator,
        *,
        pose_timing_reader: PoseTimingReader | None,
        require_xr: bool,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        if require_xr and pose_timing_reader is None:
            raise ValueError(
                "human_vr recording requires an XR acquisition-timing provider; "
                "host receipt time is not accepted"
            )
        self.teleop = teleop
        self.pose_timing_reader = pose_timing_reader
        self.require_xr = require_xr
        self.monotonic = monotonic
        self._action_sequence = 0
        self._latest_timing: dict[str, SourceTiming] | None = None

    @property
    def action_features(self) -> dict:
        return self.teleop.action_features

    @property
    def feedback_features(self) -> dict:
        return self.teleop.feedback_features

    @property
    def is_connected(self) -> bool:
        return self.teleop.is_connected

    @property
    def is_calibrated(self) -> bool:
        return self.teleop.is_calibrated

    def connect(self, calibrate: bool = True) -> None:
        self.teleop.connect(calibrate=calibrate)

    def calibrate(self) -> None:
        self.teleop.calibrate()

    def configure(self) -> None:
        self.teleop.configure()

    def get_action(self) -> dict[str, Any]:
        action = self.teleop.get_action()
        action_timestamp = self.monotonic()
        self._action_sequence += 1
        timing: dict[str, SourceTiming] = {
            "source_action": SourceTiming(
                self._action_sequence,
                action_timestamp,
                "host_monotonic",
            )
        }
        if self.pose_timing_reader is not None:
            pose_timing = dict(self.pose_timing_reader())
            expected = {"xr.left_pose", "xr.right_pose"}
            if set(pose_timing) != expected:
                raise ValueError(
                    "XR timing provider must return exactly xr.left_pose and xr.right_pose"
                )
            if not all(isinstance(value, SourceTiming) for value in pose_timing.values()):
                raise ValueError("XR timing provider returned incomplete timing metadata")
            timing.update(pose_timing)
        self._latest_timing = timing
        return action

    def send_feedback(self, feedback: dict[str, Any]) -> None:
        self.teleop.send_feedback(feedback)

    def disconnect(self) -> None:
        self.teleop.disconnect()

    def latest_action_timing(self) -> Mapping[str, SourceTiming]:
        if self._latest_timing is None:
            raise RuntimeError("no teleoperator action has been acquired for the current frame")
        return dict(self._latest_timing)

    def reset_episode(self) -> None:
        self._latest_timing = None


class LeRobotFrameTimingProvider:
    """Join the timing emitted by the real Robot and Teleoperator calls."""

    def __init__(
        self,
        robot: ObservationTimingSource,
        teleop: TimestampedTeleoperator,
        required_sources: tuple[str, ...],
    ) -> None:
        if not callable(getattr(robot, "latest_observation_timing", None)):
            raise ValueError("robot does not expose acquisition timing for get_observation")
        self.robot = robot
        self.teleop = teleop
        self.required_sources = required_sources

    def current_frame_timing(self) -> Mapping[str, SourceTiming]:
        raw_timing = {
            **dict(self.robot.latest_observation_timing()),
            **dict(self.teleop.latest_action_timing()),
        }
        timing: dict[str, SourceTiming] = {}
        for source, sample in raw_timing.items():
            if isinstance(sample, SourceTiming):
                timing[source] = sample
                continue
            try:
                timing[source] = SourceTiming(
                    sequence=sample.sequence,
                    source_timestamp=sample.source_timestamp,
                    clock_domain=sample.clock_domain,
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError(f"{source} returned incomplete source timing") from exc
        return timing

    def reset_episode(self) -> None:
        self.teleop.reset_episode()


class TemporalLeRobotDatasetAdapter:
    """Dataset-compatible proxy used directly by upstream ``record_loop``."""

    def __init__(
        self,
        dataset: Any,
        recorder: TemporalFrameRecorder,
        timing_provider: FrameTimingProvider,
        *,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.dataset = dataset
        self.recorder = recorder
        self.timing_provider = timing_provider
        self.monotonic = monotonic

    @property
    def features(self) -> Mapping[str, Mapping[str, Any]]:
        return self.dataset.features

    @property
    def fps(self) -> int:
        return self.dataset.fps

    def add_frame(self, frame: dict[str, Any]) -> None:
        timing = self.timing_provider.current_frame_timing()
        selection_timestamp = self.monotonic()
        self.recorder.add_frame(
            frame,
            timing,
            selection_timestamp=selection_timestamp,
        )

    def save_episode(self, *args: Any, **kwargs: Any) -> Any:
        result = self.dataset.save_episode(*args, **kwargs)
        self._reset_episode_state()
        return result

    def clear_episode_buffer(self, *args: Any, **kwargs: Any) -> Any:
        result = self.dataset.clear_episode_buffer(*args, **kwargs)
        self._reset_episode_state()
        return result

    def _reset_episode_state(self) -> None:
        self.recorder.reset_episode()
        self.timing_provider.reset_episode()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.dataset, name)


def wrap_lerobot_dataset_for_temporal_recording(
    dataset: Any,
    contract: Mapping[str, Any],
    *,
    robot: ObservationTimingSource,
    teleop: Teleoperator,
    source_class: str,
    pose_timing_reader: PoseTimingReader | None = None,
    monotonic: Callable[[], float] = time.perf_counter,
) -> tuple[TemporalLeRobotDatasetAdapter, TimestampedTeleoperator]:
    """Build the only project-owned layer needed by upstream ``record_loop``."""

    timed_teleop = TimestampedTeleoperator(
        teleop,
        pose_timing_reader=pose_timing_reader,
        require_xr=source_class == "human_vr",
        monotonic=monotonic,
    )
    recorder = TemporalFrameRecorder.from_resolved_contract(
        dataset,
        contract,
        source_class=source_class,
        accepted_clock_domains=("host_monotonic",),
    )
    provider = LeRobotFrameTimingProvider(robot, timed_teleop, recorder.required_sources)
    return (
        TemporalLeRobotDatasetAdapter(
            dataset,
            recorder,
            provider,
            monotonic=monotonic,
        ),
        timed_teleop,
    )
