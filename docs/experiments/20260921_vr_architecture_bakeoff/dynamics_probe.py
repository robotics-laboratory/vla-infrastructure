"""Bounded deterministic 120 Hz versus 60 Hz dynamics trace."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _host(value):
    value = getattr(value, "torch", value)
    return value.detach().cpu().numpy().copy()


def _contacts(runtime, dt: float) -> dict[str, float]:
    result = {}
    for side, sensors in runtime.contact_sensors.items():
        magnitudes = []
        for sensor in sensors:
            sensor.update(dt, force_recompute=True)
            magnitudes.append(
                float(np.linalg.norm(_host(sensor.data.net_forces_w), axis=-1).max(initial=0.0))
            )
        result[side] = max(magnitudes, default=0.0)
    return result


def _sample(env, *, tick: int, target: np.ndarray | None, physics_before: int) -> dict:
    physics_step, state = env.capture_measured_state()
    tcp = [
        _host(robot.data.body_link_pose_w)[0, wrist_id].tolist()
        for robot, wrist_id in zip(env.robots, env.wrist_ids, strict=True)
    ]
    cubes = [
        {
            "pose_xyzw": _host(asset.data.root_link_pose_w)[0].tolist(),
            "velocity": _host(asset.data.root_vel_w)[0].tolist(),
        }
        for asset in env.vr_runtime.dynamic_assets
    ]
    return {
        "tick": tick,
        "physics_step": physics_step,
        "physics_delta": physics_step - physics_before,
        "target": None if target is None else target.tolist(),
        "robot_state_deg_mm": list(state),
        "gripper_mm": [state[6], state[13]],
        "tcp_world_xyzw": tcp,
        "cubes": cubes,
        "arm_contact_n": _contacts(env.vr_runtime, float(env.sim.cfg.dt)),
    }


def qualify(env, out: Path) -> int:
    """Run one deterministic four-or-two-step control trajectory and reset assay."""
    import torch
    from isaac_s1_runtime import d0_action_to_native

    out.mkdir(parents=True, exist_ok=True)
    dt = float(env.sim.cfg.dt)
    expected_steps = 4 if abs(dt - 1.0 / 120.0) < 1.0e-12 else 2
    if expected_steps == 2 and abs(dt - 1.0 / 60.0) >= 1.0e-12:
        raise RuntimeError(f"Dynamics probe requires 120 or 60 Hz physics, got dt={dt}")

    env.reset(0)
    reset_start_step = env.sim.get_physics_step_count()
    reset_before = _sample(env, tick=-1, target=None, physics_before=reset_start_step)
    rows = []
    max_contacts = {"left": 0.0, "right": 0.0}
    for tick in range(120):
        target = env.home_d0.copy()
        target[[0, 7]] += 12.0 * np.sin(tick / 13.0)
        target[[3, 10]] += 7.0 * np.cos(tick / 11.0)
        target[[6, 13]] += 20.0 * np.sin(tick / 17.0)
        env._apply(d0_action_to_native(target))

        # One deterministic native-contact impulse stresses the same existing
        # robot/cube collision path at both rates without adding scene assets.
        if tick == 30:
            cube = env.vr_runtime.dynamic_assets[0]
            pose = _host(cube.data.root_link_pose_w)
            pose[0, :3] = _host(env.robots[0].data.body_link_pose_w)[0, env.wrist_ids[0], :3]
            cube.write_root_pose_to_sim_index(
                root_pose=torch.as_tensor(pose, device=env.sim.device)
            )
            cube.write_root_velocity_to_sim_index(
                root_velocity=torch.zeros((1, 6), device=env.sim.device)
            )

        physics_before = env.sim.get_physics_step_count()
        env._advance(4)
        row = _sample(env, tick=tick, target=target, physics_before=physics_before)
        if row["physics_delta"] != expected_steps:
            raise RuntimeError(
                f"tick {tick}: expected {expected_steps} physics steps, got {row['physics_delta']}"
            )
        for side in max_contacts:
            max_contacts[side] = max(max_contacts[side], row["arm_contact_n"][side])
        rows.append(row)

    env.reset(0)
    reset_after_step = env.sim.get_physics_step_count()
    reset_after = _sample(env, tick=120, target=None, physics_before=reset_after_step)
    result = {
        "schema": "live_min60_dynamics_trace_v1",
        "physics_hz": 1.0 / dt,
        "controls": len(rows),
        "physics_steps_per_control": expected_steps,
        "reset_settle_steps": 25,
        "contact_impulse_tick": 30,
        "maximum_arm_contact_n": max_contacts,
        "reset_before": reset_before,
        "rows": rows,
        "reset_after": reset_after,
    }
    (out / "dynamics.json").write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}), flush=True)
    return 0
