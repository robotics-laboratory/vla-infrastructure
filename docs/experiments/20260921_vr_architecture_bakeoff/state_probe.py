"""Bounded state/replay feasibility assay, not an episode recorder or D1 source."""
import json
import os
import time
from pathlib import Path
import numpy as np


def plain(value):
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if hasattr(value, 'tolist'):
        return value.tolist()
    return value


def host(value):
    if hasattr(value, 'torch'):
        value = value.torch
    return value.detach().cpu().numpy()


def capture(env, args, app):
    import omni.kit.app
    import carb.settings
    omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate(
        'isaacsim.replicator.episode_recorder', True)
    from isaacsim.replicator.episode_recorder import (
        ArticulationRecordable, RigidBodyRecordable, CameraRecordable, export_stage_snapshot)
    from isaacsim.core.experimental.utils.backend import use_backend
    from isaac_s1_runtime import d0_action_to_native
    out = Path(os.environ['VR_BAKEOFF_OUTPUT'])
    cameras = env.camera.capture.cameras
    records = [ArticulationRecordable(group=side, prim_path='/World/'+side+'Piper')
               for side in ('Left', 'Right')]
    records += [RigidBodyRecordable(group='object'+str(i), prim_path=a.cfg.prim_path)
                for i, a in enumerate(env.vr_runtime.dynamic_assets)]
    records += [CameraRecordable(group=role, prim_path=c._view.prim_paths[0], resolution=(640,480))
                for role, c in cameras.items()]
    for record in records:
        record.on_session_open(env.sim.stage)
    export_stage_snapshot(str(out))
    (out/'recordables.json').write_text(json.dumps([r.to_manifest() for r in records], indent=2))
    rows = []
    for tick in range(120):
        target = env.home_d0.copy()
        target[[0,7]] += 12*np.sin(tick/13)
        target[[3,10]] += 7*np.cos(tick/11)
        target[[6,13]] += 20*np.sin(tick/17)
        native = d0_action_to_native(target)
        env._apply(native)
        env._advance(4)
        start = time.perf_counter()
        data = {}
        for backend in ('usd','usdrt','fabric'):
            try:
                with use_backend(backend):
                    data[backend] = {r.group:plain(r.sample()) for r in records}
            except Exception as exc:
                data[backend] = {'error':repr(exc)}
        row = dict(tick=tick, physics_step=env.sim.get_physics_step_count(),
                   state=list(env.capture_measured_state()[1]),
                   target=target.tolist(), native=[native.left_rad_m.tolist(),native.right_rad_m.tolist()],
                   joint_positions=[host(r.data.joint_pos).tolist() for r in env.robots],
                   body_names=[r.body_names for r in env.robots],
                   body_poses_xyzw=[host(r.data.body_link_pose_w).tolist() for r in env.robots],
                   objects=[host(a.data.root_pose_w).tolist() for a in env.vr_runtime.dynamic_assets],
                   snapshots=data, capture_ms=1000*(time.perf_counter()-start))
        rows.append(row)
        if tick in (20,40,60,80,100,119):
            images=env.camera.capture.freeze()
            np.savez(out/f'live_{tick}.npz', **{k:v for k,v in images.items() if 'images' in k})
    (out/'states.json').write_text(json.dumps(rows, separators=(',',':')))
    (out/'capture_result.json').write_text(json.dumps(dict(
        ticks=len(rows), fsd=carb.settings.get_settings().get('/app/useFabricSceneDelegate'),
        note='Deterministic native-target assay; no XR decisions, no causal transaction or D1 admission',
        mean_capture_ms=np.mean([r['capture_ms'] for r in rows]),
        json_bytes_per_tick=(out/'states.json').stat().st_size/len(rows)),indent=2))
    print('B1 bounded capture complete', flush=True)
    return 0
