"""CPU fault injection: never imports CUDA, Warp, OVRTX or real NVENC."""

import contextlib
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import tempfile
import types
import unittest
import weakref
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1] / "tools"
ART = Path(os.environ.get("LIVE30_CPU_ARTIFACT_DIR", tempfile.mkdtemp(prefix="live30-cpu-media-")))
ART.mkdir(exist_ok=True)


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load("strict_adapter", "isaac_vr_live_nvenc.py")
consumer = load("strict_consumer", "isaac_vr_live_gpu.py")


def packet(i):
    return dict(timestamp=i, data=bytes([i % 256, 0x80]), picture_type="P")


class FakeEncoder:
    def __init__(self, delay=0, encode=None, drain=None):
        self.delay, self.encode_hook, self.drain_hook = delay, encode, drain
        self.calls, self.emitted, self.drain_calls = 0, 0, 0

    def Encode(self, frame, picture):
        ordinal = self.calls
        self.calls += 1
        if self.encode_hook:
            return self.encode_hook(ordinal)
        if self.calls > self.delay:
            out = packet(self.emitted)
            self.emitted += 1
            return [out]
        return []

    def EndEncode(self):
        self.drain_calls += 1
        if self.drain_hook:
            return self.drain_hook()
        result = [packet(i) for i in range(self.emitted, self.calls)]
        self.emitted = self.calls
        return result


