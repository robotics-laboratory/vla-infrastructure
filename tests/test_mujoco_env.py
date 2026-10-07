"""Headless EGL smoke checks for the concrete Gymnasium environment."""

from __future__ import annotations

import gymnasium as gym
import numpy as np

from lerobot_env_piperx_mujoco.constants import ENV_ID, HOME_D0
from lerobot_env_piperx_mujoco.processors import (
    PiperXMujocoActionProcessor,
    PiperXMujocoObservationProcessor,
)


def _home_native_action() -> np.ndarray:
    return PiperXMujocoActionProcessor().action(
        np.concatenate((HOME_D0["left"], HOME_D0["right"]))
    )


def test_registered_environment_reset_step_and_render() -> None:
    env = gym.make(ENV_ID, render_mode="rgb_array")
    try:
        observation, info = env.reset(seed=7)
        assert env.observation_space.contains(observation)
        assert info["settling_physics_ticks"] == 240
        assert info["control_tick"] == 0
        assert info["simulation_time_s"] == 0.0
        assert info["episode_capture_index"] == 1
        reset_capture_serial = env.unwrapped._observation_capture_serial
        d0 = PiperXMujocoObservationProcessor().observation(observation)
        np.testing.assert_allclose(
            d0["observation.state"], np.concatenate((HOME_D0["left"], HOME_D0["right"])), atol=1e-4
        )
        frame = env.render()
        assert frame is not None and frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8 and float(frame.std()) > 1.0
        _, reward, terminated, truncated, step_info = env.step(_home_native_action())
        assert (reward, terminated, truncated) == (0.0, False, False)
        assert step_info["control_tick"] == 1
        assert step_info["episode_capture_index"] == 2
        assert env.unwrapped._observation_capture_serial == reset_capture_serial + 1
        np.testing.assert_allclose(step_info["simulation_time_s"], 1.0 / 30.0, atol=1e-12)
    finally:
        env.close()


def test_reset_is_deterministic_for_level_zero() -> None:
    env = gym.make(ENV_ID)
    try:
        first, _ = env.reset(seed=1)
        first_capture_serial = env.unwrapped._observation_capture_serial
        second, _ = env.reset(seed=999)
        for key in first["qpos"]:
            np.testing.assert_array_equal(first["qpos"][key], second["qpos"][key])
        for key in first["images"]:
            np.testing.assert_array_equal(first["images"][key], second["images"][key])
            assert not np.shares_memory(first["images"][key], second["images"][key])
        assert env.unwrapped._observation_capture_serial == first_capture_serial + 1
    finally:
        env.close()


def test_continuous_teleop_profile_does_not_auto_end_at_m1_horizon() -> None:
    env = gym.make(ENV_ID, terminate_on_task_end=False)
    try:
        env.reset(seed=0)
        env.unwrapped._control_tick = 299
        _, _, terminated, truncated, info = env.step(_home_native_action())
        assert info["control_tick"] == 300
        assert not terminated
        assert not truncated
        assert not env.unwrapped._episode_done
    finally:
        env.close()
