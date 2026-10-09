"""Private socket worker: representative warmup, then immutable live GPU media.

No Isaac/pxr imports. Existing snapshot and optical witness helpers own rendering
and verification; source IDs and simulation times arrive from the live recorder.
"""

import argparse
import hashlib
import json
from multiprocessing.connection import Connection
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
import traceback

import numpy as np

from isaac_vr_live_gpu import GPUConsumer, has_quarantined_owners


def initial_payload(seed):
    """Decode the JSON-only pre-admission seed without consuming a source ordinal."""
    options = seed["single_gpu"]
    payload = dict(options["initial_payload"])
    if "matrix_bytes_hex" in payload:
        payload["matrix_bytes"] = bytes.fromhex(payload.pop("matrix_bytes_hex"))
    elif "matrices" in payload:
        payload["matrix_bytes"] = np.asarray(payload.pop("matrices"), dtype="<f8").tobytes()
    validate_payload(payload, len(seed["paths"]))
    count = options.get("warmup_frames", 12)
    if type(count) is not int or not 1 <= count <= 4096:
        raise ValueError("Warmup needs 1..4096 actual three-camera frames")
    minimum = options["source_minimum_time"]
    if not np.isfinite(minimum) or minimum < 0:
        raise ValueError("Finite nonnegative source_minimum_time required")
    return payload, count, float(minimum)


def validate_payload(payload, path_count):
    for key in [
        "snapshot_id",
        "snapshot_sha256",
        "reset_epoch",
        "state_generation",
        "sim_time_s",
        "intrinsics",
    ]:
        if key not in payload:
            raise ValueError(f"Missing immutable snapshot provenance: {key}")
    raw = payload["matrix_bytes"]
    if type(raw) is not bytes or len(raw) != path_count * 128:
        raise ValueError("Require exact immutable float64 path-ordered matrix bytes")
    matrices = np.frombuffer(raw, dtype="<f8").reshape(path_count, 4, 4)
    if (
        not np.isfinite(matrices).all()
        or not np.allclose(matrices[:, :3, 3], 0)
        or not np.allclose(matrices[:, 3, 3], 1)
    ):
        raise ValueError("Require finite USD affine world matrices")
    intrinsics = np.asarray(payload["intrinsics"], dtype=float)
    if intrinsics.shape != (3, 3) or not np.isfinite(intrinsics).all() or (intrinsics <= 0).any():
        raise ValueError("Require three positive focal/aperture triplets")
    if not np.isfinite(payload["sim_time_s"]) or payload["sim_time_s"] < 0:
        raise ValueError("Invalid source simulation time")
    return matrices, intrinsics


def decode(directory, role, expected, witness, timeout=90):
    """Stream CPU FFmpeg with an actual read deadline and bounded frame buffer."""
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
    errors, count, buffer = [], 0, bytearray()
    frame_size, deadline = 960 * 600 * 3, time.monotonic() + timeout
    with (directory / f"decode-role{role}.log").open("wb") as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("FFmpeg optical decode deadline")
                    if not selector.select(min(remaining, 1)):
                        continue
                    part = os.read(process.stdout.fileno(), frame_size - len(buffer))
                    if not part:
                        if buffer:
                            raise RuntimeError("Short decoded frame")
                        break
                    buffer.extend(part)
                    if len(buffer) != frame_size:
                        continue
                    found = witness.decode(
                        np.frombuffer(buffer, dtype=np.uint8).reshape(600, 960, 3)
                    )
                    if (
                        count >= len(expected)
                        or not found["confident"]
                        or found["row"] != expected[count]
                        or found["role"] != role
                    ):
                        errors.append(dict(frame=count, decoded=found))
                    count += 1
                    buffer = bytearray()
            if process.wait(timeout=max(0.01, deadline - time.monotonic())):
                raise RuntimeError("FFmpeg decode failed")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
    return dict(
        role=role,
        count=count,
        expected=len(expected),
        errors=errors,
        passed=count == len(expected) and not errors,
    )


