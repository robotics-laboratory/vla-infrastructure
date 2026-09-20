"""Inspect live Kit panel geometry; make only in-memory diagnostic changes."""
import sys
from pathlib import Path

target = Path(__file__).resolve().parents[4] / "tools/run_isaac_s1.py"
sys.path[:0] = [str(target.parent), str(target.parents[1])]
injection = r'''
import isaac_s2_runtime
_original_s2 = isaac_s2_runtime.run_s2
def _layout_probe(env, args, app):
    snapshots = []
    count = 0
    original_open = env.experiment_runtime.open
    def open_probe(*a, **kw):
        result = original_open(*a, **kw)
        for feed in env.experiment_runtime._feed_session._manager._feeds:
            feed.panel._container.show()
        return result
    env.experiment_runtime.open = open_probe
    original_advance = env._advance
    def snapshot(label):
        result = {'variant': label, 'panels': []}
        for feed in env.experiment_runtime._feed_session._manager._feeds:
            component = feed.panel._component
            widget = component.scene_widget
            entry = {'camera': feed.cfg.camera_name,
                     'world_width': component.width, 'world_height': component.height,
                     'resolution_scale': component.resolution_scale,
                     'unit_to_pixel_scale': component.unit_to_pixel_scale,
                     'inferred_layout_width': component.width * component.unit_to_pixel_scale,
                     'inferred_layout_height': component.height * component.unit_to_pixel_scale,
                     'scene_widget_built': widget is not None}
            if widget is not None:
                entry['texture_width'] = widget.resolution_width
                entry['texture_height'] = widget.resolution_height
                frame = widget.frame
                entry['frame_computed_width'] = frame.computed_width
                entry['frame_computed_height'] = frame.computed_height
            result['panels'].append(entry)
        snapshots.append(result)
        print('PANEL_LAYOUT', json.dumps(result), flush=True)
    def advance(repeat):
        nonlocal count
        original_advance(repeat)
        if repeat != 4:
            return
        count += 1
        if count == 6:
            snapshot('existing')
            for feed in env.experiment_runtime._feed_session._manager._feeds:
                component = feed.panel._component
                component.resolution_scale = 1.0
                component.unit_to_pixel_scale = 640.0 / component.width
        if count == 12:
            snapshot('pixel_layout_in_memory')
    env._advance = advance
    try:
        return _original_s2(env, args, app)
    finally:
        Path('/tmp/piper_xr_panel_layout_result.json').write_text(json.dumps(snapshots, indent=2))
isaac_s2_runtime.run_s2 = _layout_probe
'''
source = target.read_text().replace('def main() -> int:', injection + '\ndef main() -> int:', 1)
exec(compile(source, str(target), 'exec'), {'__file__': str(target), '__name__': '__main__'})
