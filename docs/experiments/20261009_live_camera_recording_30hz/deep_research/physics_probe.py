"""Opt-in, source-guarded PIPER physics probes. Importing runs no Isaac code.

Load with importlib.util.spec_from_file_location, then install(env, variant=...).
Valid variants: baseline, implicit-once, lazy-acceleration, implicit-lazy.
Call handle.restore() before disposing env. No SDK file is modified.
NOT a qualified recorder; all outputs must carry dataset_admissible=False.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST = Path("/tmp/live30-deep-physics.preimages.json")


def verify_preimages():
    expected = json.loads(MANIFEST.read_text())
    for name, digest in expected["sha256"].items():
        actual = hashlib.sha256(Path(name).read_bytes()).hexdigest()
        if actual != digest:
            raise RuntimeError(f"Probe preimage changed: {name}: {actual} != {digest}")
    return expected


class Handle:
    def __init__(self, env, variant):
        self.env, self.variant = env, variant
        self.saved = []
        self.active = False
        self.counts = {}
        self.stats = dict(groups=0, full_writes=0, cached_submits=0, lazy_updates=0)
        self.restored = False

    def patch(self, obj, name, value):
        self.saved.append((obj, name, name in vars(obj), vars(obj).get(name)))
        setattr(obj, name, value)

    def restore(self):
        if self.active:
            raise RuntimeError("Cannot restore inside an active physics group")
        if self.restored:
            return
        for obj, name, owned, old in reversed(self.saved):
            if owned:
                setattr(obj, name, old)
            else:
                delattr(obj, name)
        self.restored = True

    def receipt(self):
        return dict(
            variant=self.variant,
            dataset_admissible=False,
            physics_dt_unchanged=True,
            per_substep_submit_preserved=True,
            acceleration_semantics=(
                "read-interval finite difference" if "lazy" in self.variant else "unchanged"
            ),
            effort_telemetry_semantics=(
                "computed once/control" if "implicit" in self.variant else "unchanged"
            ),
            **self.stats,
        )


def _guard(robot):
    collection = robot.actuators
    if collection._control.native_actuator_path_active:
        raise RuntimeError("Native/Newton actuators forbidden for implicit probe")
    if collection._execution_actuators or collection._implicit_executor is None:
        raise RuntimeError("Requires exclusively exact upstream plain implicit actuators")
    if len(collection._implicit_executor.group_names) != len(collection):
        raise RuntimeError("Not all groups belong to implicit executor")
    if robot._instantaneous_wrench_composer.active or robot._permanent_wrench_composer.active:
        raise RuntimeError("External wrenches forbidden for implicit probe")
    if robot._fixed_tendon_target_dirty:
        raise RuntimeError("Dirty tendon command forbidden for implicit probe")


def install(env, *, variant="baseline"):
    if variant not in {"baseline", "implicit-once", "lazy-acceleration", "implicit-lazy"}:
        raise ValueError(variant)
    verify_preimages()
    if len(env.robots) != 2 or env.render_substeps != 4:
        raise RuntimeError("Probe requires two PIPERs and FFFT")
    if abs(float(env.sim.cfg.dt) - 1.0 / 120.0) > 1e-12:
        raise RuntimeError("Probe requires unchanged 120 Hz physics")
    if not env.vr_runtime._validation_complete:
        raise RuntimeError("Install after canonical reset and native scene validation")
    handle = Handle(env, variant)
    implicit = "implicit" in variant
    lazy = "lazy" in variant
    original_advance = env._advance
    try:
        for robot in env.robots:
            if implicit:
                _guard(robot)
                original_write = robot.write_data_to_sim

                def write(_robot=robot, _original=original_write):
                    if not handle.active:
                        return _original()
                    _guard(_robot)
                    index = handle.counts[id(_robot)]
                    if index == 0:
                        _original()
                        handle.stats["full_writes"] += 1
                    else:
                        _robot.actuators.submit_commands()
                        handle.stats["cached_submits"] += 1
                    handle.counts[id(_robot)] += 1

                handle.patch(robot, "write_data_to_sim", write)
                command = robot.actuators.target_command
                # Intercept the public target API. Direct mutation of command tensor buffers
                # remains prohibited by the probe contract and cannot be detected cheaply.
                for name in (
                    "set_position_index",
                    "set_velocity_index",
                    "set_effort_index",
                    "set_position_mask",
                    "set_velocity_mask",
                    "set_effort_mask",
                ):
                    original_set = getattr(command, name)

                    def setter(*args, _original=original_set, **kwargs):
                        if handle.active:
                            raise RuntimeError("Target mutation inside cached control group")
                        return _original(*args, **kwargs)

                    handle.patch(command, name, setter)
            if lazy:
                data = robot.data
                original_update = data.update

                def update(dt, _data=data, _original=original_update):
                    if not handle.active:
                        return _original(dt)
                    # Exact upstream update() except eager joint_acc access. The property
                    # remains available and on access differences over its elapsed interval.
                    _data._sim_timestamp += dt
                    if _data._fk_timestamp >= 0.0:
                        _data._fk_timestamp = _data._sim_timestamp
                    handle.stats["lazy_updates"] += 1

                handle.patch(data, "update", update)

        def advance(repeat):
            if handle.active:
                raise RuntimeError("Nested _advance not supported")
            # Settling/reset/one-off forward remain fully canonical.
            if repeat != 4 or env._render_substep != 0 or not env.vr_runtime._validation_complete:
                return original_advance(repeat)
            handle.active = True
            handle.counts = {id(robot): 0 for robot in env.robots}
            before = env.sim.get_physics_step_count()
            try:
                result = original_advance(repeat)
                if env.sim.get_physics_step_count() - before != 4:
                    raise RuntimeError("Native physics count no longer four/control")
                if implicit and any(n != 4 for n in handle.counts.values()):
                    raise RuntimeError("Unexpected articulation write cadence")
                handle.stats["groups"] += 1
                return result
            finally:
                handle.active = False

        handle.patch(env, "_advance", advance)
    except BaseException:
        handle.restore()
        raise
    return handle
