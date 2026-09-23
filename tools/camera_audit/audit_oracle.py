"""Reuse the frozen native witness assay, retain pixels, tighten classification."""

from collections import Counter
import json
import os
import time
from typing import Any
from pathlib import Path

import numpy as np

ROLES = ("left_wrist", "right_wrist", "scene")


def classify(errors, separation):
    """Reject poor absolute matches as well as ambiguous nearest references."""
    if set(errors) != {"0", "-1", "-2", "-3"} or not np.isfinite(separation) or separation < 10:
        return "unresolved"
    ordered = sorted(errors, key=errors.get)
    best, second = (errors[key] for key in ordered[:2])
    if not np.isfinite(list(errors.values())).all():
        return "unresolved"
    if best > separation * 0.4 or second - best < max(5.0, separation * 0.25):
        return "unresolved"
    return int(ordered[0])


def run(env, out: Path, count, counters, drawables):
    import deferred_probe

    count += 4  # Declared stimulus warmup; every boundary remains in the raw log.

    # Use the same native-cube assay for both producers; the historical batched
    # helper additionally requires wrist teleports, deliberately held fixed here.
    os.environ["VR_BAKEOFF_CANDIDATE"] = "LIVE-MIN120-DEFERRED"
    if os.environ["CAMERA_AUDIT_BATCH"] == "1":
        from batched_camera import ownership

        (out / "batched-ownership.json").write_text(json.dumps(ownership(env), indent=2))
    images = out / "images"
    images.mkdir()
    capture = env.camera.capture
    previous_freeze = capture.freeze
    sequence: list[dict[str, Any]] = []
    states = {}
    boundaries = []
    applying = False
    sentinel = os.environ.get("CAMERA_AUDIT_SENTINEL") == "1"
    moving = os.environ.get("CAMERA_AUDIT_MOVING_WRISTS") == "1"

    def stimulus_slot(n):
        return (n - n // 11) % 4 if sentinel else n % 4

    tick = [0]
    reference_slot = [-1]
    previous_advance = env._advance
    previous_forward = env.sim.forward
    previous_render = env.sim.render
    # The old finger teleports can excite constraint corrections and move wrists.
    # Keep canonical articulation targets; move only the existing native cubes.
    robot_methods = []
    for side, robot in enumerate(env.robots):
        base_q = deferred_probe._host(robot.data.joint_pos)
        for obj, name in (
            (robot, "write_joint_position_to_sim_index"),
            (robot, "write_joint_velocity_to_sim_index"),
            (robot.actuators.target_command, "set_position_index"),
        ):
            robot_methods.append((obj, name, getattr(obj, name)))
            if not moving:
                setattr(obj, name, lambda *a, **kw: None)
                continue
            original_joint = getattr(obj, name)

            def move_joint(*a, side=side, base_q=base_q, name=name, original=original_joint, **kw):
                import torch

                if "velocity" in name:
                    return original(*a, **kw)
                slot = stimulus_slot(tick[0] + int(applying))
                q = base_q.copy()
                q[0, env.joint_ids[side][0]] += (-0.12, -0.04, 0.04, 0.12)[slot]
                aperture = (0.02, 0.04, 0.06, 0.08)[slot]
                q[0, env.joint_ids[side][-1]] = aperture
                q[0, env.actuated_joint_ids[side][-2]] = aperture / 2
                q[0, env.actuated_joint_ids[side][-1]] = -aperture / 2
                kw["position" if name.startswith("write") else "value"] = torch.as_tensor(
                    q, device=env.sim.device
                )
                return original(*a, **kw)

            setattr(obj, name, move_joint)

    from isaac_s1_runtime import quaternion_xyzw_to_matrix

    cube_methods = []
    old_positions = (
        ((0.62, 0.17, 0.96), (0.62, 0.17, 1.01), (0.62, 0.10, 1.01), (0.62, 0.10, 0.94)),
        ((0.62, -0.17, 0.92), (0.62, -0.17, 0.96), (0.62, -0.10, 1.00), (0.62, -0.10, 0.93)),
    )
    for side, cube in enumerate(env.vr_runtime.dynamic_assets[:2]):
        camera = env.camera.wrists[side]
        center = deferred_probe._host(camera.data.pos_w)[0]
        rotation = quaternion_xyzw_to_matrix(deferred_probe._host(camera.data.quat_w_opengl)[0])
        positions = [
            center + rotation @ np.asarray([x, y, -0.30])
            for x, y in ((-0.07, -0.07), (-0.07, 0.07), (0.07, 0.07), (0.07, -0.07))
        ]
        original = cube.write_root_pose_to_sim_index
        cube_methods.append((cube, original))

        def move(*, root_pose, side=side, positions=positions, original=original, **kw):
            value = root_pose.clone()
            supplied = deferred_probe._host(value)[0, :3]
            slot = int(
                np.argmin(np.linalg.norm(np.asarray(old_positions[side]) - supplied, axis=1))
            )
            if applying:
                slot = stimulus_slot(tick[0] + 1)
            import torch

            value[0, :3] = torch.as_tensor(positions[slot], device=env.sim.device)
            return original(root_pose=value, **kw)

        cube.write_root_pose_to_sim_index = move

    def advance(repeat):
        nonlocal applying
        before = dict(counters)
        before_drawables = dict(drawables)
        started = time.perf_counter_ns()
        applying = True
        try:
            previous_advance(repeat)
        finally:
            applying = False
        boundaries.append(
            {
                "advance_ms": (time.perf_counter_ns() - started) / 1e6,
                "counts": {k: counters[k] - before[k] for k in counters},
                "drawables": {k: drawables[k] - before_drawables[k] for k in drawables},
            }
        )
        tick[0] += 1
        states[stimulus_slot(tick[0])] = {
            "joint": [deferred_probe._host(r.data.joint_pos) for r in env.robots],
            "cube": [
                deferred_probe._host(c.data.root_link_pose_w)
                for c in env.vr_runtime.dynamic_assets[:2]
            ],
        }
        boundaries[-1]["native_snapshot"] = {
            key: [v.tolist() for v in values]
            for key, values in states[stimulus_slot(tick[0])].items()
        }
        boundaries[-1]["camera_positions"] = {
            r: deferred_probe._host(c.data.pos_w).tolist() for r, c in capture.cameras.items()
        }

    def forward():
        if tick[0] == count and reference_slot[0] < 3:
            import torch

            reference_slot[0] += 1
            snapshot = states[reference_slot[0]]
            for index, q in enumerate(snapshot["joint"]):
                value = torch.as_tensor(q, device=env.sim.device)
                robot_methods[index * 3][2](position=value)
                robot_methods[index * 3 + 1][2](velocity=torch.zeros_like(value))
            for (_, original), pose in zip(cube_methods, snapshot["cube"], strict=True):
                original(root_pose=torch.as_tensor(pose, device=env.sim.device))
        return previous_forward()

    def reference_render(*a, **kw):
        result = previous_render(*a, **kw)
        if os.environ["CAMERA_AUDIT_TEMPORAL"] == "t2":
            import carb.settings
            import omni.replicator.core as rep

            settings = carb.settings.get_settings()
            previous = settings.get("/app/player/playSimulations")
            settings.set_bool("/app/player/playSimulations", False)
            try:
                rep.orchestrator.step(
                    delta_time=0.0, pause_timeline=False, rt_subframes=1, wait_for_render=True
                )
            finally:
                settings.set("/app/player/playSimulations", previous)
        return result

    env.sim.render = reference_render
    env._advance = advance
    env.sim.forward = forward

    def freeze():
        payload = previous_freeze()
        name = f"{len(sequence):06d}.npz"
        np.savez(images / name, **payload)
        sequence.append(
            {
                "file": name,
                "tick": tick[0],
                "reference_slot": reference_slot[0],
                "physics": env.sim.get_physics_step_count(),
                "render_generation": env.sim.render_generation,
                "counters": dict(counters),
                "drawables": dict(drawables),
            }
        )
        return payload

    capture.freeze = freeze
    error = None
    try:
        deferred_probe.qualify(env, out, count, characterize=True, priming_renders=2)
    except Exception as exc:
        error = repr(exc)
    finally:
        capture.freeze = previous_freeze
        env._advance = previous_advance
        env.sim.forward = previous_forward
        env.sim.render = previous_render
        for cube, original in cube_methods:
            cube.write_root_pose_to_sim_index = original
        for obj, name, method in robot_methods:
            setattr(obj, name, method)
        (out / "image-sequence.json").write_text(json.dumps(sequence, indent=2))
    path = out / "deferred-phase.json"
    if not path.exists():
        (out / "oracle-summary.json").write_text(json.dumps({"failure": error, "count": 0}))
        raise RuntimeError(error)
    raw = json.loads(path.read_text())
    # Historical helper has hard-coded renderer labels: never use those labels
    # as effective configuration. The separately retained Carb readbacks own it.
    raw["result"]["runtime"] = {
        "physics_hz": 120,
        "control_hz": 30,
        "settings": "../settings-after.json",
        "scope": "diagnostic native stimulus; no dataset admission",
    }
    path.write_text(json.dumps(raw, indent=2))
    # Full native scene appearance avoids the old color-centroid occlusion bias.
    # Restrict comparison to pixels that distinguish held native reference states.
    reference_files = {
        slot: [v["file"] for v in sequence if v["reference_slot"] == slot][:4] for slot in range(4)
    }
    if any(len(v) != 4 for v in reference_files.values()):
        raise RuntimeError("Incomplete native-state references")

    def image(file, role):
        with np.load(images / file) as payload:
            return payload["observation.images." + role][::2, ::2].astype(float)

    references, masks, separations = {}, {}, {}
    for role in ROLES:
        refs = np.stack([image(reference_files[slot][-1], role) for slot in range(4)])
        mask = np.ptp(refs, axis=0).max(axis=-1) > 40
        if mask.sum() < 50:
            summary = {
                "failure": "Native image references are not distinguishable",
                "count": count - 4,
                "unresolved": count - 4,
                "all_N": 0,
                "all_N_minus_1": 0,
                "any_N_minus_2_or_3": 0,
                "cross_view_disagreement": 0,
                "histograms": {r: {"unresolved": count - 4} for r in ROLES},
            }
            (out / "oracle-summary.json").write_text(json.dumps(summary, indent=2))
            raise RuntimeError(summary["failure"])
        masks[role], references[role] = mask, refs
        separations[role] = min(
            float(np.abs(a - b)[mask].mean()) for i, a in enumerate(refs) for b in refs[i + 1 :]
        )
    rows = raw["rows"]
    measured = {
        v["tick"]: v["file"] for v in sequence if v["reference_slot"] == -1 and v["tick"] > 0
    }
    for row in rows:
        n = row["availability_control_tick"]
        row["strict_offsets"], row["image_errors"] = {}, {}
        row["mechanisms"] = boundaries[n - 1]
        row["classification_margins"] = {}
        for role in ROLES:
            observed = image(measured[n], role)
            errors = {
                str(offset): float(
                    np.abs(observed - references[role][stimulus_slot(n + offset)])[
                        masks[role]
                    ].mean()
                )
                for offset in (0, -1, -2, -3)
            }
            row["image_errors"][role] = errors
            ordered = sorted(errors.values())
            row["classification_margins"][role] = ordered[1] - ordered[0]
            row["strict_offsets"][role] = (
                classify(errors, separations[role]) if n >= 4 else "unresolved"
            )
    retained_rows = rows
    rows = rows[4:]
    summary = {
        "stimulus_warmup_boundaries": 4,
        "total_retained_boundaries": len(retained_rows),
        "legacy_centroid_failure": error,
        "failure": None if min(separations.values()) >= 10 else "references_not_separated",
        "method": "native measured-state reference image MAE on reference-varying pixels; modulo four",
        "sentinel_holds_every_11": sentinel,
        "moving_wrists_and_gripper": moving,
        "count": len(rows),
        "reference_separations": separations,
        "histograms": {
            r: dict(Counter(str(row["strict_offsets"][r]) for row in rows)) for r in ROLES
        },
    }
    for name, predicate in {
        "all_N": lambda v: all(x == 0 for x in v),
        "all_N_minus_1": lambda v: all(x == -1 for x in v),
        "any_N_minus_2_or_3": lambda v: any(x in (-2, -3) for x in v),
        "unresolved": lambda v: "unresolved" in v,
        "cross_view_disagreement": lambda v: len(set(v) - {"unresolved"}) > 1,
    }.items():
        summary[name] = sum(predicate(list(row["strict_offsets"].values())) for row in rows)
    (out / "classifications.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in retained_rows)
    )
    (out / "oracle-summary.json").write_text(json.dumps(summary, indent=2))
