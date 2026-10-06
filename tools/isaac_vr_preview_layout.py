"""Two persistent upstream panel placements sharing the existing RGB feeds."""

from copy import deepcopy
from typing import Any


class PreviewLayoutPanels:
    def __init__(self, manager: Any, presenter: Any, wall_layout: dict, isolation=None):
        from isaaclab_teleop.camera_feed import _layout_feed_cfgs, _panel_descriptor
        from isaaclab_teleop.isaac_teleop_cfg import XrCameraFeedLayoutCfg

        self.manager = manager
        self.isolation = isolation
        self.mode = "head_locked"
        self.toggle_count = 0
        self.pressed = False
        self.panels = {"head_locked": [feed.panel for feed in manager._feeds], "wall": []}
        layout = XrCameraFeedLayoutCfg(**{
            key: value for key, value in wall_layout.items() if key != "panel_width_m"
        })
        cfgs = [deepcopy(feed.cfg) for feed in manager._feeds]
        for cfg in cfgs:
            cfg.panel_width_m = float(wall_layout["panel_width_m"])
        sizes = [(int(feed.image.shape[1]), int(feed.image.shape[0])) for feed in manager._feeds]
        try:
            for cfg, (width, height) in zip(_layout_feed_cfgs(cfgs, sizes, layout), sizes, strict=True):
                panel = presenter.create_panel(_panel_descriptor(cfg, layout), width, height)
                self.panels["wall"].append(panel)
                self._hide(panel)
        except Exception:
            self.close_inactive()
            raise

    def _hide(self, panel):
        panel._container.hide()
        if self.isolation is not None:
            self.isolation.release_panel(panel)

    def consume_button(self, value: float) -> bool:
        pressed = bool(value > 0.5)
        changed = pressed and not self.pressed
        self.pressed = pressed
        if not changed:
            return False
        for feed in self.manager._feeds:
            self._hide(feed.panel)
        self.mode = "wall" if self.mode == "head_locked" else "head_locked"
        for feed, panel in zip(self.manager._feeds, self.panels[self.mode], strict=True):
            feed.panel = panel
        self.toggle_count += 1
        return True

    def close_inactive(self):
        # Normal feed-session teardown owns the active panels.
        inactive = "wall" if self.mode == "head_locked" else "head_locked"
        for panel in self.panels[inactive]:
            panel.close()
        self.panels[inactive].clear()

    def report(self):
        return {"mode": self.mode, "toggle_count": self.toggle_count,
                "order": [feed.cfg.camera_name for feed in self.manager._feeds],
                "persistent_panel_count": sum(map(len, self.panels.values()))}
