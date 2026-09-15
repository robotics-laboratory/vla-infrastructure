"""Matched no-client preview ablation; preserve renderer and physics cadence."""
import sys
from pathlib import Path

target = Path(__file__).resolve().parents[5] / 'tools/run_isaac_s1.py'
sys.path[:0] = [str(target.parent), str(target.parents[1])]
injection = r'''
from collections import defaultdict
import isaac_s2_runtime
from isaaclab_teleop.camera_feed import _XrCameraFeedManager
from omni.ui.scene import Widget
_original_s2 = isaac_s2_runtime.run_s2

def _profile_s2(env, args, app):
    runtime = env.experiment_runtime
    phases = ['baseline_hidden', 'optimized_hidden', 'baseline_visible', 'optimized_visible']
    phase_index = 0
    phase_step = 0
    control_count = 0
    stats = defaultdict(lambda: [0, 0.0])
    advance_times = []
    results = []
    provider_samples = {'sequence_ms': [], 'raw_cpu_ms': []}
    def timed_call(label, fn, *a, **kw):
        start = time.perf_counter()
        try:
            return fn(*a, **kw)
        finally:
            if phase_step > 4:
                stats[label][0] += 1
                stats[label][1] += time.perf_counter() - start
    original_render = env.sim.render
    env.sim.render = lambda *a, **kw: timed_call('render', original_render, *a, **kw)
    original_open = runtime.open
    def open_profile(*a, **kw):
        result = original_open(*a, **kw)
        manager = runtime._feed_session._manager
        optimized_update = manager.update
        manager.update = lambda: timed_call('feed_update',
            (lambda: _XrCameraFeedManager.update(manager)) if phase_index % 2 == 0 else optimized_update)
        original_publish = manager._publish_feed
        manager._publish_feed = lambda feed: timed_call('feed_publish', original_publish, feed)
        for feed in manager._feeds:
            optimized_upload = feed.panel.upload
            baseline_upload = feed.panel._upstream.upload
            # Alternating samples isolate sequence conversion from GPU rendering.
            for _ in range(20):
                start = time.perf_counter()
                baseline_upload(feed.upload_image)
                provider_samples['sequence_ms'].append(1000 * (time.perf_counter() - start))
                start = time.perf_counter()
                optimized_upload(feed.upload_image)
                provider_samples['raw_cpu_ms'].append(1000 * (time.perf_counter() - start))
            def upload(image, optimized=optimized_upload, baseline=baseline_upload):
                return timed_call('panel_upload', baseline if phase_index % 2 == 0 else optimized, image)
            feed.panel.upload = upload
            original_source = feed.image_source.get_image
            def get_image(*a, original=original_source, **kw):
                return timed_call('source_get_image', original, *a, **kw)
            feed.image_source.get_image = get_image
        return result
    runtime.open = open_profile
    original_advance = env._advance
    def advance(repeat):
        nonlocal phase_index, phase_step, control_count
        if repeat != 4:
            return original_advance(repeat)
        control_count += 1
        phase_index = min((control_count - 1) // 20, 3)
        phase_step = (control_count - 1) % 20 + 1
        if phase_step == 1:
            stats.clear()
            advance_times.clear()
            runtime._set_display(phase_index >= 2)
            for feed in runtime._feed_session._manager._feeds:
                widget = feed.panel._component.scene_widget
                if widget is not None:
                    widget.update_policy = (Widget.UpdatePolicy.ALWAYS if phase_index % 2 == 0
                                            else Widget.UpdatePolicy.ON_DEMAND)
                    widget.invalidate()
        start = time.perf_counter()
        original_advance(repeat)
        if phase_step > 4:
            advance_times.append(time.perf_counter() - start)
        if phase_step == 20:
            entry = dict(phase=phases[phase_index], measured_control_steps=len(advance_times),
                advance_ms=float(np.mean(advance_times)) * 1000,
                advance_median_ms=float(np.median(advance_times)) * 1000,
                timings={k:dict(calls=v[0], seconds=v[1], ms_per_call=1000*v[1]/v[0])
                         for k,v in stats.items() if v[0]})
            results.append(entry)
            print('PREVIEW_PHASE', json.dumps(entry), flush=True)
    env._advance = advance
    try:
        return _original_s2(env, args, app)
    finally:
        result = dict(
            physical_client=False,
            scope='same process; 120 Hz physics and 4 renders per control step unchanged',
            provider={k:dict(samples=len(v), mean_ms=float(np.mean(v)), median_ms=float(np.median(v)))
                      for k,v in provider_samples.items()},
            phases=results,
        )
        Path(args.report).with_name('timings.json').write_text(json.dumps(result, indent=2) + '\n')
isaac_s2_runtime.run_s2 = _profile_s2
'''
source = target.read_text().replace('def main() -> int:', injection + '\ndef main() -> int:', 1)
exec(compile(source, str(target), 'exec'), {'__file__': str(target), '__name__': '__main__'})
