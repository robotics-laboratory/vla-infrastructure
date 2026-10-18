"""CPU panel stubs exercise native L3 layout changes without rendering/cameras."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from isaac_vr_native_preview import SharedCameraPreview

ROLES = ('left_wrist', 'scene', 'right_wrist')


@pytest.fixture
def native_ui(monkeypatch):
    panels, layouts, queues = [], [], []

    class Layout:
        def __init__(self, **options):
            allowed = {'mode', 'placement', 'center_offset_m', 'distance_m', 'panel_gap_m',
                       'world_position_m', 'world_orientation_xyzw'}
            assert set(options) <= allowed
            self.options = options
            layouts.append(options)

    class Provider:
        pass

    class Panel:
        def __init__(self, descriptor, width, height):
            self.role = descriptor.cfg.camera_name
            self.placement = descriptor.layout.options['placement']
            self.dimensions = (width, height)
            self.visible = False
            self.uploads, self.closes, self.invalidations = [], 0, 0
            self._container = SimpleNamespace(show=self.show, hide=self.hide)
            self._provider = Provider()
            self._component = SimpleNamespace(width=descriptor.cfg.panel_width_m,
                scene_widget=SimpleNamespace(invalidate=self.invalidate))
            panels.append(self)

        def show(self):
            self.visible = True

        def hide(self):
            self.visible = False

        def upload(self, image):
            self.uploads.append(image)

        def invalidate(self):
            self.invalidations += 1

        def close(self):
            self.closes += 1
            self.visible = False
            self._provider = None

    class Queue:
        def __init__(self, **options):
            self.options, self.pending = options, []
            self.polls, self.closed = 0, False
            queues.append(self)

        def poll(self):
            self.polls += 1

        def upload(self, image, call):
            self.pending.append(image)
            call()

        def close(self):
            self.closed = True

    def layout_feeds(cfgs, sizes, layout):
        assert len(cfgs) == len(sizes) == 3
        return cfgs

    sdk_cfg = SimpleNamespace(XrCameraFeedCfg=lambda **options: SimpleNamespace(**options),
                              XrCameraFeedLayoutCfg=Layout)
    feed = SimpleNamespace(_layout_feed_cfgs=layout_feeds,
                          _panel_descriptor=lambda cfg, layout: SimpleNamespace(cfg=cfg, layout=layout))
    scene = SimpleNamespace(Widget=SimpleNamespace(UpdatePolicy=SimpleNamespace(ON_DEMAND='on-demand')))
    presenter = SimpleNamespace(_KitSceneUiCameraFeedPresenter=lambda: SimpleNamespace(create_panel=Panel))
    for name, module in {
        'isaaclab_teleop': SimpleNamespace(), 'isaaclab_teleop.camera_feed': feed,
        'isaaclab_teleop.camera_feed_kit_scene_ui': presenter,
        'isaaclab_teleop.isaac_teleop_cfg': sdk_cfg,
        'omni.ui.scene': scene,
        'isaac_vr_native_copy_queue': SimpleNamespace(ProviderCopyQueue=Queue),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    config = dict(vr_camera_feeds=dict(
        order=['left_wrist', 'demo_scene', 'right_wrist'],
        layout=dict(mode='horizontal', placement='head_locked', center_offset_m=[0.0, 0.1],
                    distance_m=0.65, panel_width_m=0.36, panel_gap_m=0.035, max_update_hz=30.0),
        wall_layout=dict(mode='horizontal', placement='world', center_offset_m=[0.0, 0.0],
                         world_position_m=[1.50, 0.0, 1.57],
                         world_orientation_xyzw=[0.5, -0.5, -0.5, 0.5],
                         panel_width_m=0.60, panel_gap_m=0.05, max_update_hz=30.0)),
        cameras=dict(wrist=dict(width=960, height=600), scene=dict(width=320, height=200)))
    isolation = SimpleNamespace(check_panel=lambda panel: None, release_panel=lambda panel: None)
    return SimpleNamespace(config=config, panels=panels, layouts=layouts, queues=queues, isolation=isolation)


def images(preview):
    return {role: SimpleNamespace(device=SimpleNamespace(type='cuda'), dtype='torch.uint8',
             shape=(height, width, 4), is_contiguous=lambda: True,
             numel=lambda width=width, height=height: width * height * 4)
            for role, (width, height) in preview.sizes.items()}


def test_lazy_wall_layout_uses_configured_geometry_and_only_active_three_providers(native_ui):
    preview = SharedCameraPreview(native_ui.config, isolation=native_ui.isolation, transport='cuda-event')
    owners = images(preview)
    assert len(native_ui.panels) == 3 and len(native_ui.layouts) == 1
    assert preview.layout_report()['mode'] == 'head_locked'
    preview.publish(0, owners)
    assert sum(len(panel.uploads) for panel in native_ui.panels) == 3
    pending = list(preview.copy_queue.pending)
    assert preview.consume_layout_button(1.0) is True
    assert len(native_ui.panels) == 6 and len(native_ui.layouts) == 2
    assert preview.copy_queue.pending == pending  # Switching neither uploads nor discards pending owners.
    assert preview.layout_report() == dict(mode='wall', toggle_count=1,
        order=['left_wrist', 'demo_scene', 'right_wrist'], persistent_panel_count=6)
    assert all(not panel.visible for panel in native_ui.panels[:3])
    assert all(panel.visible for panel in native_ui.panels[3:])
    assert native_ui.layouts[-1]['world_position_m'] == [1.50, 0.0, 1.57]
    assert native_ui.layouts[-1]['world_orientation_xyzw'] == [0.5, -0.5, -0.5, 0.5]
    preview.publish(1, owners)
    assert all(len(panel.uploads) == 1 for panel in native_ui.panels)
    assert len(preview.copy_queue.pending) == 6
    for panel in native_ui.panels:
        role = 'scene' if panel.role == 'demo_scene' else panel.role
        assert panel.uploads[0] is owners[role]
        assert panel.dimensions == preview.sizes[role]
        assert panel._component.resolution_scale == 1.0
        assert panel._component.unit_to_pixel_scale == panel.dimensions[0] / panel._component.width
    assert len(native_ui.queues) == 1


def test_l3_rising_edges_toggle_persistent_placements_and_x_only_shows_active(native_ui):
    preview = SharedCameraPreview(native_ui.config, visible=False)
    assert preview.consume_layout_button(0.0) is False
    assert len(native_ui.panels) == 3
    assert preview.consume_layout_button(1.0) is True
    assert preview.consume_layout_button(1.0) is False
    assert preview.consume_layout_button(0.5) is False
    assert preview.layout_report()['toggle_count'] == 1
    assert not any(panel.visible for panel in native_ui.panels)
    preview.set_visible(True)
    assert [panel.visible for panel in native_ui.panels] == [False] * 3 + [True] * 3
    assert preview.consume_layout_button(1.0) is True
    assert preview.layout_report()['mode'] == 'head_locked'
    assert preview.layout_report()['toggle_count'] == 2
    assert len(native_ui.panels) == 6
    assert [panel.visible for panel in native_ui.panels] == [True] * 3 + [False] * 3
    preview.set_visible(False)
    preview.publish(0, images(preview))
    assert not any(panel.visible or panel.uploads for panel in native_ui.panels)


def test_close_releases_all_placements_once_and_keeps_pending_owners_anchored(native_ui):
    preview = SharedCameraPreview(native_ui.config, transport='cuda-event')
    owners = images(preview)
    preview.publish(0, owners)
    preview.consume_layout_button(1.0)
    preview.publish(1, owners)
    queue = preview.copy_queue
    pending = list(queue.pending)
    preview.close()
    assert preview.closed and queue.closed
    assert queue.pending == pending and len(pending) == 6
    assert all(panel.closes == 1 for panel in native_ui.panels)
    assert preview._layouts.report()['persistent_panel_count'] == 6
    assert not any(panel.visible for panel in native_ui.panels)
    preview.close()
    assert all(panel.closes == 1 for panel in native_ui.panels)


def test_close_continues_releasing_other_panels_after_one_failure(native_ui):
    preview = SharedCameraPreview(native_ui.config)
    preview.consume_layout_button(1.0)
    def fail():
        raise RuntimeError('panel close failed')
    native_ui.panels[-1].close = fail
    with pytest.raises(RuntimeError, match='panel close failed'):
        preview.close()
    assert preview.closed
    assert all(panel.closes == 1 for panel in native_ui.panels[:-1])


def test_cpu_probe_rebinds_only_its_active_providers_without_dropping_submissions(native_ui):
    preview = SharedCameraPreview(native_ui.config)
    submitted = [object()]
    probe = SimpleNamespace(providers={role: panel._provider for role, panel in preview.panels.items()},
                            submitted=submitted)
    preview.cpu_probe = probe
    old = dict(probe.providers)
    preview.consume_layout_button(1.0)
    assert probe.providers == {role: panel._provider for role, panel in preview.panels.items()}
    assert all(probe.providers[role] is not old[role] for role in probe.providers)
    assert probe.submitted is submitted


def test_cleanup_queue_failure_still_marks_preview_closed_and_preserves_layout_owners(native_ui):
    preview = SharedCameraPreview(native_ui.config, transport='cuda-event')
    preview.consume_layout_button(1.0)
    def fail():
        raise RuntimeError('queue close failed')
    preview.copy_queue.close = fail
    with pytest.raises(RuntimeError, match='queue close failed'):
        preview.close()
    assert preview.closed
    assert len(preview._all_panels()) == 6
    assert all(panel.closes == 1 for panel in native_ui.panels)


def test_native_record_l3_consumes_only_appended_control_and_preserves_motion_labels():
    import ast
    import numpy as np
    source = (Path(__file__).resolve().parents[1] / 'tools/isaac_s2_runtime.py').read_text()
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == '_consume_native_record_layout')
    received = []
    def unpack(values):
        received.append(values.copy())
        return SimpleNamespace(available=True), SimpleNamespace()
    namespace = dict(np=np, RECORD_PREVIEW_LAYOUT_BUTTON_INDEX=26,
                     PIPELINE_ACTION_DIM=22, unpack_pipeline_action=unpack)
    exec(compile(ast.Module([node], []), 'actual_native_record_layout_input', 'exec'), namespace)
    values = np.asarray(list(range(22)) + [1.0, 0.0, 1.0, 0.0, 1.0])
    original = values.copy()
    edges = []
    namespace['_consume_native_record_layout'](SimpleNamespace(consume_layout_button=edges.append), values)
    assert edges == [1.0]
    np.testing.assert_array_equal(received[0], original[:22])
    np.testing.assert_array_equal(values, original)
    # X/Y/B remain the recording lifecycle controls at 22/25/23.
    assert list(values[[22, 25, 23]]) == [1.0, 0.0, 0.0]


def test_native_record_l3_missing_controller_does_not_emit_release_and_rejects_nonfinite():
    import ast
    import numpy as np
    source = (Path(__file__).resolve().parents[1] / 'tools/isaac_s2_runtime.py').read_text()
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == '_consume_native_record_layout')
    namespace = dict(np=np, RECORD_PREVIEW_LAYOUT_BUTTON_INDEX=26, PIPELINE_ACTION_DIM=22,
                     unpack_pipeline_action=lambda values: (SimpleNamespace(available=False), None))
    exec(compile(ast.Module([node], []), 'actual_native_record_layout_input', 'exec'), namespace)
    edges = []
    runtime = SimpleNamespace(consume_layout_button=edges.append)
    values = np.zeros(27)
    namespace['_consume_native_record_layout'](runtime, values)
    assert not edges
    values[26] = np.nan
    with pytest.raises(RuntimeError, match='Non-finite recording preview'):
        namespace['_consume_native_record_layout'](runtime, values)
    assert not edges


def test_native_record_layout_is_handled_before_review_menu_early_continue():
    source = (Path(__file__).resolve().parents[1] / 'tools/isaac_s2_runtime.py').read_text()
    layout_input = source.index('_consume_native_record_layout(experiment, values)')
    lifecycle_input = source.index('event = lifecycle.buttons(')
    menu_tick = source.index('# Keep XR input/rendering alive; no IK or D0 on menu ticks.')
    assert layout_input < lifecycle_input < menu_tick
    assert 'pipeline_kwargs["native_record_preview"] = True' in source
    assert 'pipeline_action_dim = RECORD_PREVIEW_LAYOUT_BUTTON_INDEX + 1' in source


def test_actual_sdk_provider_references_survive_panel_close_until_preview_owner_release(native_ui):
    import gc
    import weakref
    preview = SharedCameraPreview(native_ui.config, transport='cuda-event')
    preview.publish(0, images(preview))
    preview.consume_layout_button(1.0)
    preview.publish(1, images(preview))
    references = [weakref.ref(panel._provider) for panel in native_ui.panels]
    preview.close()
    gc.collect()
    assert len(preview._shutdown_providers) == 6
    assert all(panel._provider is None for panel in native_ui.panels)
    assert all(reference() is not None for reference in references)
    # The bootstrap retains this owner through SimulationApp.close in production.
    del preview
    gc.collect()
    assert all(reference() is None for reference in references)


def test_head_only_preview_configuration_stays_compatible_until_layout_requested(native_ui):
    del native_ui.config['vr_camera_feeds']['wall_layout']
    preview = SharedCameraPreview(native_ui.config)
    preview.publish(0, images(preview))
    assert len(native_ui.panels) == 3
    with pytest.raises(ValueError, match='Wall preview layout is not configured'):
        preview.consume_layout_button(1.0)
    assert len(native_ui.panels) == 3 and preview.layout_report()['mode'] == 'head_locked'
    preview.close()
