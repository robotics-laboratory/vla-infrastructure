"""Concrete PIPER-X MuJoCo Gymnasium environment and LeRobot processors."""

from __future__ import annotations

import gymnasium as gym

from .constants import ENV_ID
from .env import PiperXDualCubeToMatchingPlateMujocoEnv
from .processors import PiperXMujocoActionProcessor, PiperXMujocoObservationProcessor


if ENV_ID not in gym.registry:
    gym.register(
        id=ENV_ID,
        entry_point="lerobot_env_piperx_mujoco.env:PiperXDualCubeToMatchingPlateMujocoEnv",
    )


__all__ = [
    "ENV_ID",
    "PiperXDualCubeToMatchingPlateMujocoEnv",
    "PiperXMujocoActionProcessor",
    "PiperXMujocoObservationProcessor",
]