class FakeNVC(types.ModuleType):
    __version__ = "2.2.3"
    NV_ENC_PIC_PARAMS = types.SimpleNamespace

    def __init__(self, factory=lambda: FakeEncoder()):
        super().__init__("PyNvVideoCodec")
        self.factory, self.instances, self.options = factory, [], []

    def CreateEncoder(self, *args, **kwargs):
        instance = self.factory()
        self.instances.append(instance)
        self.options.append((args, kwargs))
        return instance


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.path = ART / self.id().split(".")[-1]

    def cpu(self, fake=None, **kwargs):
        return adapter.PacketEncoder(
            self.path, width=2, height=2, _nvc=FakeNVC(lambda: fake or FakeEncoder()), **kwargs
        )

    def frame(self):
        return np.zeros((2, 2, 4), dtype=np.uint8)

    def gpu(self, fake, release, sync, capacity=8):
        return adapter.PacketEncoder(
            self.path,
            width=2,
            height=2,
            cpu=False,
            capacity=capacity,
            release_owner=release,
            synchronize=sync,
            _nvc=FakeNVC(lambda: fake),
        )

    def test_delayed_packets_exact_ledger_and_bounded_owner(self):
        enc = self.cpu(FakeEncoder(delay=3), capacity=4)
        for tag in [10, 20, 30, 40, 50, 60]:
            enc.submit(self.frame(), tag)
        receipt = enc.finish()
        self.assertEqual((receipt["inputs"], receipt["packets"], receipt["max_pending"]), (6, 6, 4))
        rows = [json.loads(row) for row in (self.path / "packets.jsonl").read_text().splitlines()]
        self.assertEqual([r["encoder_packet_timestamp"] for r in rows], list(range(6)))
        self.assertEqual([r["submitted_source_tag"] for r in rows], [10, 20, 30, 40, 50, 60])
        self.assertFalse(any(r["pixel_alignment_proven"] for r in rows))
        self.assertIs(enc.finish(), receipt)

    def test_cpu_owner_retained_until_ack(self):
        enc = self.cpu(FakeEncoder(delay=1))
        frame = self.frame()
        ref = weakref.ref(frame)
        enc.submit(frame, 0)
        del frame
        gc.collect()
        self.assertIsNotNone(ref())
        enc.submit(self.frame(), 1)
        gc.collect()
        self.assertIsNone(ref())
        enc.finish()

    def test_bad_ordinals_write_no_bad_bytes(self):
        bad_values = [1, -1, True, "0", 0.0]
        for i, value in enumerate(bad_values):
            path = self.path / str(i)
            enc = adapter.PacketEncoder(
                path,
                width=2,
                height=2,
                _nvc=FakeNVC(
                    lambda: FakeEncoder(encode=lambda _: [dict(packet(0), timestamp=value)])
                ),
            )
            with self.assertRaises(RuntimeError):
                enc.submit(self.frame(), 0)
            self.assertEqual(enc.bitstream.tell(), 0)
            with self.assertRaises(RuntimeError):
                enc.submit(self.frame(), 1)
            with self.assertRaises(RuntimeError):
                enc.finish()
            self.assertEqual((path / "stream.h264").read_bytes(), b"\x00\x80")
            # Only the later valid drain can write bytes; malformed output writes none.
            self.assertFalse(enc.receipt["passed"])

    def test_duplicate_packet_stops_before_duplicate_write(self):
        fake = FakeEncoder(encode=lambda i: [packet(0), packet(0)] if i == 0 else [])
        enc = self.cpu(fake)
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            enc.submit(self.frame(), 0)
        with self.assertRaises(RuntimeError):
            enc.finish()
        self.assertEqual((self.path / "stream.h264").read_bytes(), bytes([0, 0x80]))
        self.assertEqual(enc.packets, 1)

    def test_missing_drain_keeps_cpu_owner_quarantined(self):
        enc = self.cpu(FakeEncoder(delay=99, drain=lambda: []))
        enc.submit(self.frame(), 0)
        with self.assertRaisesRegex(RuntimeError, "Missing"):
            enc.finish()
        self.assertEqual(enc.receipt["unacknowledged_at_drain"], [0])
        self.assertEqual(len(enc.pending), 1)
        self.assertIsNotNone(enc.encoder)

    def test_gpu_ack_fence_and_failed_fence_quarantine(self):
        log = []
        owner = types.SimpleNamespace(ptr=1)
        frame = adapter.CudaRGBAFrame(owner, 1, 2, 2)

        def release(value):
            self.assertIs(value.owner, owner)
            log.append("ack-fence")

        enc = self.gpu(FakeEncoder(), release, lambda: log.append("drain-fence"))
        enc.submit(frame, 0)
        self.assertEqual(log, ["ack-fence"])
        enc.finish()
        self.assertEqual(log, ["ack-fence", "drain-fence"])
        path = self.path / "failed"

        def fail(_=None):
            raise RuntimeError("fence failed")

        enc = adapter.PacketEncoder(
            path, width=2, height=2, cpu=False, release_owner=fail, synchronize=fail, _nvc=FakeNVC()
        )
        with self.assertRaisesRegex(RuntimeError, "fence failed"):
            enc.submit(frame, 0)
        with self.assertRaises(RuntimeError):
            enc.finish()
        self.assertIs(enc.pending[0], frame)
        self.assertIsNotNone(enc.encoder)
        self.assertFalse(enc.receipt["passed"])

    def test_capacity_rejection_precedes_encode(self):
        fake = FakeEncoder(delay=99)
        enc = self.cpu(fake, capacity=2)
        enc.submit(self.frame(), 0)
        enc.submit(self.frame(), 1)
        with self.assertRaisesRegex(RuntimeError, "capacity"):
            enc.submit(self.frame(), 2)
        self.assertEqual(fake.calls, 2)
        self.assertEqual(len(enc.pending), 2)
        enc.finish()

    def test_encode_exception_poisoned_no_retry_safe_cleanup(self):
        def fail(_):
            raise RuntimeError("driver fault")

        log = []
        enc = self.gpu(FakeEncoder(encode=fail), lambda f: None, lambda: log.append("sync"))
        frame = adapter.CudaRGBAFrame(object(), 1, 2, 2)
        with self.assertRaisesRegex(RuntimeError, "driver fault"):
            enc.submit(frame, 0)
        with self.assertRaisesRegex(RuntimeError, "healthy"):
            enc.submit(frame, 1)
        with self.assertRaises(RuntimeError):
            enc.finish()
        self.assertEqual(log, ["sync"])
        self.assertIsNone(enc.encoder)
        self.assertFalse(enc.pending)

    def test_input_tag_and_thread_guard(self):
        enc = self.cpu()
        for tag in [True, "0", -1, 0.0]:
            with self.assertRaises(ValueError):
                enc.submit(self.frame(), tag)
        enc.submit(self.frame(), 3)
        with self.assertRaises(ValueError):
            enc.submit(self.frame(), 3)
        errors = []

        def foreign():
            try:
                enc.submit(self.frame(), 4)
            except RuntimeError as failure:
                errors.append(str(failure))

        thread = threading.Thread(target=foreign)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)
        enc.finish()

    def test_gpu_empty_queue_failed_drain_fence_retains_encoder(self):
        def fail():
            raise RuntimeError("fatal context")

        enc = self.gpu(FakeEncoder(), lambda frame: None, fail)
        enc.submit(adapter.CudaRGBAFrame(object(), 1, 2, 2), 0)
        with self.assertRaisesRegex(RuntimeError, "fatal context"):
            enc.finish()
        self.assertIsNotNone(enc.encoder)
        self.assertFalse(enc.receipt["passed"])

    def test_empty_output_rejected(self):
        enc = self.cpu(FakeEncoder(encode=lambda _: [dict(packet(0), data=b"")]))
        with self.assertRaisesRegex(RuntimeError, "Empty"):
            enc.submit(self.frame(), 0)
        self.assertEqual(enc.bitstream.tell(), 0)
        with self.assertRaises(RuntimeError):
            enc.finish()


