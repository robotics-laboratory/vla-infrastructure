"""Isolated OVRTX 0.5 direct 3-camera static-stage throughput probe.
No IsaacLab/Kit imports; no physics or XR. These numbers never qualify live recording.
Use pinned ovrtx0.5.1.385782 + ovstage0.2.1.385922 on isolated PYTHONPATH.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import statistics
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", required=True)
    p.add_argument("--camera", action="append", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--width", type=int, default=960)
    p.add_argument("--height", type=int, default=600)
    p.add_argument("--warmup", type=int, default=30)
    p.add_argument("--frames", type=int, default=180)
    p.add_argument("--device", type=int, default=0)
    p.add_argument("--readback", choices=["cpu", "none"], default="cpu")
    p.add_argument(
        "--mode",
        choices=["RealTimePathTracing", "PathTracing", "Minimal"],
        default="RealTimePathTracing",
    )
    args = p.parse_args()
    if len(args.camera) != 3 or len(set(args.camera)) != 3:
        p.error("Exactly three distinct absolute USD camera paths required")
    source = Path(args.stage).resolve(strict=True)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    if "@" in str(source) or any(
        not c.startswith("/") or any(x in c for x in "<>\n") for c in args.camera
    ):
        p.error("Unsafe USDA path")
    # Avoid pxr import: OVRTX ships its own USD implementation.
    import numpy as np
    import ovrtx
    import ovstage

    versions = {n: importlib.metadata.version(n) for n in ["ovrtx", "ovstage"]}
    products = [f"/Live30/Camera{i}" for i in range(3)]
    specs = []
    for i, camera in enumerate(args.camera):
        specs.append(f'''def RenderProduct "Camera{i}" (prepend apiSchemas = ["OmniRtxSettingsCommonAdvancedAPI_1"]) {{
            rel camera = <{camera}>
            uint[] deviceIds = [{args.device}]
            uniform int2 resolution = ({args.width}, {args.height})
            token omni:rtx:rendermode = "{args.mode}"
            token[] omni:rtx:waitForEvents = ["AllLoadingFinished", "OnlyOnFirstRequest"]
            rel orderedVars = </Live30/LdrColor>
        }}''')
    usd = (
        "#usda 1.0\n( subLayers = [@"
        + str(source)
        + '@] )\ndef Scope "Live30" {\n'
        + "\n".join(specs)
        + '\ndef RenderVar "LdrColor" {\n uniform string sourceName = "LdrColor"\n}\n}\n'
    )
    overlay = out / "capture-overlay.usda"
    overlay.write_text(usd)
    receipt = dict(
        dataset_admissible=False,
        scope="static scene, no physics, no XR, no encoder",
        unique_live_source_frames_verified=False,
        versions=versions,
        stage=str(source),
        stage_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        settings=vars(args),
        cuda_device_max_connections=os.environ.get("CUDA_DEVICE_MAX_CONNECTIONS"),
    )
    renderer = stage = None
    rows, timings = [], []
    try:
        renderer = ovrtx.Renderer()
        stage = ovstage.Stage("live30.direct.static")
        renderer.attach_ovstage(stage)
        ovstage.population.open_usd(stage, str(overlay), ordinal=1)
        stage.advance_write_floor(1, ovstage.Scope.ALL).wait()
        for index in range(args.warmup + args.frames):
            ordinal = index + 2
            start = time.perf_counter_ns()
            stage.advance_write_floor(ordinal, ovstage.Scope.ALL).wait()
            result = renderer.step(
                render_products=set(products), delta_time=1.0 / 50.0, ordinal=ordinal
            )
            got = []
            for role, path in enumerate(products):
                frames = result[path].frames
                if len(frames) != 1:
                    raise RuntimeError(f"{path}: expected one frame, got {len(frames)}")
                frame = frames[0]
                names = list(frame.render_vars)
                key = "/Live30/LdrColor" if "/Live30/LdrColor" in names else "LdrColor"
                if key not in names:
                    raise RuntimeError(f"No LdrColor; output vars: {names}")
                row = dict(
                    capture_index=index,
                    requested_ordinal=ordinal,
                    role=role,
                    camera=args.camera[role],
                    render_product=path,
                )
                if args.readback == "cpu":
                    mapping = frame.render_vars[key].map(device=ovrtx.Device.CPU)
                    view = np.from_dlpack(mapping)
                    pixels = view.copy()
                    del view
                    mapping.unmap()
                    del mapping
                    if tuple(pixels.shape[:2]) != (args.height, args.width):
                        raise RuntimeError(f"Unexpected pixels shape {pixels.shape}")
                    row["shape"] = list(pixels.shape)
                    # Hash+save only after timing loop for last capture; timing includes D2H copy.
                    if index == args.warmup + args.frames - 1:
                        np.save(out / f"role{role}-last.npy", pixels)
                        row["last_sha256"] = hashlib.sha256(pixels.tobytes()).hexdigest()
                    del pixels
                got.append(row)
                del frame, frames
            del result
            elapsed = (time.perf_counter_ns() - start) / 1e6
            # Last capture includes final artifact save and is excluded from timing.
            if args.warmup <= index < args.warmup + args.frames - 1:
                timings.append(elapsed)
            rows.extend(got)
        receipt.update(
            mean_ms=statistics.mean(timings),
            wall_hz=1000 / statistics.mean(timings),
            p95_ms=sorted(timings)[int(0.95 * (len(timings) - 1))],
            measured_frames=len(timings),
            total_capture_requests=args.warmup + args.frames,
        )
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        (out / "captures.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        if renderer is not None:
            renderer.detach_ovstage()
        if stage is not None:
            stage.destroy()
        if renderer is not None:
            renderer.destroy()
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
