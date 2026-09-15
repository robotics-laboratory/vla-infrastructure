"""Profile the unchanged XR loop, using no-client bounded execution."""
import sys
from pathlib import Path

target = Path('/home/ebulochkin/vla_infrastructure/.worktrees/robosyn-vr-demo/tools/run_isaac_s1.py')
sys.path[:0] = [str(target.parent), str(target.parents[1])]
injection = r'''
import time, os
from collections import defaultdict
import isaac_s2_runtime
_original_s2 = isaac_s2_runtime.run_s2
def _profile_s2(env, args, app):
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
    timed(isaac_s2_runtime, '_camera_sample', 'camera_validation')
    presenter = env.experiment_runtime._feed_session._presenter
    if presenter is not None:
        timed(presenter, 'stage_upload_image', 'panel_gpu_to_cpu')
    original_open = env.experiment_runtime.open
    def open_profile(*a, **kw):
        result = original_open(*a, **kw)
        manager = env.experiment_runtime._feed_session._manager
        if manager is not None:
            timed(manager, 'update', 'feed_manager_update')
            timed(manager, '_publish_feed', 'feed_publish')
            for i, feed in enumerate(manager._feeds):
                if os.environ.get('PIPER_PROBE_MODE', '').startswith('raw_cpu_upload'):
                    import ctypes
                    import omni.gpu_foundation_factory as gf
                    capsule_new = ctypes.PYFUNCTYPE(ctypes.py_object, ctypes.c_void_p,
                        ctypes.c_char_p, ctypes.c_void_p)(
                        ctypes.cast(ctypes.pythonapi.PyCapsule_New, ctypes.c_void_p).value)
                    def upload(image, panel=feed.panel):
                        if panel._closed:
                            return
                        array = image.numpy()
                        panel._probe_retained_image = image
                        capsule = capsule_new(array.ctypes.data, None, None)
                        panel._provider.set_raw_bytes_data(capsule,
                            [int(image.shape[1]), int(image.shape[0])], gf.TextureFormat.RGBA8_UNORM)
                    feed.panel.upload = upload
                timed(feed.panel, 'upload', f'panel_{i}_upload')
        return result
    env.experiment_runtime.open = open_profile
    mode = os.environ.get('PIPER_PROBE_MODE', 'current')
    original_advance = env._advance
    control_count = 0
    advance_times = []
    def advance(repeat):
        nonlocal control_count
        if repeat == 4:
            control_count += 1
            if control_count == 6:
                stats.clear()
        start = time.perf_counter()
        if mode.endswith('render_once') and repeat == 4:
            for tick in range(repeat):
                for robot in env.robots:
                    robot.write_data_to_sim()
                env.sim.step(render=tick == repeat - 1)
                for robot in env.robots:
                    robot.update(PHYSICS_DT)
                env.camera.update(PHYSICS_DT, force_recompute=True)
                env.physics_probe.update(PHYSICS_DT)
                env.experiment_runtime.update(PHYSICS_DT)
        else:
            original_advance(repeat)
        if repeat == 4 and control_count > 5:
            advance_times.append(time.perf_counter() - start)
    env._advance = advance
    try:
        return _original_s2(env, args, app)
    finally:
        result = dict(mode=mode, measured_advance_calls=len(advance_times),
                      advance_ms=float(np.mean(advance_times))*1000,
                      timings={k: dict(calls=v[0], seconds=v[1], ms_per_call=1000*v[1]/v[0]) for k,v in stats.items()})
        path = Path('/tmp/piper_camera_xr_' + mode + '_timings.json')
        path.write_text(json.dumps(result, indent=2))
        print('XR_PROBE_RESULT', json.dumps(result), flush=True)
isaac_s2_runtime.run_s2 = _profile_s2
'''
source = target.read_text().replace('def main() -> int:', injection + '\ndef main() -> int:', 1)
exec(compile(source, str(target), 'exec'), {'__file__': str(target), '__name__': '__main__'})