def run(conn, seed):
    output = Path(seed["output"])
    renderer = stage = consumer = mirror = None
    rows, expected, cleanup_errors = [], [], []
    receipt = dict(
        dataset_admissible=False,
        live_physical_quest_qualified=False,
        scope="single GPU live immutable producer snapshots; standalone renderer/NVENC",
        excluded_dynamic_bodies=seed["excluded_dynamic_bodies"],
        witness=seed["witness"],
        passed=False,
    )
    fatal = False
    error = None

    def save():
        (output / "worker.json").write_text(json.dumps(receipt, indent=2) + "\n")
        (output / "worker-rows.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

    def close_graph():
        nonlocal renderer, stage, mirror
        actions = [
            ("mirror", mirror.close if mirror else None),
            ("detach", renderer.detach_ovstage if renderer else None),
            ("stage", stage.destroy if stage else None),
            ("renderer", renderer.destroy if renderer else None),
        ]
        for name, action in actions:
            if action:
                try:
                    action()
                except BaseException:
                    cleanup_errors.append(dict(action=name, error=traceback.format_exc()))
        mirror = stage = renderer = None

    try:
        for path, digest in seed["helper_hashes"].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                raise RuntimeError("Changed helper " + path)
        if (
            hashlib.sha256(Path(seed["overlay"]).read_bytes()).hexdigest()
            != seed["scene_generation"]
        ):
            raise RuntimeError("Changed stage overlay")
        initial, warmup_frames, minimum_time = initial_payload(seed)
        options = seed["single_gpu"]
        sys.path.insert(0, seed["helpers"])
        import optical_witness as witness
        from ovrtx_snapshot import Snapshot, SnapshotRenderer
        import ovrtx
        import ovstage

        descendants = seed.get("render_descendants", [])
        paths = (
            seed["paths"]
            + [item["path"] for item in descendants]
            + (
                [path for role in range(3) for path in witness.paths(role)]
                if seed["witness"]
                else []
            )
        )
        camera_indices = [seed["paths"].index(camera) for camera in seed["cameras"]]
        fps, delta = 30, 1 / 30

        def capture(payload, source_id, sim_time, *, optical_source_id=None):
            matrices, intrinsics = validate_payload(payload, len(seed["paths"]))
            if descendants:
                local = np.array([item["mesh_to_body"] for item in descendants], dtype="<f8")
                parents = np.array([item["parent_index"] for item in descendants], dtype=np.int64)
                matrices = np.concatenate([matrices, local @ matrices[parents]])
            optical_id = source_id if optical_source_id is None else optical_source_id
            if seed["witness"]:
                matrices = np.concatenate(
                    [
                        matrices,
                        *[
                            witness.matrices(
                                matrices[camera],
                                intrinsics[role],
                                optical_id,
                                role,
                                depth_scale=options.get("witness_depth_scale", 1.0),
                            )
                            for role, camera in enumerate(camera_indices)
                        ],
                    ]
                )
            snapshot = Snapshot.freeze(
                source_id=source_id,
                episode_id=seed["episode_id"],
                scene_generation=seed["scene_generation"],
                sim_time_s=sim_time,
                source_wall_ns=payload.get("source_wall_ns", 0),
                matrices=matrices,
            )
            _, row = mirror.capture(snapshot)
            if [frame["role"] for frame in row["frames"]] != [0, 1, 2]:
                raise RuntimeError("Incomplete rendered camera triplet")
            return row

        def new_consumer(directory):
            return GPUConsumer(
                directory,
                gpu=seed["gpu"],
                fps=fps,
                capacity=seed["capacity"],
                preimage_path=options["gpu_preimage_path"],
                adapter_path=options.get("adapter_path"),
            )

        def new_mirror(last_ordinal, *, continuation_time_s=None):
            continuation = (
                {} if continuation_time_s is None else {"continuation_time_s": continuation_time_s}
            )
            return SnapshotRenderer(
                stage,
                renderer,
                paths=paths,
                cameras=seed["cameras"],
                products=[f"/Live30/Camera{role}" for role in range(3)],
                episode_id=seed["episode_id"],
                scene_generation=seed["scene_generation"],
                initial_delta_s=delta,
                last_ordinal=last_ordinal,
                consumer=consumer,
                **continuation,
            )

        warm_start = float(initial["sim_time_s"]) - warmup_frames * delta
        if warm_start < delta:
            raise ValueError("Initial source time must leave a positive full-frame warmup prefix")
        renderer = ovrtx.Renderer(ovrtx.RendererConfig(read_gpu_transforms=False))
        receipt["read_gpu_transforms"] = False
        stage = ovstage.Stage("live30.single.gpu.live.mirror")
        renderer.attach_ovstage(stage)
        ovstage.population.open_usd(stage, seed["overlay"], ordinal=1)
        receipt["population_domains"] = "RENDERING"
        stage.advance_write_floor(1, ovstage.Scope.ALL).wait()
        consumer = new_consumer(output / "warmup-media")
        mirror = new_mirror(1)
        warmup = dict(
            frames=warmup_frames,
            passed=False,
            recording_admitted=False,
            optical_source_id=0,
            warmup_start_time_s=warm_start,
            initial_snapshot_id=initial["snapshot_id"],
            initial_snapshot_sha256=initial["snapshot_sha256"],
            initial_matrices_sha256=hashlib.sha256(initial["matrix_bytes"]).hexdigest(),
            intrinsics=initial["intrinsics"],
            rows=[],
        )
        receipt["warmup"] = warmup
        started = time.perf_counter_ns()
        for index in range(warmup_frames):
            # Only warmup clock advances; exact source geometry and metadata remain fixed.
            warm_time = warm_start + index * delta
            row = capture(initial, index, warm_time, optical_source_id=0)
            row["recording_admitted"] = False
            row["optical_source_id"] = 0
            warmup["rows"].append(row)
        warmup["encoder"] = consumer.finish()
        warmup["elapsed_ms"] = (time.perf_counter_ns() - started) / 1e6
        last_ordinal = mirror.ordinal
        mirror.close()
        mirror = None
        warmup["passed"] = True
        (output / "warmup.json").write_text(json.dumps(warmup, indent=2) + "\n")
        # Fresh encoder local ordinals and snapshot clock for real source admission.
        consumer = new_consumer(output / "media")
        mirror = new_mirror(last_ordinal, continuation_time_s=warm_time)
        conn.send(dict(kind="ready", warmup_frames=warmup_frames, recording_admitted=False))
        initial_enqueue_ns = None
        last_physics = None
        epoch = initial["reset_epoch"]
        source_intrinsics = np.asarray(initial["intrinsics"], dtype=float)
        while True:
            payload = conn.recv()
            if payload.get("kind") == "stop":
                break
            seq = payload["source_id"]
            if type(seq) is not int or seq != len(expected) or (seed["witness"] and seq >= 4096):
                raise RuntimeError("Live source sequence gap/duplicate/range")
            _, intrinsics = validate_payload(payload, len(seed["paths"]))
            if payload["reset_epoch"] != epoch or not np.array_equal(intrinsics, source_intrinsics):
                raise RuntimeError("Live reset epoch/intrinsics changed")
            if type(payload["physics_step"]) is not int or (
                last_physics is not None and payload["physics_step"] <= last_physics
            ):
                raise RuntimeError("Live physics boundary duplicate/regression")
            if payload["sim_time_s"] < minimum_time:
                raise RuntimeError("Live simulation time precedes admission boundary")
            if initial_enqueue_ns is None:
                initial_enqueue_ns = payload["enqueue_ns"]
            begin = time.perf_counter_ns()
            row = capture(payload, seq, payload["sim_time_s"])
            row.update(
                {
                    key: payload[key]
                    for key in [
                        "snapshot_id",
                        "snapshot_sha256",
                        "reset_epoch",
                        "physics_step",
                        "state_generation",
                    ]
                }
            )
            row.update(
                enqueued_ns=payload["enqueue_ns"],
                worker_complete_ns=time.perf_counter_ns(),
                worker_total_ms=(time.perf_counter_ns() - begin) / 1e6,
            )
            rows.append(row)
            expected.append(seq)
            last_physics = payload["physics_step"]
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
            steady_worker_mean_ms=float(np.mean([row["worker_total_ms"] for row in rows]))
            if rows
            else None,
        )
        close_graph()
        if cleanup_errors:
            raise RuntimeError("Renderer teardown failed; inspect cleanup errors")
        verify_start = time.perf_counter_ns()
        receipt["decoded"] = (
            [decode(output / "media", role, expected, witness) for role in range(3)]
            if seed["witness"]
            else []
        )
        receipt["verification_ms"] = (time.perf_counter_ns() - verify_start) / 1e6
        receipt["passed"] = (
            bool(expected)
            and bool(seed["witness"])
            and all(row["passed"] for row in receipt["decoded"])
        )
    except BaseException:
        error = traceback.format_exc()
        receipt["error"] = error
    finally:
        if consumer and not consumer.closed:
            try:
                consumer.finish()
            except BaseException:
                cleanup_errors.append(dict(action="media_drain", error=traceback.format_exc()))
        if consumer:
            receipt["final_media"] = getattr(
                consumer, "receipt", {"passed": False, "owners_quarantined": True}
            )
            fatal = receipt["final_media"].get("owners_quarantined", True)
        fatal = fatal or has_quarantined_owners()
        if fatal:
            receipt["gpu_resources_retained_until_process_exit"] = True
        else:
            close_graph()
        receipt["cleanup_errors"] = cleanup_errors
        if error or cleanup_errors:
            receipt["passed"] = False
        save()
        try:
            conn.send(
                dict(kind="error", error=error or json.dumps(cleanup_errors))
                if error or cleanup_errors
                else dict(kind="done", receipt=receipt)
            )
        except BaseException:
            error = traceback.format_exc()
            receipt["ipc_error"] = error
            receipt["passed"] = False
            save()
        finally:
            conn.close()
    # CUDA lifetime is unresolved: bypass Python's resource finalizers entirely.
    if fatal:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    return 1 if error or cleanup_errors else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fd", type=int, required=True)
    parser.add_argument("--seed", required=True)
    args = parser.parse_args()
    return run(Connection(args.fd), json.loads(Path(args.seed).read_text()))


if __name__ == "__main__":
    raise SystemExit(main())
