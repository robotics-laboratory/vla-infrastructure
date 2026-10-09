"""Bounded upstream RTX/H264 feasibility probe; no Piper, physics or XR claim."""
# ruff: noqa: E402
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import time
import traceback

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--frames", type=int, default=300)
parser.add_argument("--warmup", type=int, default=60)
parser.add_argument("--renderer", choices=("minimal", "rtx"), default="minimal")
parser.add_argument("--zero-delay", action="store_true")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
report = {
    "scope": "three native 960x600 render products, moving USD cube, live H264 disk writes",
    "excluded": ["physics", "Piper", "actions", "XR", "production temporal qualification"],
    "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "host": platform.node(),
    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "base": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "isaacsim": importlib.metadata.version("isaacsim"),
    "arguments": {**vars(args), "output": str(args.output)},
    "passed": False,
}
app = None
streams = []
try:
    from isaacsim import SimulationApp

    experience = ""
    if args.zero_delay:
        import isaacsim

        experience = str(Path(isaacsim.__file__).parent / "apps/isaacsim.exp.base.zero_delay.kit")
    app = SimulationApp({"headless": True, "width": 960, "height": 600}, experience=experience)
    import carb.settings
    import numpy as np
    import omni.replicator.core as rep
    from pxr import Gf, UsdGeom
    import omni.usd

    settings = carb.settings.get_settings()
    if args.renderer == "minimal":
        settings.set("/rtx/rendermode", "MinimalRendering")
        settings.set("/rtx/minimal/mode", 2)
    settings.set("/omni/replicator/captureOnPlay", False)
    # Primitive assets avoid remote downloads and writable asset installations.
    stage = omni.usd.get_context().get_stage()
    cube = UsdGeom.Cube.Define(stage, "/World/Witness")
    cube.GetSizeAttr().Set(0.4)
    cube.CreateDisplayColorAttr().Set([Gf.Vec3f(1.0, 0.05, 0.05)])
    move = cube.AddTranslateOp()
    move.Set(Gf.Vec3d(0, 0, 0))
    rep.create.light(light_type="Dome", intensity=1000)
    annotators = []
    products = []
    for index in range(3):
        camera = rep.create.camera(position=(0, -3, 1), look_at=(0, 0, 0))
        product = rep.create.render_product(camera, (960, 600))
        annotator = rep.AnnotatorRegistry.get_annotator(
            "LdrColor", device="cpu", init_params={"compression": "h264"}
        )
        annotator.attach(product)
        products.append(product)
        annotators.append(annotator)
        streams.append((args.output / f"view_{index}.h264").open("wb"))
    durations = []
    rows = []
    counts = [0, 0, 0]
    warmup_empty = [0, 0, 0]
    measured_start = None
    for tick in range(args.warmup + args.frames):
        if tick == args.warmup:
            measured_start = time.perf_counter()
        started = time.perf_counter()
        # A distinguishable motion signal for later inspection, not a physics token.
        move.Set(Gf.Vec3d(0.7 * np.sin(tick * 0.17), 0, 0))
        rep.orchestrator.step(rt_subframes=1, delta_time=1.0 / 30, pause_timeline=False)
        sizes = []
        for index, annotator in enumerate(annotators):
            value = annotator.get_data(do_array_copy=True)
            if value is None or not value.size:
                if tick < args.warmup:
                    warmup_empty[index] += 1
                    sizes.append(0)
                    continue
                raise RuntimeError(f"empty compressed data at tick {tick}, view {index}")
            payload = value.tobytes()
            streams[index].write(payload)
            sizes.append(len(payload))
            counts[index] += 1
        if tick >= args.warmup:
            durations.append((time.perf_counter() - started) * 1000)
        rows.append({"tick": tick, "packet_bytes": sizes})
        if tick % 100 == 0:
            print(f"completed {tick + 1} render/encode bundles", flush=True)
    for stream in streams:
        stream.flush()
    elapsed = time.perf_counter() - measured_start
    (args.output / "packets.json").write_text(json.dumps(rows, indent=2) + "\n")
    report.update({
        "passed": True, "packet_counts_including_warmup": counts,
        "warmup_empty_packets": warmup_empty,
        "measured_wall_s_including_disk_flush": elapsed,
        "encoded_bundle_hz": args.frames / elapsed,
        "mean_ms": float(np.mean(durations)),
        "p95_ms": float(np.percentile(durations, 95)),
        "p99_ms": float(np.percentile(durations, 99)),
        "deadline_misses": sum(value > 1000 / 30 for value in durations),
        "actual_render_mode": settings.get("/rtx/rendermode"),
        "decoded_frame_count": "must verify separately; packet count is insufficient",
    })
except Exception:
    report["error"] = traceback.format_exc()
    print(report["error"], flush=True)
finally:
    for stream in streams:
        stream.close()
    report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    if app is not None:
        app.close()
raise SystemExit(0 if report["passed"] else 1)
