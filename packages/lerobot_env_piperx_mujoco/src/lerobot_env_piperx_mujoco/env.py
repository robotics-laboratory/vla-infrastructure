"""Concrete Gymnasium environment for the PIPER-X dual-cube MuJoCo task."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gymnasium as gym
import mujoco
import numpy as np
from gymnasium import spaces

from .constants import (
    ACTION_REPEAT,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    CUBE_INITIAL_POSITIONS,
    DEFAULT_MODEL_PATH,
    HORIZON,
    HOME_D0,
    NATIVE_ACTION_HIGH,
    NATIVE_ACTION_LOW,
    NATIVE_STATE_NAMES,
    PLATE_POSITIONS,
    SETTLING_TICKS,
    SIDES,
)


class PiperXDualCubeToMatchingPlateMujocoEnv(gym.Env[dict[str, Any], np.ndarray]):
    """One exact bimanual PIPER-X task; this is not a simulator abstraction."""

    metadata = {"render_modes": ["rgb_array"], "render_fps": 30}
    reward_range = (0.0, 1.0)

    def __init__(
        self,
        render_mode: str | None = None,
        model_path: str | Path | None = None,
        terminate_on_task_end: bool = True,
    ) -> None:
        if render_mode not in (None, "rgb_array"):
            raise ValueError(f"unsupported render_mode: {render_mode}")
        self.render_mode = render_mode
        self.terminate_on_task_end = bool(terminate_on_task_end)
        self.model_path = Path(model_path) if model_path is not None else DEFAULT_MODEL_PATH
        self.model = mujoco.MjModel.from_xml_path(str(self.model_path))
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, height=CAMERA_HEIGHT, width=CAMERA_WIDTH)
        self.render_options = mujoco.MjvOption()
        self.render_options.geomgroup[0] = 0
        self.action_space = spaces.Box(
            low=NATIVE_ACTION_LOW, high=NATIVE_ACTION_HIGH, dtype=np.float64
        )
        self.observation_space = spaces.Dict(
            {
                "qpos": spaces.Dict(
                    {
                        name: spaces.Box(low=-np.inf, high=np.inf, shape=(1,), dtype=np.float64)
                        for name in NATIVE_STATE_NAMES
                    }
                ),
                "images": spaces.Dict(
                    {
                        role: spaces.Box(
                            low=0,
                            high=255,
                            shape=(CAMERA_HEIGHT, CAMERA_WIDTH, 3),
                            dtype=np.uint8,
                        )
                        for role in ("left_wrist", "right_wrist")
                    }
                ),
            }
        )
        self._actuator_ids = {
            side: [
                self.model.actuator(f"{side}_joint{index}_position").id
                for index in range(1, 7)
            ]
            for side in SIDES
        }
        self._gripper_aperture_actuator_ids = {
            side: self.model.actuator(f"{side}_gripper_aperture_position").id
            for side in SIDES
        }
        self._robot_geom_ids = self._descendant_geom_ids(
            "left_base_link"
        ) | self._descendant_geom_ids("right_base_link")
        self._cube_geom_ids = {side: self.model.geom(f"{side}_cube_geom").id for side in SIDES}
        self._stable_ticks = {side: 0 for side in SIDES}
        self._control_tick = 0
        self._observation_capture_serial = 0
        self._episode_capture_index = 0
        self._episode_done = False

    def _descendant_geom_ids(self, root_name: str) -> set[int]:
        root_id = self.model.body(root_name).id
        body_ids = {root_id}
        changed = True
        while changed:
            changed = False
            for body_id in range(1, self.model.nbody):
                if int(self.model.body_parentid[body_id]) in body_ids and body_id not in body_ids:
                    body_ids.add(body_id)
                    changed = True
        return {
            geom_id
            for geom_id in range(self.model.ngeom)
            if int(self.model.geom_bodyid[geom_id]) in body_ids
        }

    @staticmethod
    def _home_native(side: str) -> np.ndarray:
        d0 = HOME_D0[side]
        return np.concatenate((np.deg2rad(d0[:6]), [d0[6] / 1000.0]))

    def _write_home_state(self) -> None:
        mujoco.mj_resetData(self.model, self.data)
        for side in SIDES:
            home = self._home_native(side)
            for index, value in enumerate(home[:6], start=1):
                self.data.joint(f"{side}_joint{index}").qpos = value
            self.data.joint(f"{side}_gripper").qpos = home[6]
            self.data.joint(f"{side}_gripper_joint1").qpos = 0.5 * home[6]
            self.data.joint(f"{side}_gripper_joint2").qpos = -0.5 * home[6]
            self.data.ctrl[self._actuator_ids[side]] = home[:6]
            self.data.ctrl[self._gripper_aperture_actuator_ids[side]] = home[6]
            cube_qpos = self.data.joint(f"{side}_cube_free").qpos
            cube_qpos[:3] = CUBE_INITIAL_POSITIONS[side]
            cube_qpos[3:] = (1.0, 0.0, 0.0, 0.0)
        self.data.qvel.fill(0.0)
        self.data.qacc_warmstart.fill(0.0)
        self.data.qfrc_applied.fill(0.0)
        self.data.xfrc_applied.fill(0.0)
        if self.data.act.size:
            self.data.act.fill(0.0)
        mujoco.mj_forward(self.model, self.data)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        super().reset(seed=seed)
        if options:
            raise ValueError(f"reset options are not supported by Level-0 reset: {sorted(options)}")
        self._write_home_state()
        for _ in range(SETTLING_TICKS):
            mujoco.mj_step(self.model, self.data)
        if not np.isfinite(self.data.qpos).all() or not np.isfinite(self.data.qvel).all():
            raise RuntimeError("non-finite MuJoCo state after settling")
        self.data.time = 0.0
        mujoco.mj_forward(self.model, self.data)
        self._stable_ticks = {side: 0 for side in SIDES}
        self._control_tick = 0
        self._episode_capture_index = 0
        self._episode_done = False
        observation = self._native_observation()
        info = self._task_info(native_action_saturated=False)
        info["reset_seed"] = seed
        info["settling_physics_ticks"] = SETTLING_TICKS
        return observation, info

    def step(self, action: np.ndarray) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        if self._episode_done:
            raise RuntimeError("step called after terminated/truncated episode; call reset()")
        native = np.asarray(action, dtype=np.float64)
        if native.shape != (14,) or not np.isfinite(native).all():
            raise ValueError(f"native action must be finite shape (14,), got {native.shape}")
        clipped = np.clip(native, NATIVE_ACTION_LOW, NATIVE_ACTION_HIGH)
        saturated = not np.array_equal(native, clipped)
        for side, offset in (("left", 0), ("right", 7)):
            side_target = clipped[offset : offset + 7]
            self.data.ctrl[self._actuator_ids[side]] = side_target[:6]
            self.data.ctrl[self._gripper_aperture_actuator_ids[side]] = side_target[6]
        for _ in range(ACTION_REPEAT):
            mujoco.mj_step(self.model, self.data)
        self._control_tick += 1
        if not np.isfinite(self.data.qpos).all() or not np.isfinite(self.data.qvel).all():
            raise RuntimeError("non-finite MuJoCo state after step")

        observation = self._native_observation()
        info = self._task_info(native_action_saturated=saturated)
        terminated = self.terminate_on_task_end and bool(info["success"])
        truncated = self.terminate_on_task_end and self._control_tick >= HORIZON and not terminated
        reward = 1.0 if terminated else 0.0
        self._episode_done = terminated or truncated
        return observation, reward, terminated, truncated, info

    def _cube_has_robot_contact(self, side: str) -> bool:
        cube_geom = self._cube_geom_ids[side]
        for contact_index in range(self.data.ncon):
            contact = self.data.contact[contact_index]
            pair = {int(contact.geom1), int(contact.geom2)}
            if cube_geom in pair and pair.intersection(self._robot_geom_ids):
                return True
        return False

    def _task_info(self, *, native_action_saturated: bool) -> dict[str, Any]:
        sides: dict[str, dict[str, Any]] = {}
        for side in SIDES:
            cube = self.data.body(f"{side}_cube")
            distance = float(np.linalg.norm(cube.xpos[:2] - PLATE_POSITIONS[side][:2]))
            speed = float(np.linalg.norm(cube.cvel[3:]))
            released = not self._cube_has_robot_contact(side)
            predicate = distance <= 0.06 and released and speed < 0.05
            self._stable_ticks[side] = self._stable_ticks[side] + 1 if predicate else 0
            sides[side] = {
                "cube_plate_xy_distance_m": distance,
                "cube_linear_speed_m_s": speed,
                "released": released,
                "predicate": predicate,
                "stable_ticks": self._stable_ticks[side],
            }
        return {
            "task_id": "PiperX-DualCubeToMatchingPlate-v1",
            "task_revision": "dual_cube_plate_success_v1",
            "control_tick": self._control_tick,
            "simulation_time_s": float(self.data.time),
            "episode_capture_index": self._episode_capture_index,
            "native_action_saturated": native_action_saturated,
            "sides": sides,
            "success": all(self._stable_ticks[side] >= 5 for side in SIDES),
        }

    def _render_camera(self, name: str) -> np.ndarray:
        self.renderer.update_scene(
            self.data, camera=name, scene_option=self.render_options
        )
        return self.renderer.render().copy(order="C")

    def _native_observation(self) -> dict[str, Any]:
        qpos: dict[str, np.ndarray] = {}
        for name in NATIVE_STATE_NAMES:
            if name.endswith("_gripper"):
                side = name.removesuffix("_gripper")
                value = float(
                    self.data.joint(f"{side}_gripper_joint1").qpos[0]
                    - self.data.joint(f"{side}_gripper_joint2").qpos[0]
                )
            else:
                value = float(self.data.joint(name).qpos[0])
            qpos[name] = np.asarray([value], dtype=np.float64)
        images = {
            "left_wrist": self._render_camera("left_wrist"),
            "right_wrist": self._render_camera("right_wrist"),
        }
        self._observation_capture_serial += 1
        self._episode_capture_index += 1
        return {
            "qpos": qpos,
            "images": images,
        }

    def render(self) -> np.ndarray | None:
        if self.render_mode != "rgb_array":
            return None
        return self._render_camera("scene")

    def close(self) -> None:
        self.renderer.close()
