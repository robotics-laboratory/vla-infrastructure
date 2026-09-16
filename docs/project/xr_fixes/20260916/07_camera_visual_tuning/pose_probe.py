"""Render user-selectable wrist-camera roll, height, and pitch variants."""

import sys
from pathlib import Path


target = Path(__file__).resolve().parents[5] / "tools/run_isaac_s1.py"
sys.path[:0] = [str(target.parent), str(target.parents[1])]
injection = r'''
import json
import math
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw
import isaac_s2_runtime
from isaaclab.utils.math import combine_frame_transforms

def _quat_multiply_xyzw(left, right):
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )

def _pitched_flipped_rotation(degrees):
    # 180-degree optical roll: camera up changes from parent +X to parent -X.
    flipped = (0.0, -2**-0.5, 0.0, 2**-0.5)
    half = math.radians(degrees) / 2.0
    # Positive local-Y pitch moves optical +X from parent +Z toward the gripper (+X).
    pitch = (0.0, math.sin(half), 0.0, math.cos(half))
    return _quat_multiply_xyzw(flipped, pitch)

def _probe(env, args, app):
    root = Path(args.report).parent
    variants = [
        {
            'name': 'A_base',
            'offset': (-0.060, 0.0, 0.000),
            'rotation': _pitched_flipped_rotation(3.0),
            'roll_deg': 180.0,
            'pitch_toward_gripper_deg': 3.0,
            'forward_along_gripper_m': 0.000,
        },
        {
            'name': 'E_forward5',
            'offset': (-0.060, 0.0, 0.005),
            'rotation': _pitched_flipped_rotation(3.0),
            'roll_deg': 180.0,
            'pitch_toward_gripper_deg': 3.0,
            'forward_along_gripper_m': 0.005,
        },
        {
            'name': 'F_forward10',
            'offset': (-0.060, 0.0, 0.010),
            'rotation': _pitched_flipped_rotation(3.0),
            'roll_deg': 180.0,
            'pitch_toward_gripper_deg': 3.0,
            'forward_along_gripper_m': 0.010,
        },
    ]
    result = []
    strips = []
    for variant in variants:
        images = []
        poses = []
        for camera, robot, wrist_id in zip(env.camera.wrists, env.robots, env.wrist_ids, strict=True):
            wrist = robot.data.body_link_pose_w.torch[:, wrist_id]
            pos, quat = combine_frame_transforms(
                wrist[:, :3], wrist[:, 3:],
                torch.tensor([variant['offset']], device=env.sim.device),
                torch.tensor([variant['rotation']], device=env.sim.device),
            )
            camera.set_world_poses(pos, quat, convention='world')
            poses.append({'position': pos[0].detach().cpu().tolist(),
                          'orientation_xyzw': quat[0].detach().cpu().tolist()})
        for _ in range(4):
            for robot in env.robots: robot.write_data_to_sim()
            env.sim.step()
            for robot in env.robots: robot.update(PHYSICS_DT)
            for camera in env.camera.wrists: camera.update(PHYSICS_DT, force_recompute=True)
        for side, camera in zip(('left', 'right'), env.camera.wrists, strict=True):
            rgba = camera.data.output['rgba'].torch[0].detach().cpu().numpy()
            Image.fromarray(rgba).save(root / f"{variant['name']}_{side}.png")
            images.append(rgba)
        row = np.concatenate(images, axis=1)
        canvas = Image.new('RGB', (row.shape[1], row.shape[0] + 32), 'black')
        canvas.paste(Image.fromarray(row[..., :3]), (0, 32))
        ImageDraw.Draw(canvas).text((8, 8), variant['name'], fill='white')
        strips.append(np.asarray(canvas))
        result.append({**variant, 'world_poses': poses})
    Image.fromarray(np.concatenate(strips, axis=0)).save(root / 'comparison.png')
    (root / 'variants.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0
isaac_s2_runtime.run_s2 = _probe
'''
source = target.read_text().replace("def main() -> int:", injection + "\ndef main() -> int:", 1)
exec(compile(source, str(target), "exec"), {"__file__": str(target), "__name__": "__main__"})
