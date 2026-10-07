#!/usr/bin/env python3
"""Run the deterministic M1 MuJoCo reset/step/render smoke."""

from __future__ import annotations

import argparse
import json
import os

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/piperx-mujoco-cache")

import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402

from lerobot_env_piperx_mujoco import ENV_ID  # noqa: E402
from lerobot_env_piperx_mujoco.processors import (  # noqa: E402
    PiperXMujocoActionProcessor,
    PiperXMujocoObservationProcessor,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.steps < 1:
        parser.error("--steps must be positive")

    action_processor = PiperXMujocoActionProcessor()
    observation_processor = PiperXMujocoObservationProcessor()
    env = gym.make(ENV_ID, render_mode="rgb_array")
    try:
        native_observation, reset_info = env.reset(seed=args.seed)
        d0_observation = observation_processor.observation(native_observation)
        last_info = reset_info
        for _ in range(args.steps):
            d0_action = d0_observation["observation.state"].astype(np.float64)
            native_action = action_processor.action(d0_action)
            native_observation, _, terminated, truncated, last_info = env.step(native_action)
            d0_observation = observation_processor.observation(native_observation)
            if terminated or truncated:
                break
        frame = env.render()
        if not isinstance(frame, np.ndarray):
            raise RuntimeError("rgb_array render did not return an ndarray")
        report = {
            "environment_id": ENV_ID,
            "seed": args.seed,
            "requested_steps": args.steps,
            "executed_control_ticks": last_info["control_tick"],
            "processor_revision": action_processor.get_config()["revision"],
            "observation_state_shape": list(d0_observation["observation.state"].shape),
            "wrist_rgb_shape": list(d0_observation["observation.images.left_wrist"].shape),
            "scene_rgb_shape": list(frame.shape),
            "scene_rgb_std": float(frame.std()),
            "success": bool(last_info["success"]),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
    finally:
        env.close()


if __name__ == "__main__":
    main()
