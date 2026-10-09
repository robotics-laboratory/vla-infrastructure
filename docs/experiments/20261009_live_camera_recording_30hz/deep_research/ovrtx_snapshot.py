"""Rigid snapshot -> isolated OVRTX0.5.1/ovstage0.2.1 direct worker adapter.
No imports of NVIDIA packages until constructed; no SDK files edited.
Own the stage exclusively on this worker thread. No concurrent stage mutation.
Caller must enumerate ALL moving rigid links/props/cameras and validate their USD paths.
Frozen material/topology/intrinsics generation only; rebuild adapter after scene reset.
"""

from dataclasses import dataclass
import hashlib
import importlib.metadata
import json
from pathlib import Path
import threading
import time

MANIFEST = Path(__file__).with_name("ovrtx_snapshot_preimages.json")


def verify_preimages():
    manifest = json.loads(MANIFEST.read_text())
    for path, expected in manifest["sha256"].items():
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"OVRTX preimage changed: {path}")
    for name, version in manifest["versions"].items():
        if importlib.metadata.version(name) != version:
            raise RuntimeError(f"OVRTX version mismatch: {name}")


@dataclass(frozen=True)
class Snapshot:
    source_id: int
    episode_id: str
    scene_generation: str
    sim_time_s: float
    source_wall_ns: int
    matrix_bytes: bytes

    @classmethod
    def freeze(
        cls, *, source_id, episode_id, scene_generation, sim_time_s, source_wall_ns, matrices
    ):
        import numpy as np

        array = np.asarray(matrices, dtype="<f8")
        if array.ndim != 3 or array.shape[1:] != (4, 4) or not np.isfinite(array).all():
            raise ValueError(
                "Expected finite N x 4 x 4 world matrices in USD row-vector convention"
            )
        if not np.allclose(array[:, :3, 3], 0) or not np.allclose(array[:, 3, 3], 1):
            raise ValueError("World matrices must use USD last-row translation affine convention")
        if not np.isfinite(sim_time_s) or int(source_id) != source_id or source_id < 0:
            raise ValueError("Invalid snapshot identity/time")
        return cls(
            int(source_id),
            str(episode_id),
            str(scene_generation),
            float(sim_time_s),
            int(source_wall_ns),
            array.tobytes(order="C"),
        )


