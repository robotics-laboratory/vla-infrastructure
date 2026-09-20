"""Bounded diagnostic in the pinned environment; no teleop or dataset writes."""
import sys
from pathlib import Path

target = Path(__file__).resolve().parents[4] / "tools/run_isaac_s1.py"
sys.path.insert(0, str(target.parent))
sys.path.insert(0, str(target.parents[1]))
injection = r'''
def _performance_probe(env, args, app):
    import time
    from collections import defaultdict
    from isaac_s2_runtime import _camera_sample
    stats = defaultdict(lambda: [0, 0.0])
    def timed(obj, name, label):
        original = getattr(obj, name)
        def call(*a, **kw):
            start = time.perf_counter()
            try:
                return original(*a, **kw)
            finally:
                stats[label][0] += 1
                stats[label][1] += time.perf_counter() - start
        setattr(obj, name, call)
    timed(env.sim, 'render', 'render')
    timed(env.sim, 'step', 'physics_and_render')
    timed(env.camera, 'update', 'camera_update')
    timed(env, 'observation', 'observation_cpu')
    for i, robot in enumerate(env.robots):
        timed(robot, 'write_data_to_sim', f'robot_{i}_write')
        timed(robot, 'update', f'robot_{i}_update')
    cameras = (*env.camera.wrists, env.camera.scene_camera)
    products = [c._render_data.render_product for c in cameras]
    print('PROBE_PRODUCTS', [(type(p).__name__, hasattr(p, 'hydra_texture'), hasattr(p, 'set_updates_enabled')) for p in products], flush=True)
    results = []
    def advance(mode):
        if mode == 'current':
            env._advance(4)
            _camera_sample(env, None)
            return
        for tick in range(4):
            for robot in env.robots:
                robot.write_data_to_sim()
            env.sim.step(render=(mode == 'no_camera_products' or tick == 3))
            for robot in env.robots:
                robot.update(PHYSICS_DT)
            if mode != 'no_camera_products':
                env.camera.update(PHYSICS_DT, force_recompute=True)
            env.physics_probe.update(PHYSICS_DT)
            env.experiment_runtime.update(PHYSICS_DT)
        if mode != 'no_camera_products':
            _camera_sample(env, None)
    for mode in ('current', 'render_once', 'current', 'no_camera_products'):
        if mode == 'no_camera_products':
            for p in products:
                texture = getattr(p, 'hydra_texture', p)
                texture.set_updates_enabled(False)
        for _ in range(5):
            advance(mode)
        torch.cuda.synchronize()
        stats.clear()
        start = time.perf_counter()
        for _ in range(40):
            advance(mode)
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - start
        result = dict(mode=mode, control_hz=40 / elapsed, physics_hz=160 / elapsed,
                      wall_seconds=elapsed, timings={k: dict(calls=v[0], seconds=v[1], ms_per_call=1000*v[1]/v[0]) for k,v in stats.items()})
        results.append(result)
        print('PROBE_RESULT', json.dumps(result), flush=True)
    Path('/tmp/piper_camera_probe_results.json').write_text(json.dumps(results, indent=2))
    return 0

import isaac_s2_runtime
isaac_s2_runtime.run_s2 = _performance_probe

'''
source = target.read_text()
source = source.replace('def main() -> int:', injection + '\ndef main() -> int:', 1)
scope = {'__file__': str(target), '__name__': '__main__'}
exec(compile(source, str(target), 'exec'), scope)
