"""Pinned isaacteleop 1.3.131 composition for MuJoCo Quest control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from isaacteleop.retargeters import Se3RelRetargeter, Se3RetargeterConfig
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import BaseRetargeter, OutputCombiner
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    RetargeterIO,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    ControllerInputIndex,
    DLDataType,
    NDArrayType,
)

from tools.isaac_s2_processor import ControllerDeltaSample
from tools.mujoco_quest_control import (
    MujocoQuestTeleopMessageProcessor,
    build_mujoco_quest_control_pipeline,
)


PIPELINE_REVISION = "piperx_mujoco_quest_isaacteleop_pipeline_v6"
POSITION_DEADBAND_M = 0.00025
ROTATION_DEADBAND_RAD = 0.0025


def _as_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "__dlpack__"):
        return np.from_dlpack(value)
    return np.asarray(value)


def _controller_grip_pose_is_usable(controller: Any) -> bool:
    if controller.is_none or not bool(controller[ControllerInputIndex.GRIP_IS_VALID]):
        return False
    position = _as_numpy(controller[ControllerInputIndex.GRIP_POSITION])
    orientation = _as_numpy(controller[ControllerInputIndex.GRIP_ORIENTATION])
    return bool(
        np.isfinite(position).all()
        and np.isfinite(orientation).all()
        and np.linalg.norm(orientation) > 1.0e-8
    )


class TrackingSafeSe3RelRetargeter(Se3RelRetargeter):
    """Reset upstream relative history on every unusable controller pose."""

    def __init__(self, config: Se3RetargeterConfig, name: str) -> None:
        super().__init__(config, name)
        # Upstream's fixed 1 mm / 0.01 rad thresholds discard slow deliberate
        # Quest motion before the v8 half-scale gain can integrate it.
        self._position_threshold = POSITION_DEADBAND_M
        self._rotation_threshold = ROTATION_DEADBAND_RAD

    def _invalidate_relative_reference(self) -> None:
        self._smoothed_delta_pos = np.zeros(3)
        self._smoothed_delta_rot = np.zeros(3)
        self._previous_wrist = np.asarray([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
        self._previous_thumb_tip = None
        self._previous_index_tip = None
        self._first_frame = True

    def reset_relative_reference(self) -> None:
        """Discard pose and smoothing history before a fresh control interval."""

        self._invalidate_relative_reference()

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context: Any) -> None:
        controller = inputs[self._config.input_device]
        if not _controller_grip_pose_is_usable(controller):
            self._invalidate_relative_reference()
            outputs["ee_delta"][0] = np.zeros(6, dtype=np.float32)
            return
        super()._compute_fn(inputs, outputs, context)


class ControllerStateRetargeter(BaseRetargeter):
    """Expose availability, validity, clutch, gripper, mode and reset controls."""

    def __init__(self, side: str, name: str) -> None:
        if side not in (ControllersSource.LEFT, ControllersSource.RIGHT):
            raise ValueError(f"unsupported controller source: {side}")
        self._side = side
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {self._side: OptionalType(ControllerInput())}

    def output_spec(self) -> RetargeterIOType:
        return {
            "state": TensorGroupType(
                "state",
                [NDArrayType("state_array", shape=(6,), dtype=DLDataType.FLOAT, dtype_bits=32)],
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context: Any) -> None:
        del context
        controller = inputs[self._side]
        state = np.zeros(6, dtype=np.float32)
        if not controller.is_none:
            state[:] = (
                1.0,
                float(_controller_grip_pose_is_usable(controller)),
                float(controller[ControllerInputIndex.SQUEEZE_VALUE]),
                float(controller[ControllerInputIndex.TRIGGER_VALUE]),
                float(controller[ControllerInputIndex.THUMBSTICK_CLICK]),
                float(controller[ControllerInputIndex.PRIMARY_CLICK]),
            )
        outputs["state"][0] = state


@dataclass(frozen=True)
class MujocoQuestPipeline:
    controllers: ControllersSource
    graph: OutputCombiner
    pose_retargeters: dict[str, TrackingSafeSe3RelRetargeter]
    control_source: Any
    control_processor: MujocoQuestTeleopMessageProcessor
    control_graph: Any


def build_mujoco_quest_pose_retargeter(
    source: str, name: str
) -> TrackingSafeSe3RelRetargeter:
    """One pinned relative-pose delta configuration shared by runtime and audits."""

    return TrackingSafeSe3RelRetargeter(
        Se3RetargeterConfig(
            input_device=source,
            zero_out_xy_rotation=False,
            use_wrist_rotation=True,
            use_wrist_position=True,
            delta_pos_scale_factor=1.0,
            delta_rot_scale_factor=1.0,
        ),
        name=name,
    )


def build_mujoco_quest_pipeline() -> MujocoQuestPipeline:
    """Build exactly one shared LEFT/RIGHT controller graph."""

    controllers = ControllersSource(name="piper_x_mujoco_quest_controllers")
    connected: dict[str, Any] = {}
    pose_retargeters: dict[str, TrackingSafeSe3RelRetargeter] = {}
    for label, source in (
        ("left", ControllersSource.LEFT),
        ("right", ControllersSource.RIGHT),
    ):
        pose = build_mujoco_quest_pose_retargeter(source, f"{label}_mujoco_quest_delta")
        pose_retargeters[label] = pose
        state = ControllerStateRetargeter(source, name=f"{label}_mujoco_quest_state")
        connected[f"{label}_delta"] = pose.connect(
            {source: controllers.output(source)}
        ).output("ee_delta")
        connected[f"{label}_state"] = state.connect(
            {source: controllers.output(source)}
        ).output("state")
    control_source, control_processor, control_graph = build_mujoco_quest_control_pipeline()
    return MujocoQuestPipeline(
        controllers,
        OutputCombiner(connected),
        pose_retargeters,
        control_source,
        control_processor,
        control_graph,
    )


@dataclass(frozen=True)
class PipelineSample:
    left: ControllerDeltaSample
    right: ControllerDeltaSample
    right_primary_click: float


def unpack_pipeline_output(output: RetargeterIO) -> PipelineSample:
    def arm(side: str) -> tuple[ControllerDeltaSample, np.ndarray]:
        delta = np.asarray(_as_numpy(output[f"{side}_delta"][0]), dtype=np.float64)
        state = np.asarray(_as_numpy(output[f"{side}_state"][0]), dtype=np.float64)
        if delta.shape != (6,) or state.shape != (6,):
            raise RuntimeError(f"unexpected {side} Quest pipeline output shape")
        return (
            ControllerDeltaSample(
                delta_position_m=delta[:3],
                delta_rotation_rotvec_rad=delta[3:],
                available=bool(state[0]),
                grip_pose_valid=bool(state[1]),
                squeeze_value=float(state[2]),
                trigger_value=float(state[3]),
                sensitivity_button_value=float(state[4]),
            ),
            state,
        )

    left, _ = arm("left")
    right, right_state = arm("right")
    return PipelineSample(left, right, float(right_state[5]))
