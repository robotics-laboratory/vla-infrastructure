"""Capture the preexisting core native-decoder failure without modifying that env."""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import sys

report = {'command': f'PYTHONDONTWRITEBYTECODE=1 {sys.executable} /tmp/vla-codec-previous-core-probe.py',
          'python': sys.version.split()[0], 'prefix': sys.prefix, 'executable': sys.executable,
          'versions': {name: metadata.version(name) for name in ('torch', 'torchcodec', 'lerobot')},
          'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
try:
    from torchcodec.decoders import VideoDecoder
except Exception as exc:
    error = str(exc)
    report.update(import_passed=False, error_type=type(exc).__name__, error_excerpt=error[:4000],
                  error_truncated=len(error) > 4000,
                  error_sha256=hashlib.sha256(error.encode()).hexdigest())
else:
    report['import_passed'] = True
Path('/tmp/vla-codec-previous-core-failure.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
