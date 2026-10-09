"""Opt-in diagnostic glue. Import is CPU-only; constructors require live Kit.

No sim.step/render/forward, robot.data writes, or global SimulationManager overrides.
The caller owns external snapshot identity, admission, recorder and XR lifecycle.
"""

from __future__ import annotations

import threading
import time
import numpy as np


class SourceClock:
    """Override one sim instance getter while retaining its native-counter guard.

    install only after builder startup. commit only after a completed worker reply.
    Reset is explicit; do not infer reset from decreasing step count.
    """

    def __init__(self, sim, *, epoch: int, physics_step: int, dt=1.0 / 120.0):
        if epoch < 0 or physics_step < 0 or dt <= 0:
            raise ValueError("invalid source clock")
        self.sim, self.dt = sim, float(dt)
        self.epoch, self.physics_step = int(epoch), int(physics_step)
        self.wall_time = time.time()
        self._owner = threading.get_ident()
        self._had_override = "get_physics_step_count" in vars(sim)
        self._saved_override = vars(sim).get("get_physics_step_count")
        self._native_getter = sim.get_physics_step_count
        self._native_start = int(self._native_getter())
        self._override = lambda: self.physics_step
        sim.get_physics_step_count = self._override

    def assert_native_frozen(self):
        if threading.get_ident() != self._owner:
            raise RuntimeError("source clock must be used on its Kit owner thread")
        if int(self._native_getter()) != self._native_start:
            raise RuntimeError("native SimContext stepped during external physics")

    def commit(self, *, epoch, physics_step, captured_wall_time):
        self.assert_native_frozen()
        if int(epoch) != self.epoch or int(physics_step) != self.physics_step + 4:
            raise RuntimeError("external completed step/epoch discontinuity")
        if not np.isfinite(captured_wall_time):
            raise ValueError("invalid capture wall time")
        self.physics_step = int(physics_step)
        self.wall_time = float(captured_wall_time)

    def reset(self, *, epoch, physics_step, captured_wall_time):
        self.assert_native_frozen()
        if int(epoch) <= self.epoch or int(physics_step) < 0:
            raise RuntimeError("reset requires a new source epoch")
        if not np.isfinite(captured_wall_time):
            raise ValueError("invalid reset capture wall time")
        self.epoch, self.physics_step = int(epoch), int(physics_step)
        self.wall_time = float(captured_wall_time)

    def sample(self):
        """Use as the external SimTimeRecordable.sample implementation."""
        self.assert_native_frozen()
        return dict(
            sim_time=self.physics_step * self.dt,
            physics_step=self.physics_step,
            wall_time=self.wall_time,
        )

    def close(self):
        # Restore only the instance override owned by this adapter.
        if vars(self.sim).get("get_physics_step_count") is not self._override:
            raise RuntimeError("source clock override replaced by another owner")
        if self._had_override:
            self.sim.get_physics_step_count = self._saved_override
        else:
            del self.sim.get_physics_step_count


class PassiveKitView:
    """Publish parent-before-child world poses, then pump one XR/UI update.

    poses are float32 [N,7] xyz+wxyz in EXACT caller path order. Optional
    native_counter should use SimulationManager.get_num_physics_steps; it
    detects engine callbacks not reflected in the frozen SimContext counter.
    This is presentation only. Never feed its readback to IK or recording.
    """

    def __init__(self, paths, *, native_counter=None):
        import carb
        import omni.kit.app
        from isaacsim.core.experimental.prims import XformPrim
        from isaacsim.core.experimental.utils.backend import use_backend

        if not paths or len(set(paths)) != len(paths):
            raise ValueError("paths must be nonempty and unique")
        self.paths = tuple(paths)
        self._order = sorted(range(len(paths)), key=lambda i: (paths[i].count("/"), paths[i]))
        ordered = [paths[i] for i in self._order]
        self._batch = XformPrim(ordered, resolve_paths=False, reset_xform_op_properties=False)
        if list(self._batch.paths) != ordered:
            raise RuntimeError("Kit pose path order differs")
        self._backend = use_backend
        self._settings = carb.settings.get_settings()
        self._app = omni.kit.app.get_app()
        self._owner = threading.get_ident()
        self._native_counter = native_counter

    def update(self, poses_wxyz, *, verify_readback=False):
        if threading.get_ident() != self._owner:
            raise RuntimeError("Kit presentation requires owner thread")
        poses = np.asarray(poses_wxyz, dtype=np.float32)
        if poses.shape != (len(self.paths), 7) or not np.isfinite(poses).all():
            raise ValueError("invalid external world poses")
        if not np.allclose(np.linalg.norm(poses[:, 3:], axis=1), 1, atol=1e-4, rtol=0):
            raise ValueError("nonunit quaternion")
        poses = np.ascontiguousarray(poses[self._order])
        key = "/app/player/playSimulations"
        previous = self._settings.get(key)
        if not isinstance(previous, bool):
            raise RuntimeError("playSimulations must exist as a boolean before passive pump")
        before = self._native_counter() if self._native_counter else None
        self._settings.set_bool(key, False)
        try:
            # Installed fabric setter explicitly falls back to USDRT hierarchy.
            with self._backend("fabric"):
                self._batch.set_world_poses(positions=poses[:, :3], orientations=poses[:, 3:])
            self._app.update()
            if self._native_counter and self._native_counter() != before:
                raise RuntimeError("native physics advanced inside passive app.update")
            if verify_readback:
                with self._backend("usdrt"):
                    p, q = self._batch.get_world_poses()
                p, q = p.numpy(), q.numpy()
                if not np.allclose(p, poses[:, :3], atol=1e-5, rtol=0):
                    raise RuntimeError("external position was overwritten during app.update")
                if not np.allclose(np.abs(np.sum(q * poses[:, 3:], axis=1)), 1, atol=1e-5, rtol=0):
                    raise RuntimeError("external orientation was overwritten during app.update")
        finally:
            self._settings.set_bool(key, previous)
