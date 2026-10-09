"""Decode every diagnostic H264 packet and compare the moving USD witness phase."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--run", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
source = json.loads((args.run / "result.json").read_text())
packets = json.loads((args.run / "packets.json").read_text())
report = {"run": str(args.run), "scope": "USD witness only; no physics/XR qualification", "views": []}
for role in range(3):
    path = args.run / f"view_{role}.h264"
    metadata = subprocess.run([
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,pix_fmt,nb_read_frames",
        "-of", "json", str(path),
    ], capture_output=True, text=True, check=True)
    process = subprocess.Popen([
        "ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    centroids = []
    hashes = []
    frame_bytes = 960 * 600 * 3
    while True:
        # Buffered read requests one full frame, avoiding a bulk video allocation.
        raw = process.stdout.read(frame_bytes)
        if not raw:
            break
        if len(raw) != frame_bytes:
            raise RuntimeError("truncated decoded frame")
        frame = np.frombuffer(raw, dtype=np.uint8).reshape(600, 960, 3).astype(np.int16)
        red = (frame[:, :, 0] > 80) & (frame[:, :, 0] > 2 * frame[:, :, 1]) & (
            frame[:, :, 0] > 2 * frame[:, :, 2]
        )
        y, x = np.nonzero(red)
        if len(x) < 100:
            raise RuntimeError("moving witness absent")
        centroids.append(float(x.mean()))
        hashes.append(hashlib.sha256(raw).hexdigest())
    stderr = process.stderr.read().decode()
    if process.wait() != 0 or stderr:
        raise RuntimeError(f"video decode error: {stderr}")
    values = np.asarray(centroids)
    submitted_ticks = np.asarray([row["tick"] for row in packets if row["packet_bytes"][role]])
    if len(values) != len(submitted_ticks):
        raise RuntimeError("packet/decode count mismatch")
    # Only an ordinal USD-motion assay: it cannot establish PhysX/Fabric state identity.
    candidates = {}
    ticks = np.arange(5, len(values) - 5)
    for lag in range(-5, 6):
        signal = np.sin((submitted_ticks[ticks] + lag) * 0.17)
        design = np.stack([signal, np.ones_like(signal)], axis=1)
        fit = np.linalg.lstsq(design, values[ticks], rcond=None)[0]
        candidates[str(lag)] = float(np.sqrt(np.mean((design @ fit - values[ticks]) ** 2)))
    report["views"].append({
        "view": role, "stream": json.loads(metadata.stdout)["streams"][0],
        "decoded_frames": len(values), "distinct_content_hashes": len(set(hashes)),
        "consecutive_identical_frames": sum(a == b for a, b in zip(hashes, hashes[1:])),
        "best_usd_witness_lag_ticks": int(min(candidates, key=candidates.get)),
        "lag_fit_rmse_pixels": candidates,
        "centroid_min_max": [float(values.min()), float(values.max())],
        "stream_sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
    })
expected = source.get("packet_counts_including_warmup", [0, 0, 0])
report["passed"] = source["passed"] and all(
    view["decoded_frames"] == count and view["best_usd_witness_lag_ticks"] == 0
    and view["consecutive_identical_frames"] == 0
    for view, count in zip(report["views"], expected, strict=True)
)
args.output.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
raise SystemExit(0 if report["passed"] else 1)
