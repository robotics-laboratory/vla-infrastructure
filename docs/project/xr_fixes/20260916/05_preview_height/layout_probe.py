"""Resolve the configured preview layout with the pinned upstream helpers."""

import json
from pathlib import Path

import yaml
from isaaclab_teleop.camera_feed import _layout_feed_cfgs, _panel_size_m
from isaaclab_teleop.isaac_teleop_cfg import XrCameraFeedCfg, XrCameraFeedLayoutCfg


root = Path(__file__).resolve().parents[5]
config = yaml.safe_load(
    (root / "configs/experiments/robosyn_vr_demo.yaml").read_text(encoding="utf-8")
)
layout = config["vr_camera_feeds"]["layout"]
feeds = [
    XrCameraFeedCfg(
        camera_name=side,
        panel_width_m=float(layout["panel_width_m"]),
        max_update_hz=float(layout["max_update_hz"]),
        label=label,
    )
    for side, label in (("left_wrist", "LEFT WRIST"), ("right_wrist", "RIGHT WRIST"))
]
layout_cfg = XrCameraFeedLayoutCfg(
    mode=layout["mode"],
    placement=layout["placement"],
    center_offset_m=tuple(layout["center_offset_m"]),
    distance_m=float(layout["distance_m"]),
    panel_gap_m=float(layout["panel_gap_m"]),
)
image_sizes = [(640, 480), (640, 480)]
resolved = _layout_feed_cfgs(feeds, image_sizes, layout_cfg)
panel_sizes = [_panel_size_m(feed, size) for feed, size in zip(resolved, image_sizes)]
result = {
    "placement": layout_cfg.placement,
    "center_offset_m": layout_cfg.center_offset_m,
    "resolved": [
        {
            "camera": feed.camera_name,
            "offset_m": feed.offset_m,
            "distance_m": feed.distance_m,
            "panel_size_m": panel_size,
            "lower_edge_y_m": feed.offset_m[1] - panel_size[1] / 2.0,
        }
        for feed, panel_size in zip(resolved, panel_sizes)
    ],
}
output = Path(__file__).with_name("layout_probe.json")
output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
