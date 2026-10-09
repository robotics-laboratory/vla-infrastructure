"""Three NVENC sessions with optically verifiable input; no scene/XR qualification."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import time
import traceback

import numpy as np
from pynv223_adapter import PacketEncoder, CudaRGBAFrame

p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
p.add_argument("--frames", type=int, default=180)
p.add_argument("--warmup", type=int, default=30)
p.add_argument("--gop", type=int, default=50)
p.add_argument("--gpu-input", action="store_true")
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
r = dict(
    passed=False,
    dataset_admissible=False,
    quest_connected=False,
    scope="generated pixels; no rendering, physics or XR",
    arguments=vars(a).copy(),
    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
)
r["arguments"]["output"] = str(a.output)
r["gpu_before"] = subprocess.check_output(
    ["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader"], text=True
)
encoders, times, submits = [], [], []
try:
    context = stream = 0
    if a.gpu_input:
        import warp as wp

        wp.init()
        device = wp.get_device("cuda:0")
        context, stream = device.context, wp.get_stream(device).cuda_stream
    for role in range(3):
        encoders.append(
            PacketEncoder(
                a.output / f"role{role}",
                cpu=not a.gpu_input,
                cuda_context=context,
                cuda_stream=stream,
                gop=a.gop,
            )
        )
    total = a.frames + a.warmup
    whole_start = time.perf_counter()
    for index in range(total):
        start = time.perf_counter()
        for role, encoder in enumerate(encoders):
            pixels = np.zeros((600, 960, 4), dtype=np.uint8)
            pixels[:, :, 3] = 255
            pixels[100:400, (index * 7) % 800 : ((index * 7) % 800) + 120, role] = 180
            witness = index | (role << 10)
            for bit in range(12):
                pixels[:48, bit * 40 : (bit + 1) * 40, :3] = 255 if witness & (1 << bit) else 0
            frame = pixels
            if a.gpu_input:
                owner = wp.array(pixels, dtype=wp.uint8, device=device)
                wp.synchronize_stream(wp.get_stream(device))
                frame = CudaRGBAFrame(owner, owner.ptr, 960, 600)
            before = time.perf_counter()
            encoder.submit(frame, input_tag=role * 1000000 + index)
            submits.append((time.perf_counter() - before) * 1000)
        if index >= a.warmup:
            times.append((time.perf_counter() - start) * 1000)
    work_end = time.perf_counter()
    for encoder in encoders:
        encoder.finish()
    r.update(
        mean_bundle_ms=statistics.mean(times),
        bundle_hz=1000 / statistics.mean(times),
        p95_bundle_ms=sorted(times)[int(0.95 * (len(times) - 1))],
        mean_submit_ms=statistics.mean(submits),
        whole_working_s=work_end - whole_start,
        drain_s=time.perf_counter() - work_end,
    )
    decoded = []
    for role in range(3):
        errors, count = [], 0
        cmd = [
            "/usr/bin/ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(a.output / f"role{role}/stream.h264"),
            "-vsync",
            "0",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
        with (a.output / f"decode-role{role}.log").open("wb") as log:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log)
            while True:
                raw = proc.stdout.read(960 * 600 * 3)
                if not raw:
                    break
                if len(raw) != 960 * 600 * 3:
                    raise RuntimeError("short decoded frame")
                image = np.frombuffer(raw, dtype=np.uint8).reshape(600, 960, 3)
                witness = sum(
                    (1 << bit)
                    for bit in range(12)
                    if image[12:36, bit * 40 + 12 : bit * 40 + 28].mean() > 127
                )
                if witness != (count | (role << 10)):
                    errors.append(dict(frame=count, witness=witness))
                count += 1
            if proc.wait(timeout=30):
                raise RuntimeError("software decoder failed")
        decoded.append(dict(role=role, frames=count, errors=errors))
    r["decoded"] = decoded
    r["passed"] = all(x["frames"] == total and not x["errors"] for x in decoded)
except BaseException:
    r["error"] = traceback.format_exc()
finally:
    r["encoder_pending_max"] = [encoder.max_pending for encoder in encoders]
    r["cleanup_errors"] = []
    for encoder in encoders:
        if not encoder.closed:
            try:
                encoder.finish()
            except BaseException:
                r["cleanup_errors"].append(traceback.format_exc())
                r["passed"] = False
    (a.output / "result.json").write_text(json.dumps(r, indent=2) + "\n")
print(json.dumps(r, indent=2), flush=True)
raise SystemExit(0 if r["passed"] else 1)
