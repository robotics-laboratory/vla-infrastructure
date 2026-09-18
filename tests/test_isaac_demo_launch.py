"""Launch isolation regressions: another user's XR state must never leak in."""
import os
from pathlib import Path

import pytest

from tools.isaac_demo_launch import (
    STACKS, configure_cloudxr, private_directory, user_environment, write_runtime_config,
)


def test_per_user_environment_discards_foreign_runtime_and_caches(tmp_path, monkeypatch):
    for key in ('XR_RUNTIME_JSON', 'NV_CXR_RUNTIME_DIR', 'XDG_CACHE_HOME',
                'XDG_CONFIG_HOME', 'XDG_RUNTIME_DIR', 'ROBOSYN_VR_CAMERA_DIAGNOSTICS_DIR'):
        monkeypatch.setenv(key, '/home/someone-else/private')
    environment, state = user_environment(STACKS['isaac61'], 'isaac61', state_root=tmp_path)
    assert 'XR_RUNTIME_JSON' not in environment
    assert 'NV_CXR_RUNTIME_DIR' not in environment
    assert 'ROBOSYN_VR_CAMERA_DIAGNOSTICS_DIR' not in environment
    for key in ('XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_RUNTIME_DIR', 'WARP_CACHE_PATH'):
        assert Path(environment[key]).is_relative_to(state)
        assert Path(environment[key]).stat().st_uid == os.getuid()
        assert Path(environment[key]).stat().st_mode & 0o777 == 0o700


def test_reject_inherited_home(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path / 'someone-else'))
    with pytest.raises(RuntimeError, match='Linux account home'):
        user_environment(STACKS['isaac61'], 'isaac61', state_root=tmp_path)


def test_reject_state_symlink(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(target)
    with pytest.raises(RuntimeError, match='symlink'):
        private_directory(alias)


def test_existing_runtime_never_falls_back_to_foreign_user(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    environment = {}
    with pytest.raises(RuntimeError, match='Existing CloudXR IPC'):
        configure_cloudxr(environment, mode='existing', dry_run=True)
    assert 'XR_RUNTIME_JSON' not in environment


def test_asset_conversion_is_per_user(tmp_path):
    root = Path(__file__).resolve().parents[1]
    before = (root / 'configs/isaac61_s1_runtime.yaml').read_bytes()
    import yaml
    path = write_runtime_config(root, STACKS['isaac61'], tmp_path, tmp_path)
    config = yaml.safe_load(path.read_text())
    assert Path(config['asset']['composed_urdf']).is_relative_to(tmp_path)
    assert (root / 'configs/isaac61_s1_runtime.yaml').read_bytes() == before