class FakeRuntime:
    def __init__(self):
        self.log, self.sync_error, self.map_error, self.unmap_error = [], False, False, False
        self.device = types.SimpleNamespace(
            is_primary=True, context=11, context_guard=contextlib.nullcontext()
        )
        self.stream = types.SimpleNamespace(
            cuda_stream=12, record_event=lambda: types.SimpleNamespace(cuda_event=13)
        )
        self.wp = types.SimpleNamespace(
            uint8="uint8",
            ScopedStream=lambda *a, **k: contextlib.nullcontext(),
            from_dlpack=lambda mapping: mapping.view,
            clone=self.clone,
            synchronize_event=lambda event: self.log.append("ack-fence"),
            synchronize_stream=self.sync,
        )
        self.ovrtx = types.SimpleNamespace(Device=types.SimpleNamespace(CUDA="fake-cuda"))
        self.tuple = (self.wp, self.ovrtx, self.device, self.stream)

    def clone(self, view):
        self.log.append("clone")
        return types.SimpleNamespace(ptr=1)

    def sync(self, stream):
        self.log.append("sync")
        if self.sync_error:
            raise RuntimeError("sync fault")

    def render_var(self):
        runtime = self

        class Mapping:
            wait_event = 14
            view = types.SimpleNamespace(
                device=runtime.device, dtype="uint8", shape=(2, 2, 4), is_contiguous=True
            )

            def unmap(self, **kwargs):
                runtime.log.append("unmap")
                if runtime.unmap_error:
                    raise RuntimeError("unmap fault")

        class RenderVar:
            def map(self, **kwargs):
                runtime.log.append("map")
                if runtime.map_error:
                    raise ValueError("map fault")
                return Mapping()

        return RenderVar()


