import hashlib
import json
from importlib.metadata import version
import os
from pathlib import Path
import resource
import runpy
import sys
import threading
import time

import numpy as np
from PIL import Image

sys.path.insert(0, '/home/ebulochkin/vla_infrastructure')
from tools import isaac_vr_lerobot_materialize as m

root = Path('/tmp/vla-materializer-benchmark-20261007')
mode = sys.argv[1]
if mode == 'prepare':
    root.mkdir(exist_ok=False)
    fixture = runpy.run_path('/home/ebulochkin/vla_infrastructure/tests/test_isaac_vr_lerobot_materialize.py')
    bundle, arrays = fixture['_bundle'](root, frames=60)
    report_path = fixture['_report'](root, arrays)
    report = json.loads(report_path.read_text())
    yy, xx = np.indices(m.IMAGE_SHAPE[:2])
    for item in report['renders']:
        frame = item['frame']
        role = m.CAMERA_ROLES.index(item['role'])
        image = np.empty(m.IMAGE_SHAPE, dtype=np.uint8)
        image[..., 0] = ((xx // 4 + frame + role * 30) % 256).astype(np.uint8)
        image[..., 1] = ((yy // 3 + role * 50) % 256).astype(np.uint8)
        image[..., 2] = (((xx // 32 + yy // 32) % 2) * 100 + 60 + role * 20).astype(np.uint8)
        x = (frame * 7 + role * 150) % (image.shape[1] - 80)
        y = 150 + role * 80
        image[y:y+60, x:x+80] = [220, 30 + role * 60, 70]
        path = Path(item['path'])
        Image.fromarray(image).save(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        item['sha256'] = item['rgb_sha256'] = digest
    report_path.write_text(json.dumps(report))
    print(json.dumps({'source': str(root), 'frames': 60, 'streams': 3, 'shape': m.IMAGE_SHAPE}))
else:
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:4])
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.configs import rgb_encoder_defaults
    streaming = mode.startswith('stream')
    output = root / mode
    stop = threading.Event()
    peak_bytes = [0]
    peak_pngs = [0]

    def sample_disk():
        while not stop.is_set():
            total, pngs = 0, 0
            for tree in list(root.glob('.' + mode + '.tmp-*')) + ([output] if output.exists() else []):
                try:
                    for path in tree.rglob('*'):
                        if path.is_file():
                            total += path.stat().st_size
                            pngs += path.suffix == '.png'
                except FileNotFoundError:
                    pass
            peak_bytes[0] = max(total, peak_bytes[0])
            peak_pngs[0] = max(pngs, peak_pngs[0])
            stop.wait(0.025)

    monitor = threading.Thread(target=sample_disk, daemon=True)
    monitor.start()
    started = time.perf_counter()
    result = m.materialize_projection(
        bundle=root / 'bundle', replay_report=root / 'replay.json', output=output,
        repo_id='local/materializer-benchmark', task_id='dual_cube_to_matching_plates',
        streaming_encoding=streaming, encoder_queue_maxsize=2,
    )
    elapsed = time.perf_counter() - started
    stop.set()
    monitor.join()
    rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    final_bytes = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
    loaded = LeRobotDataset('local/materializer-benchmark', root=output, video_backend='pyav')
    selected = {}
    for index in (0, 29, 59):
        frame = loaded[index]
        for role in m.CAMERA_ROLES:
            selected[f'{index}_{role}'] = frame[f'observation.images.{role}'].numpy()
    np.savez_compressed(root / (mode + '-pixels.npz'), **selected)
    payload = {
        'source_sha256': hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest(),
        'benchmark_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'python': sys.version,
        'packages': {name: version(name) for name in ('lerobot', 'torch', 'torchcodec', 'datasets', 'av', 'numpy', 'pyarrow')},
        'mode': mode, 'streaming_encoding': streaming, 'encoder_queue_maxsize': 2,
        'frames': result['frames'], 'streams': 3, 'shape': list(m.IMAGE_SHAPE),
        'elapsed_seconds_full_pipeline_including_qa': elapsed,
        'max_rss_mib': rss_kib / 1024,
        'peak_output_tree_bytes_sampled_25ms': peak_bytes[0],
        'peak_png_count_sampled_25ms': peak_pngs[0],
        'final_output_bytes': final_bytes, 'cpu_affinity': sorted(os.sched_getaffinity(0)),
        'rgb_encoder': str(rgb_encoder_defaults()), 'qa': result['qa'],
        'admission': result['admission'], 'fingerprint': result['schema_fingerprint_sha256'],
    }
    (root / (mode + '-report.json')).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload))
