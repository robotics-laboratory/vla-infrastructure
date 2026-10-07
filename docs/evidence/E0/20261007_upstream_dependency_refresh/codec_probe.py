"""Bounded synthetic CPU decoder validation, without SDK/hardware or dataset admission."""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
from torchcodec.decoders import VideoDecoder
from lerobot.configs.video import RGBEncoderConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.datasets.video_utils import decode_video_frames

root = Path('/home/ebulochkin/vla_infrastructure')
sample = Path('/tmp/vla-codec-candidate-sample.mp4')
decoder = VideoDecoder(str(sample), device='cpu')
direct = decoder.get_frames_at(indices=[0, 1, 2]).data
frames = decode_video_frames(sample, [0, 1/30, 2/30], tolerance_s=1e-4,
                             backend='torchcodec', return_uint8=True)
assert len(decoder) == 3 and tuple(direct.shape) == (3, 3, 24, 32)
assert (direct == frames).all() and direct[:, 0].float().mean() > 200

dataset_root = Path(tempfile.mkdtemp(prefix='vla-codec-candidate-')) / 'dataset'
features = {'observation.state': {'dtype': 'float32', 'shape': (1,), 'names': ['state']},
            'action': {'dtype': 'float32', 'shape': (1,), 'names': ['action']},
            'observation.images.scene': {'dtype': 'video', 'shape': (24, 32, 3),
                                         'names': ['height', 'width', 'channel']}}
dataset = LeRobotDataset.create(repo_id='tests/codec-candidate', root=dataset_root,
                                fps=30, features=features, use_videos=True,
                                video_backend='torchcodec',
                                rgb_encoder=RGBEncoderConfig(vcodec='h264', crf=0))
for index in range(3):
    dataset.add_frame({'observation.state': np.array([index], dtype=np.float32),
                       'action': np.array([index + 1], dtype=np.float32),
                       'observation.images.scene': direct[index].permute(1, 2, 0).numpy(),
                       'task': 'Synthetic CPU decoder validation.'})
dataset.save_episode()
dataset.finalize()
loaded = LeRobotDataset('tests/codec-candidate', root=dataset_root, video_backend='torchcodec')
assert len(loaded) == 3
for index in range(3):
    row = loaded[index]
    assert tuple(row['observation.images.scene'].shape) == (3, 24, 32)
    assert row['observation.images.scene'][0].mean() > 0.8
    assert row['action'].item() == index + 1

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

report = {'passed': True, 'scope': 'Synthetic CPU decoder/dataset round-trip; no physical or D1 admission',
          'command': f'HF_HOME=/tmp/vla-codec-candidate-hf HF_DATASETS_CACHE=/tmp/vla-codec-candidate-hf/datasets PYTHONDONTWRITEBYTECODE=1 {sys.executable} /tmp/vla-codec-candidate-probe.py',
          'sync_command': 'UV_PROJECT_ENVIRONMENT=/data/ebulochkin/vla-runtime/core-codec-candidate-20261007/env UV_CACHE_DIR=/data/vla-infrastructure/cache/uv uv sync --frozen --group isaac-teleop --python /data/vla-infrastructure/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 --no-managed-python',
          'sample_command': 'ffmpeg -hide_banner -loglevel error -f lavfi -i color=size=32x24:rate=30:color=red -frames:v 3 -c:v libx264 -pix_fmt yuv420p -threads 1 -y /tmp/vla-codec-candidate-sample.mp4',
          'python': sys.version.split()[0], 'prefix': sys.prefix, 'executable': sys.executable,
          'versions': {name: metadata.version(name) for name in ('torch', 'torchcodec', 'lerobot', 'isaacteleop')},
          'source_head': subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip(),
          'source_sha256': {str(path): digest(path) for path in
                            (root/'pyproject.toml', root/'uv.lock', Path(__file__),
                             root/'tools/check_environment_dependencies.py')},
          'video_decoder': {'frames': 3, 'shape': list(direct.shape), 'dtype': str(direct.dtype),
                            'device': str(direct.device), 'sample_sha256': digest(sample)},
          'lerobot': {'explicit_video_backend': 'torchcodec', 'dataset_root': str(dataset_root),
                      'all_rows_read': 3, 'direct_decode_bytes_equal': True},
          'compatibility_source': 'https://github.com/meta-pytorch/torchcodec#compatibility-with-torch-versions'}
Path('/tmp/vla-codec-candidate-decode.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
