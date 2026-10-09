"""Opt-in live recorder observer + bounded local subprocess mirror. No GPU on import.
Attach only after start_live_recording; never samples state itself or changes labels.
"""

import hashlib
import importlib.util
import json
from multiprocessing.connection import Connection
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import numpy as np

HERE = Path(
    "/home/ebulochkin/vla_infrastructure/docs/experiments/20261009_live_camera_recording_30hz/deep_research"
)
RUNTIME = Path("/data/ebulochkin/vla-runtime/live30-deep-20261009")
ROLES = ["left_wrist", "right_wrist", "scene"]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class LiveMirror:
    def __init__(
        self,
        record,
        output,
        *,
        gpu=0,
        witness=True,
        capacity=8,
        startup_timeout=180,
        helpers=HERE,
        worker=HERE / "mirror_worker.py",
        worker_env=None,
    ):
        if capacity != 8 or record._next_capture_sequence != 0:
            raise ValueError(
                "Requires capacity8 and installation before first recorder observation"
            )
        guard = json.loads(Path(__file__).with_name("live_mirror_preimages.json").read_text())
        for path, digest in guard.items():
            if sha(path) != digest:
                raise RuntimeError(f"Live mirror source changed: {path}")
        self.record, self.output = record, Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.original, self.was_owned = (
            record._capture_new_observation,
            "_capture_new_observation" in vars(record),
        )
        self.previous = vars(record).get("_capture_new_observation")
        self.capacity, self.pending, self.sent, self.acked = capacity, {}, 0, 0
        self.max_pending, self.blocked_ms, self.ages_ms = 0, 0.0, []
        self.closed, self.reset_epoch, self.last_physics = False, None, None
        self.proc = self.conn = self.log = None
        self.pose = load(helpers / "ovrtx_live_probe.py", "live30_pose").pose_matrices
        witness_module = load(helpers / "optical_witness.py", "live30_witness")
        metadata = self._seed(helpers, gpu, witness, witness_module)
        self.metadata = metadata
        parent, child = socket.socketpair()
        self.conn = Connection(parent.detach())
        env = dict(os.environ if worker_env is None else worker_env)
        env["PYTHONPATH"] = os.pathsep.join(
            map(str, [RUNTIME / "optional-ovrtx", RUNTIME / "optional-pynvcodec", helpers])
        )
        self.log = (self.output / "worker.log").open("wb")
        try:
            self.proc = subprocess.Popen(
                [
                    sys.executable,
                    str(worker),
                    "--fd",
                    str(child.fileno()),
                    "--seed",
                    str(self.output / "seed.json"),
                ],
                env=env,
                pass_fds=(child.fileno(),),
                stdout=self.log,
                stderr=self.log,
            )
            child.close()
            message = self._receive(startup_timeout)
            if message.get("kind") != "ready":
                raise RuntimeError(f"Worker startup failed: {message}")
            record._capture_new_observation = self.capture
        except BaseException:
            child.close()
            self.abort()
            raise

    def _seed(self, helpers, gpu, witness, witness_module):
        from pxr import Usd, UsdGeom, UsdPhysics

        manifest_path = self.record.output_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        (self.output / "source-manifest.json").write_bytes(manifest_path.read_bytes())
        if sha(self.record.snapshot) != manifest["stage_snapshot_sha256"]:
            raise ValueError("Current recorder stage hash mismatch")
        entries = [
            r.to_manifest()
            for r in self.record.recordables
            if r.to_manifest()["type"] in ["articulation", "rigid_body", "camera"]
        ]
        paths = [p for e in entries for p in e.get("link_paths", [e.get("prim_path")])]
        cameras = [manifest["camera_roles"][r] for r in ROLES]
        if len(paths) != len(set(paths)) or not set(cameras).issubset(paths):
            raise ValueError("Bad pose coverage")
        stage = Usd.Stage.Open(str(self.record.snapshot))
        for path in paths:
            prim = stage.GetPrimAtPath(path)
            if not prim:
                raise ValueError(f"Missing USD path {path}")
            matrix = np.array(
                UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            )
            if not np.allclose(np.linalg.norm(matrix[:3, :3], axis=1), 1, atol=1e-5):
                raise ValueError("Nonunit scale unsupported")
        rigid = [str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)]
        missing = sorted(set(rigid) - set(paths))
        if set(missing) - {"/World/RobosynDemo/ValidationProbe"}:
            raise ValueError(f"Unrecorded dynamic bodies: {missing}")
        usd = "#usda 1.0\n( subLayers = [@" + str(self.record.snapshot.resolve()) + "@]\n"
        usd += f' metersPerUnit = {UsdGeom.GetStageMetersPerUnit(stage)}\n upAxis = "{UsdGeom.GetStageUpAxis(stage)}"\n)\n'
        if missing:
            usd += 'over "World" {\n over "RobosynDemo" {\n over "ValidationProbe" (active = false) {}\n }\n}\n'
        usd += 'def Scope "Live30" {\n'
        for role, camera in enumerate(cameras):
            usd += f"""def RenderProduct "Camera{role}" (prepend apiSchemas = ["OmniRtxSettingsCommonAdvancedAPI_1"]) {{
 rel camera = <{camera}>
 uint[] deviceIds = [{gpu}]
 uniform int2 resolution = (960, 600)
 token omni:rtx:rendermode = "RealTimePathTracing"
 token[] omni:rtx:waitForEvents = ["AllLoadingFinished", "OnlyOnFirstRequest"]
 rel orderedVars = </Live30/LdrColor>
}}\n"""
        usd += 'def RenderVar "LdrColor" {\n uniform string sourceName = "LdrColor"\n}\n}\n'
        if witness:
            usd += witness_module.usd()
        overlay = self.output / "mirror.usda"
        overlay.write_text(usd)
        if not Usd.Stage.Open(str(overlay)):
            raise ValueError("Overlay USD parse failed")
        self.entries, self.paths, self.cameras, self.intrinsics = entries, paths, cameras, None
        metadata = dict(
            output=str(self.output.resolve()),
            overlay=str(overlay.resolve()),
            helpers=str(helpers),
            paths=paths,
            cameras=cameras,
            episode_id=self.record.episode_id,
            run_id=self.record.run_id,
            scene_generation=sha(overlay),
            source_stage_sha256=sha(self.record.snapshot),
            source_manifest_sha256=sha(manifest_path),
            rigid_bodies=rigid,
            excluded_dynamic_bodies=missing,
            witness=witness,
            gpu=gpu,
            capacity=self.capacity,
            dataset_admissible=False,
        )
        metadata["helper_hashes"] = {
            str(helpers / f): sha(helpers / f)
            for f in ["ovrtx_snapshot.py", "ovrtx_gpu_consumer.py", "optical_witness.py"]
        }
        (self.output / "seed.json").write_text(json.dumps(metadata, indent=2) + "\n")
        return metadata

    def _receive(self, timeout=120):
        if not self.conn.poll(timeout):
            raise RuntimeError(f"Mirror IPC timeout; worker={self.proc.poll()}")
        message = self.conn.recv()
        if message.get("kind") == "error":
            raise RuntimeError(message["error"])
        return message

    def _ack(self, message):
        seq = message["source_id"]
        if message.get("kind") != "ack" or seq not in self.pending:
            raise RuntimeError("Unexpected mirror ACK")
        snapshot = self.pending.pop(seq)
        self.ages_ms.append((time.perf_counter_ns() - snapshot["enqueue_ns"]) / 1e6)
        self.acked += 1

    def capture(self):
        token, frames = (
            self.original()
        )  # exact existing immutable-by-copy sampler frame; NO second state read
        if token.capture_sequence != self.sent or token.capture_sequence >= 4096:
            raise RuntimeError("Source sequence/board range")
        if self.reset_epoch is None:
            self.reset_epoch = token.reset_epoch
        if token.reset_epoch != self.reset_epoch:
            raise RuntimeError("Reset requires fresh mirror worker")
        if self.last_physics is not None and token.physics_step <= self.last_physics:
            raise RuntimeError("Duplicate source boundary")
        matrices = []
        for entry in self.entries:
            frame = frames[entry["group"]]
            plural = entry["type"] == "articulation"
            matrix = self.pose(
                frame["positions" if plural else "position"],
                frame["orientations" if plural else "orientation"],
            )
            matrices.append(matrix if plural else matrix[None])
        intrinsics = np.array(
            [
                [
                    float(frames["state/camera/" + r][k])
                    for k in ["focal_length", "horizontal_aperture", "vertical_aperture"]
                ]
                for r in ROLES
            ]
        )
        if self.intrinsics is None:
            self.intrinsics = intrinsics.copy()
        if not np.array_equal(self.intrinsics, intrinsics):
            raise RuntimeError("Changing camera intrinsics unsupported")
        payload = dict(
            source_id=token.capture_sequence,
            reset_epoch=token.reset_epoch,
            physics_step=token.physics_step,
            state_generation=token.state_generation,
            snapshot_id=token.scene_state_snapshot_id,
            snapshot_sha256=token.scene_state_snapshot_sha256,
            sim_time_s=float(frames["meta/time"]["sim_time"]),
            source_wall_ns=int(float(frames["meta/time"]["wall_time"]) * 1e9),
            matrix_bytes=np.concatenate(matrices).astype("<f8").tobytes(),
            intrinsics=intrinsics.tolist(),
            enqueue_ns=time.perf_counter_ns(),
        )
        started = time.perf_counter_ns()
        while self.conn.poll():
            self._ack(self._receive())
        while len(self.pending) >= self.capacity:
            self._ack(self._receive())
        self.blocked_ms += (time.perf_counter_ns() - started) / 1e6
        self.pending[token.capture_sequence] = payload
        self.conn.send(payload)
        self.sent += 1
        self.last_physics = token.physics_step
        self.max_pending = max(self.max_pending, len(self.pending))
        return token, frames

    def restore(self):
        if self.was_owned:
            self.record._capture_new_observation = self.previous
        else:
            vars(self.record).pop("_capture_new_observation", None)

    def finish(self):
        if self.closed:
            return getattr(self, "receipt", dict(dataset_admissible=False, aborted=True))
        self.restore()
        started = time.perf_counter_ns()
        try:
            while self.pending:
                self._ack(self._receive())
            self.conn.send({"kind": "stop"})
            message = self._receive()
            if message.get("kind") != "done":
                raise RuntimeError(f"Unexpected drain reply: {message}")
            if self.proc.wait(timeout=30):
                raise RuntimeError("Mirror subprocess failed")
            self.receipt = dict(
                dataset_admissible=False,
                captures=self.sent,
                acked=self.acked,
                max_pending=self.max_pending,
                backpressure_ms=self.blocked_ms,
                drain_ms=(time.perf_counter_ns() - started) / 1e6,
                ack_age_p95_ms=float(np.percentile(self.ages_ms, 95)) if self.ages_ms else None,
                worker=message["receipt"],
                excluded_dynamic_bodies=self.metadata["excluded_dynamic_bodies"],
                ack_semantics="worker consumed snapshot and submitted3GPUframes; encoded completion verified at final drain",
            )
            (self.output / "producer.json").write_text(json.dumps(self.receipt, indent=2) + "\n")
            if self.metadata["witness"] and not message["receipt"]["passed"]:
                raise RuntimeError("Live mirror optical verification failed; inspect worker.json")
            return self.receipt
        finally:
            self.abort()

    def abort(self):
        self.restore()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.conn:
            self.conn.close()
        if self.log:
            self.log.close()
        self.closed = True
