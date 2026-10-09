"""One installed compressed LdrColor atlas for full_scene_probe diagnostics.

Import after SimulationApp; replace the three-RP media construction entirely.
No GPU execution on import. Poll/write owns packet bytes before reuse. Source
coverage, uniqueness and per-role frame counts require offline witness decoding.
"""

from pathlib import Path
import hashlib
import importlib.util
import json
import os
import time


class AtlasMedia:
    def __init__(self, env, output, *, warmup=60, helper_path=None):
        helper = Path(helper_path or "/tmp/live30-tiled-probe.py")
        spec = importlib.util.spec_from_file_location("live30_native_atlas", helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        paths = env.camera.camera_prim_paths
        if set(paths) != set(module.ROLES):
            raise ValueError(f"Expected three canonical camera roles: {tuple(paths)}")
        self.env, self.output, self.warmup = env, Path(output), int(warmup)
        self.output.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.probe = module.ThreeCameraProbe(
            {role: str(paths[role]) for role in module.ROLES}, mode="tiled", payload="h264"
        )
        self.stream = (self.output / "atlas.h264").open("xb")
        self.index = (self.output / "atlas_packets.jsonl").open("x", encoding="utf-8")
        self.rows, self.counts, self.empty = [], [0], [0]
        self.last_tick, self.error, self.finished = None, None, None
        pitch = 1920 * 4
        self.manifest = dict(
            self.probe.manifest,
            stream_file="atlas.h264",
            helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),
            adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            role_layout={
                role: dict(
                    tile_index=i,
                    x=(i % 2) * 960,
                    y=(i // 2) * 600,
                    width=960,
                    height=600,
                    rgba_pitch=pitch,
                )
                for role, i in self.probe.role_indices.items()
            },
            encoder_sessions=1,
            encoded_resolution_wh=[1920, 1200],
            native_encoder_eos_exposed=False,
            decoded_role_counts=None,
            source_alignment_proven=False,
        )
        with (self.output / "atlas_manifest.json").open("x", encoding="utf-8") as out:
            json.dump(self.manifest, out, indent=2)

    def after(self, control_tick, *, producer_metadata=None):
        if self.finished is not None or self.error:
            raise RuntimeError(self.error or "Atlas media finished")
        if type(control_tick) is not int or control_tick < 0:
            raise ValueError("Nonnegative integer producer/control tick required")
        if self.last_tick is not None and control_tick != self.last_tick + 1:
            raise RuntimeError("Skipped/repeated control tick")
        physics = int(self.env.sim.get_physics_step_count())
        row = dict(
            control_tick=control_tick,
            source_state_after_physics=physics,
            renderer_source_generation=None,
            source_alignment_proven=False,
            packet_bytes=[0],
            packet_counts_are_atlas_stream=True,
        )
        capture = None
        try:
            capture = self.probe.capture(producer_metadata=producer_metadata)
            if capture is None:
                self.empty[0] += 1
                row["status"] = "warmup_empty"
                if control_tick > self.warmup:
                    raise RuntimeError(f"Empty atlas packet after warmup at tick {control_tick}")
            else:
                data = capture["arrays"]["0"]
                row.update(
                    offset=self.stream.tell(),
                    packet_bytes=[len(data)],
                    packet_sha256=hashlib.sha256(data).hexdigest(),
                    render_completions=capture["render_completions"],
                    fetch_ns=capture["fetch_ns"],
                    host_monotonic_ns=capture["host_monotonic_ns"],
                    producer_metadata=producer_metadata,
                    status="packet_unverified",
                )
                if not data or self.stream.write(data) != len(data):
                    raise RuntimeError("Empty/short atlas packet write")
                self.counts[0] += 1
            if int(self.env.sim.get_physics_step_count()) != physics:
                raise RuntimeError("Physics boundary changed while polling atlas")
            self.last_tick = control_tick
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            row.update(status="failed", error=self.error)
            raise
        finally:
            if capture is not None:
                self.probe.release(capture)
            self.rows.append(row)
            self.index.write(json.dumps(row, separators=(",", ":")) + "\n")
        return row

    def finish(self):
        if self.finished is not None:
            return self.finished
        start = time.perf_counter()
        try:
            for stream in (self.stream, self.index):
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            self.stream.close()
            self.index.close()
            self.probe.close()
        self.finished = dict(
            packet_counts=self.counts,
            empty_packets=self.empty,
            packet_counts_are_atlas_stream=True,
            control_rows=len(self.rows),
            stream_file=str(self.output / "atlas.h264"),
            manifest=self.manifest,
            close_flush_s=time.perf_counter() - start,
            error=self.error,
            native_encoder_eos_exposed=False,
            final_source_coverage_proven=False,
            decoded_role_counts=None,
            dropped_source_frames=None,
        )
        with (self.output / "atlas_result.json").open("x", encoding="utf-8") as out:
            json.dump(self.finished, out, indent=2)
        return self.finished

    def close(self):
        return self.finish()
