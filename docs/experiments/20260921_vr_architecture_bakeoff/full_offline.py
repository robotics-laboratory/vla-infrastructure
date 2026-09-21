"""Maximal live sensor/panel suppression, plus auditable native state context."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def install(env,out):
    from state_probe import host
    from pxr import UsdUtils
    from omni.kit.viewport.utility import get_active_viewport
    out=Path(out);armed=False;violations=[]
    rig=env.camera;runtime=env.vr_runtime
    cameras=rig.capture.cameras
    run_id=str(uuid4())
    snapshot=out/'stage_snapshot.usd'
    layers,assets,unresolved=UsdUtils.ComputeAllDependencies(str(snapshot))
    dependencies={}
    for name in sorted(set([l.realPath for l in layers]+[str(a) for a in assets])):
        path=Path(name)
        dependencies[name]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    manifest=dict(candidate=os.environ['VR_BAKEOFF_CANDIDATE'],run_id=run_id,
        stage_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        task_profile=runtime.profile,runtime_config=runtime.config,
        camera_roles=list(cameras),camera_resolution=[640,480],
        camera_attributes={role:{str(a.GetName()):str(a.Get()) for a in env.sim.stage.GetPrimAtPath(c._view.prim_paths[0]).GetAttributes()}
                           for role,c in cameras.items()},
        dependencies=dependencies,unresolved_assets=[str(a) for a in unresolved],
        live_boundary='after native scene/reset bootstrap, before XR device context entry',
        bootstrap_images='native startup validation only; no images after live boundary',
        mutable_visual_attributes=['/World/RobosynDemo/Backdrop.visibility'],
        dataset_admissible=False,qualification='complete D0 snapshot transaction and task outcome not qualified')
    (out/'full_offline_manifest.json').write_text(json.dumps(manifest,indent=2,default=str))
    # Existing scene bootstrap remains a separate, unmeasured initialization.
    # Do not create even hidden SceneUI panels for this distinct candidate.
    runtime._prebind_camera_panels=lambda:None
    runtime.hud_on_start=False
    original_open=runtime.open
    initial_frames={}
    def opened(current):
        nonlocal armed,initial_frames
        original_open(current)
        for camera in cameras.values():
            camera._render_data.render_product.hydra_texture.updates_enabled=False
            for annotator in camera._render_data.annotators.values():annotator.detach()
        initial_frames.update({r:int(c.frame.torch.reshape(-1)[0].item()) for r,c in cameras.items()})
        rig.capture.invalidate();rig.capture_boundary=lambda current:None
        armed=True
    runtime.open=opened
    for role,camera in cameras.items():
        original=camera._update_buffers_impl
        def guarded(*a,_original=original,_role=role,**kw):
            if armed:
                violations.append('camera extraction: '+_role)
                raise RuntimeError('FULL-OFFLINE forbids live image extraction: '+_role)
            return _original(*a,**kw)
        camera._update_buffers_impl=guarded
    original_freeze=rig.capture.freeze
    def freeze(*a,**kw):
        if armed:
            violations.append('RGB freeze/copy')
            raise RuntimeError('FULL-OFFLINE forbids live RGB copies')
        return original_freeze(*a,**kw)
    rig.capture.freeze=freeze
    def enrich(tick):
        if not armed:raise RuntimeError('FULL-OFFLINE live boundary not armed')
        if runtime._feed_bound or runtime.display_visible:raise RuntimeError('FULL-OFFLINE preview bound/visible')
        frames={r:int(c.frame.torch.reshape(-1)[0].item()) for r,c in cameras.items()}
        if frames!=initial_frames:raise RuntimeError('FULL-OFFLINE camera frames advanced')
        if any(c._render_data.render_product.hydra_texture.updates_enabled for c in cameras.values()):
            raise RuntimeError('FULL-OFFLINE camera product enabled')
        if os.environ.get('VR_BAKEOFF_VERIFY_XR_DISPLAY')=='1':
            # Functional-only display probe: no extra pump or canonical camera access.
            if tick in (50,100):runtime._set_backdrop_visibility(tick==100)
            if tick in (60,110):
                from omni.kit.xr.core import XRCore
                XRCore.get_singleton().schedule_capture_display_frame(str(out/f'xr_display_{tick}'))
        if tick%100==0:
            viewport=get_active_viewport()
            (out/'full_offline_live_checks.json').write_text(json.dumps(dict(
                tick=tick,frames_start=initial_frames,frames_end=frames,all_products_disabled=True,
                annotators_detached=True,preview_bound=False,preview_visible=False,
                image_activity_violations=violations,viewport_camera=str(viewport.camera_path),
                viewport_updates=viewport.updates_enabled),indent=2))
        return dict(run_id=run_id,stage_sha256=manifest['stage_sha256'],
            task=dict(profile=runtime.profile,outcome=None,outcome_status='not_evaluated'),
            backdrop_visible=runtime._backdrop_visible,
            articulation_joint_positions=[host(r.data.joint_pos).tolist() for r in env.robots],
            articulation_joint_velocities=[host(r.data.joint_vel).tolist() for r in env.robots],
            articulation_root_poses=[host(r.data.root_pose_w).tolist() for r in env.robots],
            object_velocities=[host(a.data.root_vel_w).tolist() for a in runtime.dynamic_assets])
    return enrich
