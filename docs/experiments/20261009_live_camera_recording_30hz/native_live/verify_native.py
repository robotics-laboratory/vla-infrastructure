"""Decode saved native-camera streams; inspect real optical source/role identity."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    marker_path = Path(__file__).resolve().parent.parent / "temporal_physics/mesh_freshness.py"
    spec = importlib.util.spec_from_file_location("native_verify_marker", marker_path)
    marker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(marker)
    rows = [json.loads(line) for line in (args.input / "native-camera/frames.jsonl").read_text().splitlines()]
    result = dict(schema="native_kit_optical_identity_v1", dataset_admissible=False,
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  input=str(args.input), roles=[], passed=False)
    for role in range(3):
        video = args.input / f"native-camera/media/role{role}/stream.h264"
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
                   "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        stderr = (args.output / f"role{role}.stderr").open("xb")
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr)
        measurements, previous = [], None
        try:
            for index, row in enumerate(rows):
                chunks, total = [], 0
                while total < 960 * 600 * 3:
                    chunk = proc.stdout.read(960 * 600 * 3 - total)
                    if not chunk:
                        raise RuntimeError("Missing/partial frame")
                    chunks.append(chunk)
                    total += len(chunk)
                image = np.frombuffer(b"".join(chunks), np.uint8).reshape(600, 960, 3)
                measurements.append(marker.decode(image, row["source_id"], role, previous))
                previous = row["source_id"]
                if index in (0, 1, len(rows) // 2, len(rows) - 1):
                    Image.fromarray(image).save(args.output / f"role{role}-frame{index:04d}.jpg")
            assert proc.stdout.read(1) == b"", "Extra video frames"
            assert proc.wait(timeout=30) == 0
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            stderr.close()
        offsets = {}
        for m in measurements:
            lag = m["expected_source"] - m["decoded_source"]
            offsets[str(lag)] = offsets.get(str(lag), 0) + 1
        result["roles"].append(dict(role=role, command=command, frames=len(measurements),
                                   lag_histogram=offsets, measurements=measurements,
                                   passed=all(m["passed"] for m in measurements)))
    result["passed"] = all(r["passed"] for r in result["roles"])
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(passed=result["passed"], roles=[{k:v for k,v in r.items() if k != "measurements"} for r in result["roles"]])))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
