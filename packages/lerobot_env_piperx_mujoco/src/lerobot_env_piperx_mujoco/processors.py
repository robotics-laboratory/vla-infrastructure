"""LeRobot processor steps for the concrete PIPER-X/MuJoCo semantic edge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import torch
from lerobot.configs import FeatureType, PipelineFeatureType, PolicyFeature
from lerobot.lerobot_types import EnvAction, EnvTransition, PolicyAction, RobotAction, TransitionKey
from lerobot.processor import ActionProcessorStep, ObservationProcessorStep, ProcessorStepRegistry

from .constants import (
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    JOINT_LIMITS_DEG,
    NATIVE_STATE_NAMES,
    SIDES,
)


PROCESSOR_REVISION = "piper_x_d0_mujoco_edge_v1"


def _checked_vector(value: Any, *, name: str) -> np.ndarray:
    if isinstance(value, torch.Tensor):
        value = value.detach().cpu().numpy()
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (14,):
        raise ValueError(f"{name} must have shape (14,), got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains a non-finite value")
    return array.copy()


@dataclass
@ProcessorStepRegistry.register(name="piperx_mujoco_action_processor")
class PiperXMujocoActionProcessor(ActionProcessorStep):
    """Map D0 degrees/signed-mm to clipped MuJoCo radians/aperture targets."""

    last_d0_action: np.ndarray | None = field(default=None, init=False, repr=False)
    last_saturation_mask: np.ndarray | None = field(default=None, init=False, repr=False)

    def action(
        self, action: PolicyAction | RobotAction | EnvAction
    ) -> PolicyAction | RobotAction | EnvAction:
        d0 = _checked_vector(action, name="D0 action")
        native = np.empty(14, dtype=np.float64)
        saturation = np.zeros(14, dtype=np.bool_)
        for offset in (0, 7):
            source_joints = d0[offset : offset + 6]
            clipped_joints = np.clip(source_joints, JOINT_LIMITS_DEG[:, 0], JOINT_LIMITS_DEG[:, 1])
            source_gripper = d0[offset + 6]
            clipped_gripper = float(np.clip(source_gripper, 0.0, 100.0))
            native[offset : offset + 6] = np.deg2rad(clipped_joints)
            native[offset + 6] = clipped_gripper / 1000.0
            saturation[offset : offset + 6] = source_joints != clipped_joints
            saturation[offset + 6] = source_gripper != clipped_gripper
        self.last_d0_action = d0
        self.last_saturation_mask = saturation
        return native

    def __call__(self, transition: EnvTransition) -> EnvTransition:
        processed = super().__call__(transition)
        info = dict(processed.get(TransitionKey.INFO) or {})
        info["piperx_mujoco_processor_revision"] = PROCESSOR_REVISION
        info["piperx_mujoco_action_saturated"] = bool(
            self.last_saturation_mask is not None and self.last_saturation_mask.any()
        )
        if self.last_saturation_mask is not None:
            info["piperx_mujoco_saturation_mask"] = self.last_saturation_mask.copy()
        if self.last_d0_action is not None:
            info["dataset_action_t"] = self.last_d0_action.copy()
        processed[TransitionKey.INFO] = info
        return processed

    def get_config(self) -> dict[str, Any]:
        return {"revision": PROCESSOR_REVISION, "native_order": list(NATIVE_STATE_NAMES)}

    def transform_features(
        self, features: dict[PipelineFeatureType, dict[str, PolicyFeature]]
    ) -> dict[PipelineFeatureType, dict[str, PolicyFeature]]:
        return features.copy()


@dataclass
@ProcessorStepRegistry.register(name="piperx_mujoco_observation_processor")
class PiperXMujocoObservationProcessor(ObservationProcessorStep):
    """Map named MuJoCo qpos and wrist RGB to the accepted raw D0 observation."""

    def observation(self, observation: dict[str, Any]) -> dict[str, np.ndarray]:
        qpos = observation.get("qpos")
        images = observation.get("images")
        if not isinstance(qpos, dict) or not isinstance(images, dict):
            raise ValueError("native observation requires qpos and images dictionaries")

        state_parts: list[float] = []
        for side in SIDES:
            for index in range(1, 7):
                state_parts.append(float(np.rad2deg(self._scalar(qpos, f"{side}_joint{index}"))))
            state_parts.append(abs(self._scalar(qpos, f"{side}_gripper")) * 1000.0)

        return {
            "observation.state": np.asarray(state_parts, dtype=np.float32),
            "observation.images.left_wrist": self._rgb(images, "left_wrist"),
            "observation.images.right_wrist": self._rgb(images, "right_wrist"),
        }

    @staticmethod
    def _scalar(values: dict[str, Any], name: str) -> float:
        array = np.asarray(values.get(name), dtype=np.float64)
        if array.shape != (1,) or not np.isfinite(array).all():
            raise ValueError(f"native qpos {name} must be one finite value")
        return float(array[0])

    @staticmethod
    def _rgb(images: dict[str, Any], role: str) -> np.ndarray:
        image = np.asarray(images.get(role))
        expected = (CAMERA_HEIGHT, CAMERA_WIDTH, 3)
        if image.shape != expected or image.dtype != np.uint8:
            raise ValueError(
                f"{role} must be uint8 RGB HWC {expected}, got {image.shape}/{image.dtype}"
            )
        return np.ascontiguousarray(image)

    def get_config(self) -> dict[str, Any]:
        return {"revision": PROCESSOR_REVISION, "native_order": list(NATIVE_STATE_NAMES)}

    def transform_features(
        self, features: dict[PipelineFeatureType, dict[str, PolicyFeature]]
    ) -> dict[PipelineFeatureType, dict[str, PolicyFeature]]:
        transformed = {feature_type: bucket.copy() for feature_type, bucket in features.items()}
        transformed[PipelineFeatureType.OBSERVATION] = {
            "observation.state": PolicyFeature(type=FeatureType.STATE, shape=(14,)),
            "observation.images.left_wrist": PolicyFeature(
                type=FeatureType.VISUAL, shape=(CAMERA_HEIGHT, CAMERA_WIDTH, 3)
            ),
            "observation.images.right_wrist": PolicyFeature(
                type=FeatureType.VISUAL, shape=(CAMERA_HEIGHT, CAMERA_WIDTH, 3)
            ),
        }
        return transformed
