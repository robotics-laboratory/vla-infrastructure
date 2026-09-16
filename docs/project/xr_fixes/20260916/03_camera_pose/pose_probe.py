"""Render the current and two local +Z optical-axis candidates at demo home."""
import sys
from pathlib import Path

target = Path(__file__).resolve().parents[5] / 'tools/run_isaac_s1.py'
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
    variants = [
        ('above_x04_z00', (0.04, 0.0, 0.00), (2**-0.5, 0.0, 2**-0.5, 0.0)),
        ('above_x06_z00', (0.06, 0.0, 0.00), (2**-0.5, 0.0, 2**-0.5, 0.0)),
        ('above_x05_z03', (0.05, 0.0, 0.03), (2**-0.5, 0.0, 2**-0.5, 0.0)),
    ]
    result = []
    strips = []
    for name, offset, rotation in variants:
        images = []
        poses = []
        for camera, robot, wrist_id in zip(env.camera.wrists, env.robots, env.wrist_ids, strict=True):
            wrist = robot.data.body_link_pose_w.torch[:, wrist_id]
            pos, quat = combine_frame_transforms(
                wrist[:, :3], wrist[:, 3:],
                torch.tensor([offset], device=env.sim.device),
                torch.tensor([rotation], device=env.sim.device),
            )
            camera.set_world_poses(pos, quat, convention='world')
            poses.append({'position': pos[0].detach().cpu().tolist(),
                          'orientation_xyzw': quat[0].detach().cpu().tolist()})
        for _ in range(4):
            for robot in env.robots: robot.write_data_to_sim()
            env.sim.step()
            for robot in env.robots: robot.update(PHYSICS_DT)
            for camera in env.camera.wrists: camera.update(PHYSICS_DT, force_recompute=True)
        for side, camera in zip(('left','right'), env.camera.wrists, strict=True):
            rgba = camera.data.output['rgba'].torch[0].detach().cpu().numpy()
            path = root / f'{name}_{side}.png'
            Image.fromarray(rgba).save(path)
            images.append(rgba)
        row = np.concatenate(images, axis=1)
        canvas = Image.new('RGB', (row.shape[1], row.shape[0] + 32), 'black')
        canvas.paste(Image.fromarray(row[..., :3]), (0,32))
        ImageDraw.Draw(canvas).text((8,8), name, fill='white')
        strips.append(np.asarray(canvas))
        result.append({'variant':name, 'offset_parent_m':offset,
                       'rotation_world_convention_xyzw':rotation, 'world_poses':poses})
    Image.fromarray(np.concatenate(strips, axis=0)).save(root / 'comparison.png')
    (root/'poses.json').write_text(json.dumps(result, indent=2)+'\n')
    return 0
isaac_s2_runtime.run_s2 = _probe
'''
source = target.read_text().replace('def main() -> int:', injection + '\ndef main() -> int:', 1)
exec(compile(source, str(target), 'exec'), {'__file__': str(target), '__name__': '__main__'})
