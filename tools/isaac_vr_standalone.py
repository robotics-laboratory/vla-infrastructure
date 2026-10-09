"""Opt-in single-GPU diagnostic: one CPU physics owner, passive Kit XR view.

Keeps the current environment, native recorder and upstream IK. The inherited
socket has one concrete worker and two commands; it is not a simulator service.
No physical hardware is commanded. No SDK files or production selection change.
"""

from __future__ import annotations

import hashlib
import json
from multiprocessing.connection import Connection
import os
from pathlib import Path
import socket
import subprocess
import time

import numpy as np

from isaac_vr_standalone_ik import piper_ik_state
from isaac_vr_standalone_view import PassiveKitView, SourceClock


class StandaloneState:
    """Own source snapshots and scoped instance overrides, with explicit restore."""

    def __init__(self, env, output, *, python, timeout=60):
        self.env, self.output = env, Path(output)
        self.python, self.timeout = str(python), float(timeout)
        self.output.mkdir(parents=True, exist_ok=False)
        self.clock = SourceClock(
            env.sim,
            epoch=int(env.camera.reset_epoch),
            physics_step=int(env.sim.get_physics_step_count()),
        )
        self.offset = self.clock.physics_step
        self.conn = self.proc = self.log = None
        self.snapshot = self.resolver = self.view = None
        self.targets = None
        self.seq = -1
        self.failed = False
        self.closed = False
        self.saved = {}
        self.native_state_step = env._state_physics_step
        self.timings = []
        self.receipt = dict(
            schema="single_gpu_source_owner_v1",
            physical=False,
            dataset_admissible=False,
            controls=0,
            native_physics_frozen=False,
        )

    def pose_batch(self, paths):
        owner = self

        class Batch:
            def get_world_poses(self):
                if owner.failed:
                    raise RuntimeError("external physics owner failed closed")
                owner.clock.assert_native_frozen()
                if owner.snapshot is None:
                    raise RuntimeError("external snapshot is not ready")
                poses = owner.resolver.poses(paths, owner.snapshot["rigid_body_world_pose"])
                return poses[:, :3], poses[:, 3:]

        return Batch()

    def sample_time(self):
        return self.clock.sample()

    def _override(self, name, value):
        self.saved[name] = (name in vars(self.env), vars(self.env).get(name))
        setattr(self.env, name, value)

    def _receive(self):
        if not self.conn.poll(self.timeout):
            raise RuntimeError(f"physics reply timeout: worker={self.proc.poll()}")
        reply = self.conn.recv()
        if reply.get("op") == "error":
            raise RuntimeError(f"physics worker failed: {reply}")
        return reply

    def start(self, snapshot):
        from isaac_vr_standalone_scene import build_seed, SnapshotPoses
        from isaacsim.core.simulation_manager import SimulationManager

        seed = build_seed(self.env, Path(snapshot), self.output)
        self.seed = seed
        self.resolver = SnapshotPoses(Path(snapshot), seed["rigid_body_paths"])
        seed_path = self.output / "seed.json"
        seed_path.write_text(json.dumps(seed, indent=2) + "\n")
        parent, child = socket.socketpair()
        self.conn = Connection(parent.detach())
        self.log = (self.output / "worker.log").open("wb")
        worker = Path(__file__).with_name("isaac_vr_standalone_worker.py")
        self.receipt.update(
            worker_sha256=hashlib.sha256(worker.read_bytes()).hexdigest(),
            seed_sha256=hashlib.sha256(seed_path.read_bytes()).hexdigest(),
        )
        try:
            self.proc = subprocess.Popen(
                [
                    self.python,
                    str(worker),
                    "--fd",
                    str(child.fileno()),
                    "--seed",
                    str(seed_path),
                    "--receipt",
                    str(self.output / "worker.json"),
                ],
                pass_fds=(child.fileno(),),
                stdout=self.log,
                stderr=self.log,
                env={k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")},
            )
        finally:
            child.close()
        ready = self._receive()
        if ready.get("op") != "ready":
            raise RuntimeError(f"invalid physics startup: {ready}")
        self.properties = ready["dof_properties"]
        self._accept(ready["snapshot"], initial=True)
        self.receipt["initial_parity"] = self._initial_parity()
        paths = list(seed["rigid_body_paths"])
        paths += ["/World/LeftPiper", "/World/RightPiper"]
        paths += list(self.env.camera.camera_prim_paths.values())
        self.view = PassiveKitView(paths, native_counter=SimulationManager.get_num_physics_steps)
        self.view.update(
            self.resolver.poses(paths, self.snapshot["rigid_body_world_pose"]), verify_readback=True
        )
        self.clock.assert_native_frozen()
        self.targets = np.asarray(
            seed["initial"].get("position_target", seed["initial"]["q"]), np.float32
        ).copy()
        self._override("standalone_state", self)
        self._override("_apply", self.apply)
        self._override("_advance", self.advance)
        self._override("capture_measured_state", self.capture_measured_state)
        # Resetting the original Kit engine would silently fork the source clock.
        self._override("_reset_native", self.reject_reset)
        self.receipt["native_physics_frozen"] = True

    def _accept(self, snapshot, *, initial=False):
        expected = -1 if initial else self.seq + 1
        if snapshot["seq"] != expected or snapshot["physics_steps"] != 4 * (expected + 1):
            raise RuntimeError("nonconsecutive completed native snapshot")
        if not snapshot["fixed_base"]:
            raise RuntimeError("external articulation is not fixed base")
        for key, value in list(snapshot.items()):
            if isinstance(value, np.ndarray):
                if not np.isfinite(value).all():
                    raise RuntimeError(f"nonfinite source snapshot: {key}")
                snapshot[key] = value.copy()
                snapshot[key].setflags(write=False)
        if np.max(np.abs(snapshot["mimic_residual"])) > 2e-4:
            raise RuntimeError("imported native mimic constraints diverged")
        ik = piper_ik_state(
            q=snapshot["q"],
            link_poses_xyzw=snapshot["rigid_body_world_pose"][:24].reshape(2, 12, 7),
            com_poses_xyzw=snapshot["articulation_body_com_local_pose"],
            jacobian_com=snapshot["jacobian"],
            limits=self.properties["limits"],
            body_names=self.seed["body_names"],
            dof_names=self.seed["dof_names"],
            fixed_base=True,
        )
        self.snapshot, self.seq, self._ik = snapshot, expected, ik

    def _initial_parity(self):
        initial = self.seed["initial"]
        errors = {}
        for key in ("q", "dq", "root_pose", "rigid_body_world_pose"):
            if key in initial:
                errors[key] = float(
                    np.max(np.abs(self.snapshot[key] - np.asarray(initial[key], np.float32)))
                )
                if errors[key] > 3e-5:
                    raise RuntimeError(f"initial Kit/native state mismatch: {key}={errors[key]}")
        for arm, (robot, wrist_id, ids) in enumerate(
            zip(self.env.robots, self.env.wrist_ids, self.env.joint_ids, strict=True)
        ):
            row = wrist_id - 1 if robot.is_fixed_base else wrist_id
            cols = [i + robot.num_base_dofs for i in ids[:6]]
            reference = robot.data.body_link_jacobian_w.torch[:, row, :, cols].cpu().numpy()[0]
            error = float(np.max(np.abs(reference - self._ik["jacobian"][arm])))
            errors[f"jacobian_{arm}"] = error
            if error > 2e-4:
                raise RuntimeError(f"initial Kit/native TCP Jacobian mismatch: {error}")
        return errors

    def capture_measured_state(self):
        from isaac_s1_runtime import native_state_to_d0

        if self.failed:
            raise RuntimeError("external physics owner failed closed")
        self.clock.assert_native_frozen()
        q = self.snapshot["q"]
        native = [q[i, ids] for i, ids in enumerate(self.env.joint_ids)]
        return self.clock.physics_step, tuple(float(v) for v in native_state_to_d0(*native))

    def ik_state(self, arm):
        import torch

        if self.failed:
            raise RuntimeError("external physics owner failed closed")
        self.clock.assert_native_frozen()
        return {
            k: torch.as_tensor(v[arm].copy(), dtype=torch.float32, device=self.env.sim.device)
            if k == "limits"
            else torch.as_tensor(
                v[arm : arm + 1].copy(), dtype=torch.float32, device=self.env.sim.device
            )
            for k, v in self._ik.items()
        }

    def apply(self, targets):
        if self.failed:
            raise RuntimeError("external physics owner failed closed")
        self.clock.assert_native_frozen()
        result = self.targets.copy()
        for arm, (ids, values) in enumerate(
            zip(self.env.actuated_joint_ids, (targets.left_rad_m, targets.right_rad_m), strict=True)
        ):
            result[arm, ids] = self.env._with_mimics(values)
        if result.shape != (2, 9) or not np.isfinite(result).all():
            raise ValueError("invalid native command")
        self.targets = result

    def advance(self, repeat):
        if self.failed:
            raise RuntimeError("external physics owner failed closed")
        try:
            self._advance_completed(repeat)
        except BaseException:
            self.failed = True
            raise

    def _advance_completed(self, repeat):
        if repeat != 4:
            raise ValueError("standalone source requires one four-substep control boundary")
        self.clock.assert_native_frozen()
        started = time.perf_counter_ns()
        self.conn.send(dict(op="step", seq=self.seq + 1, native_targets=self.targets))
        reply = self._receive()
        received_monotonic_ns = time.monotonic_ns()
        received_wall_time = time.time()
        if reply.get("op") != "captured" or not np.array_equal(
            reply["native_targets"], self.targets
        ):
            raise RuntimeError("native completion/command acknowledgment differs")
        self._accept(reply["snapshot"])
        self.clock.commit(
            epoch=self.clock.epoch,
            physics_step=self.offset + self.snapshot["physics_steps"],
            captured_wall_time=received_wall_time,
            received_monotonic_ns=received_monotonic_ns,
        )
        self.env._state_physics_step = self.clock.physics_step
        captured = time.perf_counter_ns()
        poses = self.resolver.poses(self.view.paths, self.snapshot["rigid_body_world_pose"])
        self.view.update(poses, verify_readback=self.seq < 2 or self.seq % 120 == 0)
        self.clock.assert_native_frozen()
        self.timings.append(
            dict(
                seq=self.seq,
                physics_ipc_ns=captured - started,
                passive_view_ns=time.perf_counter_ns() - captured,
                **reply["timings_ns"],
            )
        )
        self.receipt["controls"] += 1

    def reject_reset(self, seed):
        raise RuntimeError(
            "experimental standalone reset requires closing and recreating this source owner"
        )

    def close(self):
        if self.closed:
            return
        self.closed = True
        errors = []
        if self.proc and self.proc.poll() is None:
            try:
                self.conn.send(dict(op="close"))
                self.receipt["tail"] = self._receive()
                if self.receipt["tail"] != dict(
                    op="closed", controls=self.seq + 1, physics_steps=4 * (self.seq + 1)
                ):
                    raise RuntimeError("physics terminal acknowledgment differs")
                if self.proc.wait(timeout=10) != 0:
                    raise RuntimeError("physics worker exited unsuccessfully")
            except Exception as exc:
                errors.append(repr(exc))
                if self.proc.poll() is None:
                    self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
        for name, (existed, previous) in self.saved.items():
            if existed:
                setattr(self.env, name, previous)
            else:
                vars(self.env).pop(name, None)
        self.env._state_physics_step = self.native_state_step
        if self.proc and self.proc.poll() not in (None, 0):
            errors.append(f"physics worker exit status {self.proc.poll()}")
        if self.conn:
            self.conn.close()
        if self.log:
            self.log.close()
        try:
            self.clock.close()
        except Exception as exc:
            errors.append(repr(exc))
        worker_receipt = self.output / "worker.json"
        if worker_receipt.exists():
            native_errors = json.loads(worker_receipt.read_text()).get("cleanup_errors", [])
            errors.extend(native_errors)
            self.receipt["worker_cleanup_errors"] = native_errors
        self.receipt.update(cleanup_errors=errors, timing_rows=len(self.timings))
        (self.output / "owner.json").write_text(json.dumps(self.receipt, indent=2) + "\n")
        (self.output / "timings.json").write_text(json.dumps(self.timings, indent=2) + "\n")
        if errors:
            raise RuntimeError(f"standalone cleanup failed: {errors}")
