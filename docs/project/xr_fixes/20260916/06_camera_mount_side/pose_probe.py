"""Render mirrored gripper-X camera positions with the accepted optical rotation."""

import sys
from pathlib import Path


target = Path(__file__).resolve().parents[5] / "tools/run_isaac_s1.py"
sys.path[:0] = [str(target.parent), str(target.parents[1])]
injection = r'''
import json
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw
import isaac_s2_runtime
from isaaclab.utils.math import combine_frame_transforms

def _probe(env, args, app):
    root = Path(args.report).parent
    rotation = (2**-0.5, 0.0, 2**-0.5, 0.0)
    variants = [
        ('above_xn05_z00', (-0.05, 0.0, 0.00), rotation),
        ('above_xn05_zp01', (-0.05, 0.0, 0.01), rotation),
        ('above_xn055_z00', (-0.055, 0.0, 0.00), rotation),
        ('above_xn055_zp01', (-0.055, 0.0, 0.01), rotation),
    ]
    result = []
    strips = []
    for name, offset, rotation in variants:
        images = []
        poses = []
        parent_x_world = []
        for camera, robot, wrist_id in zip(env.camera.wrists, env.robots, env.wrist_ids, strict=True):
            wrist = robot.data.body_link_pose_w.torch[:, wrist_id]
            origin, _ = combine_frame_transforms(
                wrist[:, :3], wrist[:, 3:],
                torch.zeros((1, 3), device=env.sim.device),
                torch.tensor([[0.0, 0.0, 0.0, 1.0]], device=env.sim.device),
            )
            axis_point, _ = combine_frame_transforms(
                wrist[:, :3], wrist[:, 3:],
                torch.tensor([[1.0, 0.0, 0.0]], device=env.sim.device),
                torch.tensor([[0.0, 0.0, 0.0, 1.0]], device=env.sim.device),
            )
            pos, quat = combine_frame_transforms(
                wrist[:, :3], wrist[:, 3:],
                torch.tensor([offset], device=env.sim.device),
                torch.tensor([rotation], device=env.sim.device),
            )
            camera.set_world_poses(pos, quat, convention='world')
            poses.append({'position': pos[0].detach().cpu().tolist(),
                          'orientation_xyzw': quat[0].detach().cpu().tolist()})
            parent_x_world.append((axis_point - origin)[0].detach().cpu().tolist())
        for _ in range(4):
            for robot in env.robots: robot.write_data_to_sim()
            env.sim.step()
            for robot in env.robots: robot.update(PHYSICS_DT)
            for camera in env.camera.wrists: camera.update(PHYSICS_DT, force_recompute=True)
        for side, camera in zip(('left','right'), env.camera.wrists, strict=True):
            rgba = camera.data.output['rgba'].torch[0].detach().cpu().numpy()
            Image.fromarray(rgba).save(root / f'{name}_{side}.png')
            images.append(rgba)
        row = np.concatenate(images, axis=1)
        canvas = Image.new('RGB', (row.shape[1], row.shape[0] + 32), 'black')
        canvas.paste(Image.fromarray(row[..., :3]), (0, 32))
        ImageDraw.Draw(canvas).text((8, 8), name, fill='white')
        strips.append(np.asarray(canvas))
        result.append({'variant': name, 'offset_parent_m': offset,
                       'rotation_world_convention_xyzw': rotation,
                       'gripper_parent_plus_x_world': parent_x_world,
                       'world_poses': poses})
    Image.fromarray(np.concatenate(strips, axis=0)).save(root / 'comparison.png')
    (root / 'poses.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0
isaac_s2_runtime.run_s2 = _probe
'''
source = target.read_text().replace("def main() -> int:", injection + "\ndef main() -> int:", 1)
exec(compile(source, str(target), "exec"), {"__file__": str(target), "__name__": "__main__"})