class ConsumerTests(unittest.TestCase):
    def setUp(self):
        self.path = ART / self.id().split(".")[-1]
        self.runtime = FakeRuntime()
        self.old = sys.modules.get("PyNvVideoCodec")
        self.fake = FakeNVC(lambda: FakeEncoder(delay=1))
        sys.modules["PyNvVideoCodec"] = self.fake
        self.manifest = ART / (self.id().split(".")[-1] + "-preimages.json")
        self.manifest.write_text(
            json.dumps(
                dict(
                    adapter=str(ROOT / "isaac_vr_live_nvenc.py"),
                    sha256={
                        str(ROOT / "isaac_vr_live_nvenc.py"): hashlib.sha256(
                            (ROOT / "isaac_vr_live_nvenc.py").read_bytes()
                        ).hexdigest()
                    },
                )
            )
        )

    def tearDown(self):
        if self.old is None:
            del sys.modules["PyNvVideoCodec"]
        else:
            sys.modules["PyNvVideoCodec"] = self.old

    def make(self, capacity=8):
        return consumer.GPUConsumer(
            self.path,
            width=2,
            height=2,
            capacity=capacity,
            adapter_path=ROOT / "isaac_vr_live_nvenc.py",
            preimage_path=self.manifest,
            _runtime=self.runtime.tuple,
        )

    def test_complete_triplets_and_release_before_teardown(self):
        c = self.make()
        for source in range(3):
            for role in range(3):
                row = c(role, self.runtime.render_var(), source_id=source)
                self.assertEqual(row["encoder_local_ordinal"], source)
        receipt = c.finish()
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["counts"], [3, 3, 3])
        self.assertEqual(self.runtime.log.count("ack-fence"), 9)
        self.assertEqual(self.runtime.log[-1], "sync")
        self.assertEqual([e.inputs for e in c.encoders], [3, 3, 3])
        (self.path / "consumer.json").write_text(json.dumps(receipt, indent=2))

    def test_missing_role_and_wrong_source_poison_consumer(self):
        c = self.make()
        c(0, self.runtime.render_var(), source_id=0)
        with self.assertRaisesRegex(RuntimeError, "triplet"):
            c(2, self.runtime.render_var(), source_id=0)
        with self.assertRaises(RuntimeError):
            c.finish()
        self.assertFalse(c.receipt["passed"])
        self.assertTrue(all(e.closed for e in c.encoders))
        (self.path / "consumer.json").write_text(json.dumps(c.receipt, indent=2))

    def test_preflight_every_role_before_new_triplet_mapping(self):
        c = self.make(capacity=1)
        for role in range(3):
            c(role, self.runtime.render_var(), source_id=0)
        maps = self.runtime.log.count("map")
        with self.assertRaisesRegex(RuntimeError, "capacity"):
            c(0, self.runtime.render_var(), source_id=1)
        self.assertEqual(self.runtime.log.count("map"), maps)
        with self.assertRaises(RuntimeError):
            c.finish()

    def test_primary_map_error_survives_sync_failure(self):
        c = self.make()
        self.runtime.map_error = self.runtime.sync_error = True
        with self.assertRaisesRegex(ValueError, "map fault"):
            c(0, self.runtime.render_var(), source_id=0)
        with self.assertRaises(RuntimeError):
            c.finish()
        self.assertTrue(c.receipt["owners_quarantined"])
        self.assertTrue(any("map fault" in error for error in c.receipt["errors"]))
        self.assertTrue(any("sync fault" in error for error in c.receipt["errors"]))
        (self.path / "consumer.json").write_text(json.dumps(c.receipt, indent=2))

    def test_exact_roles_sources_and_mutated_preimage(self):
        c = self.make()
        with self.assertRaises(RuntimeError):
            c(True, self.runtime.render_var(), source_id=0)
        with self.assertRaises(ValueError):
            c(0, self.runtime.render_var(), source_id=True)
        c.finish()
        self.manifest.write_text(
            json.dumps(
                dict(
                    adapter=str(ROOT / "isaac_vr_live_nvenc.py"),
                    sha256={str(ROOT / "isaac_vr_live_nvenc.py"): "bad"},
                )
            )
        )
        with self.assertRaisesRegex(RuntimeError, "source changed"):
            consumer.GPUConsumer(
                self.path / "guard", preimage_path=self.manifest, _runtime=self.runtime.tuple
            )

    def test_context_enter_failure_still_publishes_failure_receipt(self):
        c = self.make()

        class BrokenContext:
            def __enter__(self):
                raise RuntimeError("context enter failed")

            def __exit__(self, *args):
                return False

        self.runtime.device.context_guard = BrokenContext()
        with self.assertRaisesRegex(RuntimeError, "context enter failed"):
            c.finish()
        self.assertTrue(c.receipt["owners_quarantined"])
        self.assertFalse(c.receipt["passed"])
        self.assertTrue(all(row["drain_not_reached"] for row in c.receipt["encoder_receipts"]))
        (self.path / "consumer.json").write_text(json.dumps(c.receipt, indent=2))


class CheckedDriverFenceTests(unittest.TestCase):
    def test_real_fence_binding_inspects_nonzero_driver_status(self):
        log = []

        def event(handle):
            log.append(("event", handle))
            return 0

        def stream(handle):
            log.append(("stream", handle))
            return 719

        fences = consumer._CheckedCudaFences(
            _driver=types.SimpleNamespace(cuEventSynchronize=event, cuStreamSynchronize=stream)
        )
        fences.event(types.SimpleNamespace(cuda_event=123))
        with self.assertRaisesRegex(RuntimeError, "status 719"):
            fences.stream(types.SimpleNamespace(cuda_stream=456))
        self.assertEqual(log, [("event", 123), ("stream", 456)])


class WorkerProtocolTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT))
        self.worker = load("live_worker_cpu_test", "isaac_vr_live_worker.py")
        self.output = ART / self.id().split(".")[-1]
        self.output.mkdir()
        overlay = self.output / "mirror.usda"
        overlay.write_text("CPU fake overlay")
        self.raw = np.tile(np.eye(4), (3, 1, 1)).astype("<f8").tobytes()
        self.initial = dict(
            matrix_bytes_hex=self.raw.hex(),
            intrinsics=[[1, 2, 3]] * 3,
            sim_time_s=10.0,
            snapshot_id=7,
            snapshot_sha256="producer-token",
            reset_epoch=0,
            state_generation=10,
        )
        self.seed = dict(
            output=str(self.output),
            overlay=str(overlay),
            helpers=str(self.output),
            helper_hashes={},
            scene_generation=hashlib.sha256(overlay.read_bytes()).hexdigest(),
            paths=["/Camera0", "/Camera1", "/Camera2"],
            cameras=["/Camera0", "/Camera1", "/Camera2"],
            episode_id="cpu-test",
            excluded_dynamic_bodies=[],
            witness=True,
            gpu=0,
            capacity=8,
            single_gpu=dict(
                initial_payload=self.initial,
                warmup_frames=3,
                source_minimum_time=10.0,
                gpu_preimage_path="fake-test-guard",
            ),
        )
        self.events, self.consumers, self.mirrors = [], [], []
        self.optical_calls = []
        test = self

        class Renderer:
            def attach_ovstage(self, stage):
                test.events.append("attach")

            def detach_ovstage(self):
                test.events.append("detach")

            def destroy(self):
                test.events.append("destroy-renderer")

        class Stage:
            def __init__(self, name):
                pass

            def advance_write_floor(self, *args):
                return types.SimpleNamespace(wait=lambda: None)

            def destroy(self):
                test.events.append("destroy-stage")

        class FakeConsumer:
            def __init__(self, directory, **kwargs):
                self.closed, self.counts, self.failed = False, [0, 0, 0], False
                test.consumers.append(self)

            def __call__(self, role, rv, source_id):
                self.counts[role] += 1

            def finish(self):
                self.closed = True
                self.receipt = dict(
                    passed=not self.failed, owners_quarantined=False, counts=self.counts
                )
                test.events.append("media-drain")
                if self.failed:
                    raise RuntimeError("fake media failure")
                return self.receipt

        class Snapshot:
            @staticmethod
            def freeze(**kwargs):
                return types.SimpleNamespace(**kwargs)

        class Mirror:
            def __init__(self, stage, renderer, **kwargs):
                self.ordinal, self.consumer = kwargs["last_ordinal"], kwargs["consumer"]
                self.continuation_time_s = kwargs.get("continuation_time_s")
                self.snapshots = []
                test.mirrors.append(self)

            def capture(self, snapshot):
                self.snapshots.append(snapshot)
                self.ordinal += 1
                frames = []
                for role in range(3):
                    self.consumer(role, None, source_id=snapshot.source_id)
                    frames.append(dict(role=role))
                return [], dict(
                    source_id=snapshot.source_id,
                    frames=frames,
                    source_sim_time_s=snapshot.sim_time_s,
                )

            def close(self):
                test.events.append("mirror-close")

        self.consumer_class = FakeConsumer
        self.modules = {
            "ovrtx": types.SimpleNamespace(Renderer=Renderer),
            "ovstage": types.SimpleNamespace(
                Stage=Stage,
                Scope=types.SimpleNamespace(ALL="all"),
                population=types.SimpleNamespace(open_usd=lambda *a, **k: None),
            ),
            "ovrtx_snapshot": types.SimpleNamespace(Snapshot=Snapshot, SnapshotRenderer=Mirror),
            "optical_witness": types.SimpleNamespace(
                paths=lambda role: [],
                matrices=lambda camera, intrinsics, source, role: (
                    test.optical_calls.append((source, role)) or np.empty((0, 4, 4))
                ),
            ),
        }
        payload = dict(self.initial)
        payload.pop("matrix_bytes_hex")
        payload.update(
            matrix_bytes=self.raw,
            source_id=0,
            physics_step=11,
            source_wall_ns=1,
            enqueue_ns=__import__("time").perf_counter_ns(),
            sim_time_s=10.0,
        )

        class Conn:
            def __init__(self):
                self.incoming, self.sent = [payload, {"kind": "stop"}], []

            def recv(self):
                return self.incoming.pop(0)

            def send(self, message):
                if message["kind"] == "ready":
                    test.assertTrue(test.consumers[0].closed)
                    test.assertEqual(test.consumers[0].counts, [3, 3, 3])
                    test.assertEqual(test.consumers[1].counts, [0, 0, 0])
                self.sent.append(message)

            def close(self):
                test.events.append("ipc-close")

        self.conn = Conn()

    def execute(self):
        with (
            patch.dict(sys.modules, self.modules),
            patch.object(self.worker, "GPUConsumer", self.consumer_class),
            patch.object(self.worker, "has_quarantined_owners", return_value=False),
            patch.object(
                self.worker,
                "decode",
                side_effect=lambda directory, role, expected, witness: dict(
                    passed=True, count=len(expected)
                ),
            ),
        ):
            return self.worker.run(self.conn, self.seed)

    def test_warmup_actual_three_role_calls_before_ready_fresh_source_clock(self):
        self.assertEqual(self.execute(), 0)
        self.assertEqual([row["kind"] for row in self.conn.sent], ["ready", "ack", "done"])
        self.assertEqual([snapshot.source_id for snapshot in self.mirrors[0].snapshots], [0, 1, 2])
        self.assertEqual([snapshot.source_id for snapshot in self.mirrors[1].snapshots], [0])
        self.assertEqual(self.mirrors[1].snapshots[0].sim_time_s, 10.0)
        np.testing.assert_allclose(
            [s.sim_time_s for s in self.mirrors[0].snapshots],
            [10.0 - 3 / 30, 10.0 - 2 / 30, 10.0 - 1 / 30],
        )
        self.assertAlmostEqual(self.mirrors[1].continuation_time_s, 10.0 - 1 / 30)
        self.assertIsNone(self.mirrors[0].continuation_time_s)
        self.assertEqual(self.optical_calls, [(0, role) for _ in range(4) for role in range(3)])
        self.assertTrue(
            all(
                np.array_equal(s.matrices, np.frombuffer(self.raw, dtype="<f8").reshape(3, 4, 4))
                for s in self.mirrors[0].snapshots
            )
        )
        receipt = json.loads((self.output / "worker.json").read_text())
        self.assertTrue(receipt["warmup"]["passed"])
        self.assertFalse(receipt["warmup"]["recording_admitted"])
        self.assertEqual(receipt["warmup"]["optical_source_id"], 0)
        self.assertEqual(receipt["captures"], 1)
        self.assertEqual(self.events[-1], "ipc-close")

    def test_invalid_geometry_rejects_before_gpu_and_preserves_failure_receipt(self):
        self.initial["matrix_bytes_hex"] = "00"
        self.assertEqual(self.execute(), 1)
        self.assertEqual(self.consumers, [])
        self.assertEqual([row["kind"] for row in self.conn.sent], ["error"])
        self.assertFalse(json.loads((self.output / "worker.json").read_text())["passed"])

    def test_warmup_cannot_advance_into_future_of_admitted_source(self):
        self.initial["sim_time_s"] = 0.05
        self.seed["single_gpu"]["source_minimum_time"] = 0.05
        self.assertEqual(self.execute(), 1)
        self.assertEqual(self.consumers, [])
        self.assertEqual([row["kind"] for row in self.conn.sent], ["error"])
        self.assertIn(
            "warmup prefix", json.loads((self.output / "worker.json").read_text())["error"]
        )

    def test_source_duplicate_aborts_segment(self):
        self.conn.incoming.insert(1, dict(self.conn.incoming[0]))
        self.assertEqual(self.execute(), 1)
        self.assertEqual([row["kind"] for row in self.conn.sent], ["ready", "ack", "error"])
        self.assertEqual(self.consumers[-1].counts, [1, 1, 1])

    def test_fatal_quarantine_skips_renderer_finalizers_and_exits_process(self):
        parent = self.consumer_class

        class FatalConsumer(parent):
            def finish(self):
                self.closed = True
                self.receipt = dict(passed=False, owners_quarantined=True)
                raise RuntimeError("fatal CUDA fence")

        self.consumer_class = FatalConsumer

        class FatalExit(BaseException):
            pass

        with patch.object(self.worker.os, "_exit", side_effect=FatalExit):
            with self.assertRaises(FatalExit):
                self.execute()
        self.assertNotIn("detach", self.events)
        self.assertNotIn("destroy-stage", self.events)
        self.assertNotIn("destroy-renderer", self.events)
        self.assertEqual([row["kind"] for row in self.conn.sent], ["error"])
        receipt = json.loads((self.output / "worker.json").read_text())
        self.assertTrue(receipt["gpu_resources_retained_until_process_exit"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    forbidden = [name for name in ("warp", "ovrtx", "torch", "cupy") if name in sys.modules]
    receipt = dict(
        schema="live30_cpu_media_fault_injection_v1",
        tests=result.testsRun,
        passed=result.wasSuccessful() and not forbidden,
        failures=len(result.failures),
        errors=len(result.errors),
        gpu_executed=False,
        actual_nvenc_executed=False,
        forbidden_modules_loaded=forbidden,
        dataset_admissible=False,
        pixel_alignment_proven=False,
        candidate_sha256={
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in ROOT.glob("isaac_vr_live_*.py")
        },
    )
    (ART / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    sys.exit(0 if receipt["passed"] else 1)
