"""Experimental process-local Fabric gating; native gating/catch-up remains unqualified."""

import hashlib
from pathlib import Path

LAB = Path("/data/vla-infrastructure/IsaacLab/source")
EXT = Path(
    "/data/vla-infrastructure/isaac61_production/env/lib/python3.12/site-packages/isaacsim/extscache/omni.physx.fabric-110.3.2+110.3.0.lx64.r.cp312.u7f4"
)
GUARDS = {
    LAB
    / "isaaclab/isaaclab/sim/simulation_context.py": "819536a201b525774b4bc04d6bd9a9e3fc11397961b4881e9083eb4502ee958a",
    LAB
    / "isaaclab_physx/isaaclab_physx/physics/physx_manager.py": "79852394dafa48aeb5e9cdb39072dde27c9ab35f6b587a17ce931318ab44fd4a",
    EXT
    / "omni/physxfabric/bindings/_physxFabric.cpython-312-x86_64-linux-gnu.so": "ede92d7eb3328583ff6c2be2a313b18bea91e1d77fc54eeee968ba6af24354d1",
    EXT
    / "config/python_api.md": "61622abbcef5abac289141bcdb7322148c76a8e7f32e04a031ff1dc9b7f23f7c",
    EXT
    / "omni/physxfabric/scripts/settings.py": "ff4b9efdd259833c3f232a1664da1ea36f38148b0d4c73dbcbda4a9f34c5c2ef",
}


def install(env):
    import carb.settings
    from isaaclab.sim import SimulationContext

    assert isinstance(env.sim, SimulationContext)
    for path, digest in GUARDS.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, str(path)
    assert abs(env.sim.cfg.dt - 1 / 120) < 1e-12 and env.render_substeps == 4
    assert env.sim.is_rendering and env.sim.cfg.use_fabric
    assert env.sim.physics_manager.__module__.startswith("isaaclab_physx.")
    settings, key = carb.settings.get_settings(), "/physics/fabricEnabled"
    previous = settings.get_as_bool(key)
    assert previous is True
    old_advance, old_step = env._advance, env.sim.step
    absent = object()
    saved = [
        (env, "_advance", env.__dict__.get("_advance", absent)),
        (env.sim, "step", env.sim.__dict__.get("step", absent)),
    ]
    active, index = False, 0
    receipt = {
        "groups": 0,
        "disabled_steps": 0,
        "enabled_boundary_steps": 0,
        "physics_dt": 1 / 120,
        "repeat": 4,
        "source_guards": {str(k): v for k, v in GUARDS.items()},
    }

    def step(render=True):
        nonlocal index
        if not active:
            return old_step(render=render)
        assert index < 4 and render == (index == 3), (index, render)
        settings.set_bool(key, index == 3)
        try:
            result = old_step(render=render)
            receipt["enabled_boundary_steps" if index == 3 else "disabled_steps"] += 1
            index += 1
            return result
        finally:
            settings.set_bool(key, previous)

    def advance(repeat):
        nonlocal active, index
        if repeat != 4:
            return old_advance(repeat)
        assert not active and env._render_substep == 0
        start = env.sim.get_physics_step_count()
        active, index = True, 0
        try:
            result = old_advance(repeat)
            assert index == 4 and env.sim.get_physics_step_count() == start + 4
            assert env._render_substep == 0 and settings.get_as_bool(key) is True
            receipt["groups"] += 1
            return result
        finally:
            active = False
            settings.set_bool(key, previous)

    def restore():
        assert not active
        settings.set_bool(key, previous)
        for obj, attr, value in reversed(saved):
            if value is absent:
                delattr(obj, attr)
            else:
                setattr(obj, attr, value)

    env.sim.step, env._advance = step, advance
    return receipt, restore
