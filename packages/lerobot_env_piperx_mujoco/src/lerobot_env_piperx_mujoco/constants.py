"""Frozen names and units for the concrete PIPER-X MuJoCo boundary."""

from __future__ import annotations

from pathlib import Path

import numpy as np


ENV_ID = "PiperX-DualCubeToMatchingPlate-Mujoco-v0"
PACKAGE_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MODEL_PATH = PACKAGE_ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml"

CAMERA_HEIGHT = 480
CAMERA_WIDTH = 640
PHYSICS_HZ = 240
ACTION_REPEAT = 8
SETTLING_TICKS = PHYSICS_HZ
HORIZON = 300

SIDES = ("left", "right")
ARM_JOINT_NAMES = tuple(f"joint{index}" for index in range(1, 7))
NATIVE_STATE_NAMES = tuple(
    f"{side}_{name}" for side in SIDES for name in (*ARM_JOINT_NAMES, "gripper")
)
HOME_D0 = {
    "left": np.asarray([-20.0, 90.0, -50.0, 0.0, 0.0, 0.0, 50.0]),
    "right": np.asarray([20.0, 90.0, -50.0, 0.0, 0.0, 0.0, 50.0]),
}
JOINT_LIMITS_DEG = np.asarray(
    [
        [-150.0, 150.0],
        [0.0, 180.0],
        [-170.0, 0.0],
        [-89.0, 89.0],
        [-89.0, 89.0],
        [-120.0, 120.0],
    ],
    dtype=np.float64,
)
NATIVE_ACTION_LOW = np.concatenate(
    (np.deg2rad(JOINT_LIMITS_DEG[:, 0]), [0.0], np.deg2rad(JOINT_LIMITS_DEG[:, 0]), [0.0])
)
NATIVE_ACTION_HIGH = np.concatenate(
    (np.deg2rad(JOINT_LIMITS_DEG[:, 1]), [0.1], np.deg2rad(JOINT_LIMITS_DEG[:, 1]), [0.1])
)
CUBE_INITIAL_POSITIONS = {
    "left": np.asarray([0.52, 0.17, 0.847]),
    "right": np.asarray([0.52, -0.17, 0.847]),
}
PLATE_POSITIONS = {
    "left": np.asarray([0.72, 0.17, 0.831]),
    "right": np.asarray([0.72, -0.17, 0.831]),
}