class SnapshotRenderer:
    """Apply snapshot, publish, synchronously render, copy pixels before next mutation.

    Pass a loaded, attached ovstage/renderer with last published ordinal. Path order
    is the matrix order; include three cameras. Initial sim delta is explicit.
    Products and cameras are three ordered absolute paths; role order preserved.
    Returned source_id describes requested immutable state, not independent optical
    proof. Validate animated marker/pose content before claiming source correctness.
    """

    def __init__(
        self,
        stage,
        renderer,
        *,
        paths,
        cameras,
        products,
        episode_id,
        scene_generation,
        last_ordinal=1,
        initial_delta_s=1 / 30,
        render_var="/Live30/LdrColor",
        width=960,
        height=600,
        consumer=None,
        continuation_time_s=None,
    ):
        verify_preimages()
        import ovstage

        if len(paths) != len(set(paths)) or not paths:
            raise ValueError("Snapshot paths must be nonempty and unique")
        if len(cameras) != 3 or len(products) != 3 or len(set(products)) != 3:
            raise ValueError("Exactly three distinct render products required")
        if not set(cameras).issubset(paths):
            raise ValueError("Snapshot must include every camera world transform")
        self.stage, self.renderer = stage, renderer
        self.paths, self.cameras, self.products = tuple(paths), tuple(cameras), tuple(products)
        self.episode_id, self.scene_generation = str(episode_id), str(scene_generation)
        self.ordinal, self.initial_delta_s = int(last_ordinal), float(initial_delta_s)
        self.render_var, self.width, self.height = render_var, width, height
        self.consumer = consumer
        self.thread = threading.get_ident()
        self.last_source_id = self.last_time = None
        self.busy = self.closed = self.failed = False
        self.dictionary = ovstage.PathDictionary(stage)
        self.path_list = self.dictionary.create_path_list_from_strings(self.paths)
        if tuple(self.dictionary.get_path_strings(self.path_list)) != self.paths:
            raise RuntimeError("Path list reordered; refuse ambiguous snapshot binding")
        self.query = stage.query_from_path_list(self.path_list)
        self.first = True
        if continuation_time_s is not None:
            import math
            if not math.isfinite(continuation_time_s) or continuation_time_s < 0:
                raise ValueError("Invalid already-rendered continuation time")
            # The same stage/path set has already received resetXformStack and
            # rendered warmup. Preserve renderer caches and its current clock;
            # admitted source IDs and encoder ordinals still start afresh.
            self.last_time = float(continuation_time_s)
            self.first = False

    def _guard(self):
        if self.closed or self.failed or self.busy or threading.get_ident() != self.thread:
            raise RuntimeError(
                "Snapshot renderer requires exclusive, healthy worker-thread ownership"
            )

    def capture(self, snapshot):
        self._guard()
        import numpy as np
        import ovstage
        import ovrtx

        if (
            snapshot.episode_id != self.episode_id
            or snapshot.scene_generation != self.scene_generation
        ):
            raise ValueError("Episode/scene generation changed: flush queue and reconstruct worker")
        if self.last_source_id is not None and snapshot.source_id != self.last_source_id + 1:
            raise ValueError("Source sequence gap/duplicate; do not silently drop a snapshot")
        matrices = np.frombuffer(snapshot.matrix_bytes, dtype="<f8")
        if matrices.size != len(self.paths) * 16:
            raise ValueError("Snapshot transform count changed")
        matrices = matrices.reshape(len(self.paths), 4, 4)
        delta = (
            self.initial_delta_s if self.last_time is None else snapshot.sim_time_s - self.last_time
        )
        if not np.isfinite(delta) or delta <= 0:
            raise ValueError("Non-increasing simulation time")
        if self.first and snapshot.sim_time_s < delta:
            raise ValueError(
                "First snapshot must follow initial_delta_s of physics; time-zero priming needs separate policy"
            )
        self.busy = True
        self.ordinal += 1
        begin = time.perf_counter_ns()
        try:
            if self.first:
                self.renderer.reset(time=snapshot.sim_time_s - delta)
                self.stage.write_attribute(
                    self.query,
                    "omni:resetXformStack",
                    self.ordinal,
                    np.ones(len(self.paths), dtype=np.bool_),
                    is_array=False,
                ).wait()
            self.stage.write_attribute(
                self.query,
                "omni:xform",
                self.ordinal,
                matrices,
                is_array=False,
                semantic=ovstage.AttributeSemantic.MATRIX,
            ).wait()
            self.stage.advance_write_floor(self.ordinal, ovstage.Scope.ALL).wait()
            published = time.perf_counter_ns()
            outputs = self.renderer.step(set(self.products), delta, ordinal=self.ordinal)
            rendered = time.perf_counter_ns()
            images, frames = [], []
            try:
                for role, product in enumerate(self.products):
                    produced = outputs[product].frames
                    if len(produced) != 1:
                        raise RuntimeError(
                            f"Expected exactly one real frame per source/product; {len(produced)}"
                        )
                    frame = produced[0]
                    gpu = None
                    if self.consumer:
                        gpu = self.consumer(
                            role, frame.render_vars[self.render_var], source_id=snapshot.source_id
                        )
                    else:
                        with frame.render_vars[self.render_var].map(
                            device=ovrtx.Device.CPU
                        ) as mapping:
                            view = np.from_dlpack(mapping)
                            image = view.copy()
                            del view
                        if image.shape[:2] != (self.height, self.width):
                            raise RuntimeError(f"Unexpected image shape: {image.shape}")
                        images.append(image)
                    frames.append(
                        dict(
                            role=role,
                            camera=self.cameras[role],
                            product=product,
                            capture_start=frame.start_time,
                            capture_end=frame.end_time,
                            progression=frame.progression,
                            gpu=gpu,
                        )
                    )
                sensor_clock = [outputs.simulation_start_time, outputs.simulation_end_time]
                if not np.isclose(sensor_clock[1], snapshot.sim_time_s, rtol=0, atol=1e-7):
                    raise RuntimeError("OVRTX sensor clock drift from source simulation time")
            finally:
                del outputs
            self.last_source_id, self.last_time = snapshot.source_id, snapshot.sim_time_s
            self.first = False
            end = time.perf_counter_ns()
            return images, dict(
                dataset_admissible=False,
                optical_phase_verified=False,
                source_id=snapshot.source_id,
                episode_id=snapshot.episode_id,
                scene_generation=snapshot.scene_generation,
                source_sim_time_s=snapshot.sim_time_s,
                source_wall_ns=snapshot.source_wall_ns,
                ordinal=self.ordinal,
                transform_sha256=hashlib.sha256(snapshot.matrix_bytes).hexdigest(),
                sensor_clock=sensor_clock,
                frames=frames,
                output_path="owned GPU NVENC" if self.consumer else "CPU pixels",
                apply_publish_ms=(published - begin) / 1e6,
                render_ms=(rendered - published) / 1e6,
                output_consume_ms=(end - rendered) / 1e6,
                total_ms=(end - begin) / 1e6,
            )
        except BaseException:
            # Partly published state cannot be retried under the same source identity.
            self.failed = True
            raise
        finally:
            self.busy = False

    def close(self):
        if self.closed:
            return
        if self.busy or threading.get_ident() != self.thread:
            raise RuntimeError("Close on idle owner thread")
        self.stage.release_query(self.query).wait()
        self.dictionary.destroy_path_list(self.path_list)
        self.dictionary.destroy()
        self.closed = True
