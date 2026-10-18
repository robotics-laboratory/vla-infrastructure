"""Pinned native-media prerequisites, initialized before Kit creates CUDA users.

Reuses the previously audited CUDA12.8/CUPTI source. Builds only in private
launch state; never edits SDKs, installs packages or removes foreign subscribers.
"""
from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ISAAC = Path('/data/vla-infrastructure/isaac61_production/env')
CODEC = Path('/data/ebulochkin/vla-runtime/live30-deep-20261009/optional-pynvcodec')
SOURCE = ROOT / 'tools/native/provider_copy_cupti.cpp'
CUPTI = ISAAC / 'lib/python3.12/site-packages/nvidia/cuda_cupti/lib/libcupti.so.12'
CUPTI_SHA256 = 'fccdc5fcc7c32f8cf4b3ed9b17f7f187a185a6fa0a5bcc06e3434cbd1687c808'
_OWNED = []  # Retain DSOs, layers and pending GPU owners through Kit shutdown.


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(profile, output, *, library_loader=ctypes.CDLL):
    """Resolve the tested codec and, for event preview, own CUPTI before Kit."""
    if not profile['native']:
        return {}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    receipt = dict(runtime=profile['name'], dataset_admissible=False, passed=False)
    try:
        codec_root = Path(os.environ.get('VLA_NATIVE_CODEC_ROOT', CODEC)).resolve()
        if not codec_root.is_dir():
            raise RuntimeError(f'Pinned PyNvVideoCodec target missing: {codec_root}')
        distributions = list(importlib.metadata.distributions(path=[str(codec_root)]))
        codec = [d for d in distributions if d.metadata['Name'].lower() == 'pynvvideocodec']
        if len(codec) != 1 or codec[0].version != '2.2.3':
            raise RuntimeError('Native recording requires the tested PyNvVideoCodec2.2.3 target')
        sys.path.insert(0, str(codec_root))
        receipt['codec'] = dict(root=str(codec_root), version=codec[0].version)
        if profile['early_subscribe']:
            cupti = Path(os.environ.get('VLA_CUPTI_LIBRARY', CUPTI)).resolve()
            if not cupti.is_file() or _sha(cupti) != CUPTI_SHA256:
                raise RuntimeError(f'Pinned CUPTI library missing or changed: {cupti}')
            os.environ['VLA_CUPTI_LIBRARY'] = str(cupti)
            receipt['cupti'] = dict(path=str(cupti), sha256=CUPTI_SHA256)
            shim, build = build_copy_shim(output / 'native-copy')
            os.environ['VLA_NATIVE_COPY_SHIM'] = str(shim)
            library = library_loader(str(shim))
            initialize = library.vla_copy_probe_init
            initialize.argtypes, initialize.restype = [], ctypes.c_int
            status = initialize()
            receipt['copy_shim'] = dict(path=str(shim), sha256=_sha(shim), build=build,
                                        subscription_status=status)
            if status:
                raise RuntimeError(f'Early scoped CUPTI subscription failed: {status}')
            _OWNED.append(library)
        receipt['passed'] = True
        return receipt
    except BaseException as exc:
        receipt['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        (output / 'native_dependencies.json').write_text(json.dumps(receipt, indent=2) + '\n')


def build_copy_shim(output):
    """Compile the exact retained adapter against this installed SDK's headers."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    candidates = sorted((ISAAC / 'lib/python3.12/site-packages/isaacsim/extscache').glob(
        'omni.rtx.spg-*/deps/cuda/include'))
    if len(candidates) != 1:
        raise RuntimeError(f'Expected one pinned CUDA header tree, got {candidates}')
    include = candidates[0]
    headers = {name: _sha(include / name) for name in ('cuda.h', 'cuda_runtime_api.h', 'cupti.h')}
    binary = output / 'provider_copy_cupti.so'
    command = ['g++', '-std=c++17', '-O2', '-fPIC', '-shared', '-Wall', '-Wextra', '-Werror',
               '-I' + str(include), str(SOURCE), '-o', str(binary), '-ldl', '-pthread']
    result = subprocess.run(command, capture_output=True, text=True)
    receipt = dict(command=command, returncode=result.returncode, source_sha256=_sha(SOURCE),
                   headers=headers, stdout=result.stdout, stderr=result.stderr)
    (output / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if result.returncode:
        raise RuntimeError(f'CUPTI adapter build failed; see {output / "build.json"}')
    return binary, receipt


def prepare_stage(profile, sim):
    """Author source attributes before the first ordinary SimulationContext.reset."""
    if not profile['native'] or not profile['media'].get('source_proof'):
        return None
    from isaac_vr_native_source_proof import prepare_source_proof_stage

    options = profile['media']
    layer = prepare_source_proof_stage(
        sim, clock_only=options.get('proof_clock_only', False),
        attribute_probe=options.get('attribute_probe', False),
        attribute_only=options.get('attribute_only', False),
        identity_only=options.get('identity_only', False),
    )
    _OWNED.append(layer)
    return layer


def retain(owner):
    _OWNED.append(owner)
