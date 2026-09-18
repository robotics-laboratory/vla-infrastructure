"""Pinned demo releases and per-Linux-user launch state (no SDK mutation)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import subprocess

import yaml

STORAGE = Path('/data/vla-infrastructure')
TARGET = STORAGE / 'isaac61_production'
STACKS = {
    'isaac61': {
        'lab': TARGET / 'IsaacLab', 'environment': TARGET / 'env',
        'commit': '0c2e2c64e51922d088b695d72ffe03faa5c6b95d',
        'pyproject': '2780d507882950e64ca8f972fcad4c19e74b9681af1d830e0b34fa09e79e116b',
        'lock': 'f633120f145944672d9ba3d6a7bda9a145a01b6295e9fc08f0997e60dc6a40e7',
        'packages': {'isaacsim': '6.1.0.0', 'isaaclab': '17.0.2',
                     'isaaclab-rl': '0.16.3', 'isaaclab-teleop': '0.9.0', 'isaacteleop': '1.4.98rc1'},
        's1': 'isaac61_s1_runtime.yaml', 's2': 'isaac61_s2_runtime.yaml',
    },
    'legacy': {
        'lab': STORAGE / 'isaaclab_candidate_qualification/20260907/candidate_b_exact',
        'environment': STORAGE / 'envs/isaac-s1-candidate-b',
        'commit': '913ac53f51b2f8d02c9e121caa4cbdd06262948e',
        'pyproject': 'b691862409ab8ad58b074ac32ce7f071e3895ec10975444b9e62995741ace159',
        'lock': '80eb2c4e1155dd9e9736506d41cdbe327df74ee2b005bdecc0fb7c87c8b8bb84',
        'packages': {'isaacsim': '6.0.1.0', 'isaaclab': '16.4.0',
                     'isaaclab-teleop': '0.8.0', 'isaacteleop': '1.4.98rc1'},
        's1': 'isaac_s1_runtime.yaml', 's2': 'isaac_s2_runtime.yaml',
    },
}

GROUND_ROOT = STORAGE / 'assets/isaac61-demo-ground'
GROUND_HASHES = {
    'default_ground_plane.usda': '8d86d2473acd68f6e4f3763c52347eee283b521303c56d29b8bd733c72811636',
    'Materials/Textures/default_ground_plane_albedo.png': '2c41b1f063769715b3d74738abd3efa4078eabb95f6ada8e5d2b3bba29411b14',
    'Materials/Textures/default_ground_plane_roughness.png': 'a55248660ef2d82b15b9cf731d42b2580c160314be5ae4c13e27c773c2debf8c',
}


def git(checkout: Path, *arguments: str) -> str:
    # Trust this explicit shared checkout only, never a global safe.directory '*'.
    return subprocess.check_output(
        ['git', '-c', f'safe.directory={checkout}', '-C', str(checkout), *arguments],
        text=True).strip()


def verify_stack(name: str) -> dict:
    stack = STACKS[name]
    if name == 'isaac61':
        for relative, expected in GROUND_HASHES.items():
            if hashlib.sha256((GROUND_ROOT / relative).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f'Pinned NVIDIA ground asset changed: {relative}')
    for checkout, commit in (
        (stack['lab'], stack['commit']),
        (STORAGE / 'assets/agx_arm_urdf', 'f6642ce0d7872c686f29c99e9e10cd23d1d49313'),
    ):
        if git(checkout, 'rev-parse', 'HEAD') != commit or git(checkout, 'status', '--porcelain'):
            raise RuntimeError(f'Expected clean pinned checkout {commit}: {checkout}')
    for filename, key in (('pyproject.toml', 'pyproject'), ('uv.lock', 'lock')):
        if hashlib.sha256((stack['lab'] / filename).read_bytes()).hexdigest() != stack[key]:
            raise RuntimeError(f'Frozen upstream workspace mismatch: {filename}')
    probe = subprocess.check_output([
        str(stack['environment'] / 'bin/python'), '-c',
        'import importlib.metadata as m,json,sys; '
        'print(json.dumps({p:m.version(p) for p in sys.argv[1:]}))',
        *stack['packages'],
    ], text=True)
    if json.loads(probe) != stack['packages']:
        raise RuntimeError(f'Installed packages do not match {name}: {probe}')
    return stack


def private_directory(path: Path) -> Path:
    if path.is_symlink():
        raise RuntimeError(f'Per-user state cannot be a symlink: {path}')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid():
        raise RuntimeError(f'Per-user state belongs to another UID: {path}')
    path.chmod(0o700)
    return path


def user_environment(stack: dict, name: str, *, state_root: Path | None = None) -> tuple[dict, Path]:
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if Path.home().resolve() != home.resolve():
        raise RuntimeError('HOME differs from the Linux account home; use a proper login shell')
    proposed = state_root or Path('/data') / pwd.getpwuid(os.getuid()).pw_name / 'vla-runtime' / f'isaac-{name}'
    if not proposed.is_absolute():
        raise RuntimeError('State root must be absolute')
    if proposed.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise RuntimeError('Runtime state must be outside the repository')
    state = private_directory(proposed)
    environment = os.environ.copy()
    for key in ('PYTHONHOME', 'VIRTUAL_ENV', 'EXP_PATH', 'ISAACSIM_PATH', 'XR_RUNTIME_JSON', 'NV_CXR_RUNTIME_DIR',
                'NV_CXR_OUTPUT_DIR', 'CXR_INSTALL_DIR', 'CXR_HOST_VOLUME_PATH',
                'ISAACLAB_CXR_SKIP_AUTOLAUNCH', 'ROBOSYN_VR_GROUND_USD', 'ROBOSYN_VR_CAMERA_DIAGNOSTICS_DIR'):
        environment.pop(key, None)
    environment.pop('UV_PYTHON_PREFERENCE', None)
    environment.update({
        'PYTHONPATH': str(stack['lab'] / 'source/isaaclab'),
        'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
        'ROBOSYN_VR_ASSET_CACHE': str(state / 'assets/demo'),
    })
    for key, relative in (
        ('XDG_CACHE_HOME', 'cache'), ('XDG_CONFIG_HOME', 'config'),
        ('XDG_DATA_HOME', 'data'), ('CUDA_CACHE_PATH', 'cuda'),
        ('WARP_CACHE_PATH', 'warp'), ('TMPDIR', 'tmp'), ('XDG_RUNTIME_DIR', 'run'),
    ):
        environment[key] = str(private_directory(state / relative))
    if name == 'isaac61':
        environment['ROBOSYN_VR_GROUND_USD'] = str(GROUND_ROOT / 'default_ground_plane.usda')
    private_directory(state / 'kit')
    return environment, state


def configure_cloudxr(environment: dict, *, mode: str, dry_run: bool) -> None:
    if mode == 'existing':
        root = Path(environment['VLA_CLOUDXR_INSTALL_DIR'])
        runtime = root / 'run'
        if not runtime.is_dir() or runtime.stat().st_uid != os.getuid():
            raise RuntimeError(f'Existing CloudXR IPC must belong to UID {os.getuid()}: {runtime}')
        manifest = root / 'openxr_cloudxr.json'
        if not manifest.is_file() or not os.access(manifest, os.R_OK):
            raise RuntimeError(f'Missing current-user OpenXR manifest: {manifest}')
        environment.update({'ISAACLAB_CXR_SKIP_AUTOLAUNCH': '1',
                            'XR_RUNTIME_JSON': str(manifest), 'NV_CXR_RUNTIME_DIR': str(runtime)})
    elif not dry_run:
        if environment.get('ISAACLAB_CXR_ACCEPT_EULA', '').upper() not in ('1', 'Y', 'YES', 'TRUE'):
            raise RuntimeError('Accept CloudXR EULA with ISAACLAB_CXR_ACCEPT_EULA=1')
        # This deployment uses the upstream default WSS port. Never take over another user's server.
        with socket.socket() as probe:
            try:
                probe.bind(('0.0.0.0', 48322))
            except OSError as error:
                raise RuntimeError('CloudXR port 48322 is occupied. Its owner must stop it, '
                                   'or use --cloudxr-mode existing for YOUR own runtime.') from error


def write_runtime_config(root: Path, stack: dict, state: Path, output: Path) -> Path:
    config = yaml.safe_load((root / 'configs' / stack['s1']).read_text())
    assets = private_directory(state / 'assets')
    config['asset']['composed_urdf'] = str(assets / 'piper_x_gate_c.urdf')
    config['asset']['converted_usd_dir'] = str(assets / 'converted/<composed_urdf_sha256>')
    path = output / 'runtime.yaml'
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return path
