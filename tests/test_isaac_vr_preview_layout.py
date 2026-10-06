from types import SimpleNamespace as NS

from tools.isaac_vr_preview_layout import PreviewLayoutPanels


class Panel:
    def __init__(self):
        self.hidden = 0
        self.closed = 0
        self._container = NS(hide=self.hide)

    def hide(self):
        self.hidden += 1

    def close(self):
        self.closed += 1


def test_layout_switches_reuse_panels_sources_and_camera_identity_across_reset():
    layouts = PreviewLayoutPanels.__new__(PreviewLayoutPanels)
    layouts.isolation = None
    layouts.mode = "head_locked"
    layouts.toggle_count = 0
    layouts.pressed = False
    layouts.panels = {mode: [Panel() for _ in range(3)] for mode in ("head_locked", "wall")}
    feeds = [NS(panel=panel, cfg=NS(camera_name=name), camera=object(), image_source=object())
             for name, panel in zip(("left_wrist", "demo_scene", "right_wrist"),
                                    layouts.panels["head_locked"], strict=True)]
    layouts.manager = NS(_feeds=feeds)
    identities = [(f.camera, f.image_source) for f in feeds]
    for _ in range(40):
        assert layouts.consume_button(1.0)
        assert not layouts.consume_button(1.0)  # Held L3 cannot toggle after reset/reconnect.
        assert [f.panel for f in feeds] == layouts.panels[layouts.mode]
        assert [(f.camera, f.image_source) for f in feeds] == identities
        assert not layouts.consume_button(0.0)
    assert layouts.report() == {"mode": "head_locked", "toggle_count": 40,
                                "order": ["left_wrist", "demo_scene", "right_wrist"],
                                "persistent_panel_count": 6}
    layouts.close_inactive()
    assert all(p.closed == 0 for p in layouts.panels["head_locked"])
    assert layouts.panels["wall"] == []
