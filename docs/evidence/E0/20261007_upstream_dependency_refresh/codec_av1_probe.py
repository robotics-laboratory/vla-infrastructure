from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

import torch
from lerobot.datasets.lerobot_dataset import LeRobotDataset

root=Path('/tmp/vla-materializer-benchmark-20261007/staged_guard_clean')
readers=[LeRobotDataset('tests/encoding-benchmark', root=root, video_backend=backend)
         for backend in ('pyav','torchcodec')]
maximum=0.0
roles=('left_wrist','right_wrist','scene')
for index in range(len(readers[0])):
    pyav_frame, codec_frame=(reader[index] for reader in readers)
    for key in ('observation.state','action','timestamp','frame_index'):
        torch.testing.assert_close(pyav_frame[key],codec_frame[key],rtol=0,atol=0)
    for role in roles:
        key=f'observation.images.{role}'
        assert tuple(codec_frame[key].shape)==(3,600,960)
        difference=(pyav_frame[key]-codec_frame[key]).abs().max().item()
        maximum=max(maximum,difference)
        assert difference<=2/255, (index,role,difference)
project=Path('/home/ebulochkin/vla_infrastructure')
print(json.dumps({
 'passed':True, 'completed_at':datetime.now(timezone.utc).isoformat(),
 'scope':'Full 60-row synthetic native-SVGA AV1 dataset read with explicit TorchCodec; no physical admission',
 'command':'HF_HOME=/tmp/vla-final-hf HF_DATASETS_CACHE=/tmp/vla-final-hf/datasets PYTHONDONTWRITEBYTECODE=1 /data/ebulochkin/vla-runtime/core-codec-candidate-20261007/env/bin/python /tmp/vla-codec-av1-probe.py',
 'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip(),
 'probe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 'input_manifest_sha256':hashlib.sha256((root/'isaac_vr_materialization_manifest.json').read_bytes()).hexdigest(),
 'input_root':str(root), 'interpreter':sys.executable,
 'packages':{name:importlib.metadata.version(name) for name in ('torch','torchcodec','lerobot','av')},
 'rows_read':len(readers[0]),'camera_frames_read':len(readers[0])*len(roles),
 'decoded_shape_chw':[3,600,960],'max_abs_rgb_difference_vs_pyav':maximum,
 'state_action_timestamps_equal':True,
},indent=2))
