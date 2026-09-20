"""Selected VR composition and explicit, opt-in external asset qualification."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING or __package__:
    from .isaac_demo_launch import git
else:
    from isaac_demo_launch import git

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/isaac61_vr_runtime.yaml"
ASSET_LAB_CONFIG = ROOT / "configs/experiments/robosyn_asset_lab.yaml"


def load_composition(profile: str) -> dict:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    if profile in config["profiles"]["available"]:
        return config
    if profile != "robosyn_asset_lab":
        raise ValueError(f"Unknown VR profile: {profile}")
    overlay = yaml.safe_load(ASSET_LAB_CONFIG.read_text())
    if overlay["status"] != "EXPERIMENTAL_TEST_ONLY_NOT_A_GATE":
        raise RuntimeError("asset lab must remain experimental")
    manifest_path = ROOT / overlay["asset_manifest"]
    manifest = yaml.safe_load(manifest_path.read_text())
    checkout = Path(manifest["source_checkout"])
    if git(checkout, "rev-parse", "HEAD") != manifest["source_commit"] or git(
        checkout, "status", "--porcelain", "--untracked-files=all"
    ):
        raise RuntimeError(f"RoboSyn test checkout is not clean/pinned: {checkout}")
    for item in manifest["assets"]:
        path = checkout / item["source_path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError(f"RoboSyn test asset hash mismatch: {path}")
    config["asset_lab"] = {**overlay, "source_checkout": str(checkout)}
    return config
