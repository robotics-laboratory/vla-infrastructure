"""Private inherited socket worker: sequential immutable live snapshots -> OVRTX/NVENC.
Never imports pxr/IsaacSim; all scene input comes from the just-opened live recorder.
"""

import argparse
import hashlib
import json
from multiprocessing.connection import Connection
from pathlib import Path
import subprocess
import sys
import time
import traceback
import numpy as np


def decode(directory, role, expected, witness):
    command = [
        "/usr/bin/ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(directory / f"role{role}/stream.h264"),
        "-vsync",
        "0",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]
    errors, count = [], 0
    with (directory / f"decode-role{role}.log").open("wb") as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)
        try:
            while True:
                payload = bytearray()
                while len(payload) < 960 * 600 * 3:
                    part = process.stdout.read(960 * 600 * 3 - len(payload))
                    if not part:
                        break
                    payload.extend(part)
                if not payload:
                    break
                if len(payload) != 960 * 600 * 3:
                    raise RuntimeError("Short decoded frame")
                found = witness.decode(np.frombuffer(payload, dtype=np.uint8).reshape(600, 960, 3))
                if (
                    count >= len(expected)
                    or not found["confident"]
                    or found["row"] != expected[count]
                    or found["role"] != role
                ):
                    errors.append(dict(frame=count, decoded=found))
                count += 1
            if process.wait(timeout=30):
                raise RuntimeError("FFmpeg decode failed")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return dict(
        role=role,
        count=count,
        expected=len(expected),
        errors=errors,
        passed=count == len(expected) and not errors,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fd", type=int, required=True)
    parser.add_argument("--seed", required=True)
    args = parser.parse_args()
    conn = Connection(args.fd)
    seed = json.loads(Path(args.seed).read_text())
    output = Path(seed["output"])
    for path, digest in seed["helper_hashes"].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Changed helper " + path)
    if hashlib.sha256(Path(seed["overlay"]).read_bytes()).hexdigest() != seed["scene_generation"]:
        raise RuntimeError("Changed stage overlay")
    sys.path.insert(0, seed["helpers"])
    import optical_witness as witness
    from ovrtx_snapshot import Snapshot, SnapshotRenderer
    from ovrtx_gpu_consumer import GPUConsumer
    import ovrtx
    import ovstage

    renderer = stage = consumer = mirror = None
    rows, expected = [], []
    receipt = dict(
        dataset_admissible=False,
        live_physical_quest_qualified=False,
        scope="live producer separate renderer process",
        excluded_dynamic_bodies=seed["excluded_dynamic_bodies"],
        witness=seed["witness"],
        passed=False,
    )
    try:
        renderer = ovrtx.Renderer()
        stage = ovstage.Stage("live30.actual.live.mirror")
        renderer.attach_ovstage(stage)
        ovstage.population.open_usd(stage, seed["overlay"], ordinal=1)
        stage.advance_write_floor(1, ovstage.Scope.ALL).wait()
        consumer = GPUConsumer(output / "media", gpu=seed["gpu"], fps=30)
        paths = seed["paths"] + (
            [p for r in range(3) for p in witness.paths(r)] if seed["witness"] else []
        )
        camera_indices = [seed["paths"].index(camera) for camera in seed["cameras"]]
        conn.send(dict(kind="ready"))
        initial_enqueue_ns = None
        epoch = None
        while True:
            payload = conn.recv()
            if payload.get("kind") == "stop":
                break
            seq = payload["source_id"]
            if seq != len(expected):
                raise RuntimeError("Live source sequence gap/duplicate")
            if epoch is None:
                epoch = payload["reset_epoch"]
            if payload["reset_epoch"] != epoch:
                raise RuntimeError("Live reset epoch changed")
            if initial_enqueue_ns is None:
                initial_enqueue_ns = payload["enqueue_ns"]
            begin = time.perf_counter_ns()
            matrices = np.frombuffer(payload["matrix_bytes"], dtype="<f8").reshape(
                len(seed["paths"]), 4, 4
            )
            if seed["witness"]:
                boards = [
                    witness.matrices(matrices[c], payload["intrinsics"][r], seq, r)
                    for r, c in enumerate(camera_indices)
                ]
                matrices = np.concatenate([matrices, *boards])
            if mirror is None:
                mirror = SnapshotRenderer(
                    stage,
                    renderer,
                    paths=paths,
                    cameras=seed["cameras"],
                    products=[f"/Live30/Camera{r}" for r in range(3)],
                    episode_id=seed["episode_id"],
                    scene_generation=seed["scene_generation"],
                    initial_delta_s=1 / 30,
                    consumer=consumer,
                )
            snapshot = Snapshot.freeze(
                source_id=seq,
                episode_id=seed["episode_id"],
                scene_generation=seed["scene_generation"],
                sim_time_s=payload["sim_time_s"],
                source_wall_ns=payload["source_wall_ns"],
                matrices=matrices,
            )
            _, row = mirror.capture(snapshot)
            row.update(
                snapshot_id=payload["snapshot_id"],
                snapshot_sha256=payload["snapshot_sha256"],
                reset_epoch=epoch,
                physics_step=payload["physics_step"],
                state_generation=payload["state_generation"],
                enqueued_ns=payload["enqueue_ns"],
                worker_complete_ns=time.perf_counter_ns(),
                worker_total_ms=(time.perf_counter_ns() - begin) / 1e6,
            )
            rows.append(row)
            expected.append(seq)
            conn.send(dict(kind="ack", source_id=seq))
        drain_started = time.perf_counter_ns()
        receipt["encoder"] = consumer.finish()
        encode_done = time.perf_counter_ns()
        receipt.update(
            captures=len(expected),
            encode_done_ns=encode_done,
            encode_drain_ms=(encode_done - drain_started) / 1e6,
            completed_elapsed_s=(encode_done - initial_enqueue_ns) / 1e9
            if initial_enqueue_ns
            else None,
            steady_worker_mean_ms=float(np.mean([r["worker_total_ms"] for r in rows[60:]]))
            if len(rows) > 60
            else None,
        )
        # Release RTX/GPU before CPU verification; producer remains blocked only at final drain.
        if mirror:
            mirror.close()
            mirror = None
        renderer.detach_ovstage()
        stage.destroy()
        stage = None
        renderer.destroy()
        renderer = None
        verify_start = time.perf_counter_ns()
        receipt["decoded"] = (
            [decode(output / "media", r, expected, witness) for r in range(3)]
            if seed["witness"]
            else []
        )
        receipt["verification_ms"] = (time.perf_counter_ns() - verify_start) / 1e6
        receipt["passed"] = seed["witness"] and all(r["passed"] for r in receipt["decoded"])
        (output / "worker.json").write_text(json.dumps(receipt, indent=2) + "\n")
        (output / "worker-rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        conn.send(dict(kind="done", receipt=receipt))
    except BaseException:
        receipt["error"] = traceback.format_exc()
        try:
            conn.send(dict(kind="error", error=receipt["error"]))
        except BaseException:
            pass
        raise
    finally:
        if consumer and not consumer.closed:
            try:
                consumer.finish()
            except BaseException:
                receipt["cleanup_error"] = traceback.format_exc()
        if mirror:
            mirror.close()
        if renderer:
            renderer.detach_ovstage()
        if stage:
            stage.destroy()
        if renderer:
            renderer.destroy()
        (output / "worker.json").write_text(json.dumps(receipt, indent=2) + "\n")
        (output / "worker-rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        conn.close()


if __name__ == "__main__":
    main()
