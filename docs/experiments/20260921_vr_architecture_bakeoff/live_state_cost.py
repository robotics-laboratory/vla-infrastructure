"""State-only cost prototype. Explicitly excludes D0 admission and camera QA.

Reuse the exact S2 control loop; replace only its live-image guards. This measures
cost with real IK/physics/XR, but is NOT a qualified transaction/episode writer.
"""
from dataclasses import asdict
import inspect
import json
import os
from pathlib import Path
import time
import textwrap


def run(original, env, args, app):
    import omni.kit.app
    from state_probe import plain
    from isaac_s1_runtime import jsonable
    from isaac_s2_performance import S2PerformanceLogger
    import isaac_s2_runtime as runtime
    omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate(
        'isaacsim.replicator.episode_recorder', True)
    from isaacsim.core.experimental.utils.backend import use_backend
    from isaacsim.replicator.episode_recorder import (
        ArticulationRecordable, RigidBodyRecordable, CameraRecordable, export_stage_snapshot)
    out=Path(os.environ['VR_BAKEOFF_OUTPUT'])
    candidate=os.environ['VR_BAKEOFF_CANDIDATE']
    preview_spec={'C1-640':(1,640,480),'C1-320':(1,320,240),
                  'C2-320':(3,320,240),'C2-256':(3,256,192),
                  'G-tiled640':(3,640,480)}.get(candidate)
    records=[ArticulationRecordable(group=side,prim_path='/World/'+side+'Piper') for side in ('Left','Right')]
    records += [RigidBodyRecordable(group='object'+str(i),prim_path=a.cfg.prim_path)
                for i,a in enumerate(env.vr_runtime.dynamic_assets)]
    records += [CameraRecordable(group=role,prim_path=c._view.prim_paths[0],resolution=(640,480))
                for role,c in env.camera.capture.cameras.items()]
    for record in records:record.on_session_open(env.sim.stage)
    export_stage_snapshot(str(out))
    (out/'recordables.json').write_text(json.dumps([r.to_manifest() for r in records],indent=2))
    enrich=None
    if candidate.startswith('B1-FULL-OFFLINE'):
        from full_offline import install as install_full
        enrich=install_full(env,out)
    source=inspect.getsource(original)
    first=source.index('                camera = camera_guard.sample(env)')
    last=source.index('                if performance is not None:',first)
    source=source[:first]+'''                camera = {"valid": False, "strictly_advanced": False,
                          "disabled_for_state_only_cost": True}
'''+source[last:]
    for old,new in [
        ('and camera_valid_frames == control_steps','and True  # Explicitly no live dataset images'),
        ('and (not diagnostic or camera_advanced_frames == control_steps)','and True'),
        ('"gate": "NONE_EXPERIMENTAL" if experimental else "S2"','"gate": "NONE_STATE_COST_UNQUALIFIED"')]:
        assert source.count(old)==1,old
        source=source.replace(old,new)
    source=source.replace('"runtime_smoke_passed_physical_human_gate_required"','"state_cost_completed_D0_UNQUALIFIED"')
    (out/'executed_control_loop.py').write_text(source)
    space=dict(original.__globals__);exec(compile(source,str(out/'executed_control_loop.py'),'exec'),space)
    textures=[c._render_data.render_product.hydra_texture for c in env.camera.capture.cameras.values()]
    boundary=env.camera.capture_boundary
    reset=env.reset
    # Reuse native robot/object reset verbatim, omitting only sensor reset and
    # image-return/validation after startup. Never re-enable inactive products.
    reset_source=textwrap.dedent(inspect.getsource(reset))
    reset_source=reset_source.replace('self.camera.reset()',
        'self.camera.reset_epoch += 1\n    self.camera.capture.invalidate()')
    reset_source=reset_source.replace('self.camera.capture.latest(require_eligible=False)','pass')
    reset_source=reset_source.replace('return self.observation()',
        'return {"observation.state": np.asarray(self.capture_measured_state()[1])}')
    (out/'executed_reset.py').write_text(reset_source)
    reset_space=dict(reset.__globals__)
    exec(compile(reset_source,str(out/'executed_reset.py'),'exec'),reset_space)
    first_reset=True
    def reset_with_cameras(*a,**kw):
        nonlocal first_reset
        if first_reset:
            first_reset=False
            env.camera.capture_boundary=boundary
            return reset(*a,**kw)
        return reset_space['reset'](env,*a,**kw)
    env.reset=reset_with_cameras
    # Native after_reset refreshes disabled sensor buffers for panels. Preview
    # products remain alive and render the reset world on the normal next pump.
    env.vr_runtime.after_reset=lambda:env.vr_runtime._set_backdrop_visibility(env.vr_runtime._backdrop_visible)
    begin=S2PerformanceLogger.begin_step
    preview=None
    preview_rows=[]
    def begin_step(log):
        nonlocal preview
        result=begin(log)
        for texture in textures:texture.updates_enabled=False
        env.camera.capture.invalidate()
        env.camera.capture_boundary=lambda current:None
        if preview_spec and preview is None:
            import omni.replicator.core as rep
            count,width,height=preview_spec
            paths=[c._view.prim_paths[0] for c in env.camera.capture.cameras.values()]
            product=rep.create.render_product_tiled(cameras=paths if count==3 else paths[2:],
                    tile_resolution=(width,height),force_new=True,name='OperatorPreviewOnly')
            ann=rep.AnnotatorRegistry.get_annotator('rgb');ann.attach(product)
            preview=(product,ann)
            manager=env.vr_runtime._feed_session._manager
            if manager:
                manager.update=lambda *a,**kw:None
            env.vr_runtime._set_display(True)
        elif not preview_spec:
            env.vr_runtime._set_display(False)
        return result
    S2PerformanceLogger.begin_step=begin_step
    if not preview_spec:env.vr_runtime.consume_display_button=lambda *a,**kw:None
    args.demo_display_toggle_smoke=False
    end=S2PerformanceLogger.end_step
    def end_step(log,number,**state):
        if preview:
            import numpy as np
            import torch
            count,width,height=preview_spec
            data=preview[1].get_data()
            if isinstance(data,dict):data=data['data']
            image=np.asarray(data)
            shape=(height,width,4) if count==1 else (height*2,width*2,4)
            valid=image.shape==shape
            if not valid and number>30:raise RuntimeError(f'Operator preview missing: {image.shape} != {shape}')
            if valid:
                manager=env.vr_runtime._feed_session._manager
                if manager and env.vr_runtime.display_visible:
                    for i,feed in enumerate(manager._feeds):
                        if count==1 and feed.cfg.camera_name!='demo_scene':
                            env.vr_runtime.preview_isolation.release_panel(feed.panel)
                            feed.panel._container.hide();continue
                        tile=image if count==1 else image[(i//2)*height:(i//2+1)*height,(i%2)*width:(i%2+1)*width]
                        feed.panel.upload(torch.from_numpy(tile.copy()))
                if number in (30,100):np.save(out/f'preview_{number}.npy',image)
            preview_rows.append(dict(tick=number,valid=valid,shape=list(image.shape),
                                     visible=env.vr_runtime.display_visible,host_ns=time.monotonic_ns()))
            if number%100==0:(out/'preview_frames.json').write_text(json.dumps(preview_rows))
        return end(log,number,**state)
    S2PerformanceLogger.end_step=end_step
    solve=runtime._BimanualDifferentialIk.solve
    serial=0
    def observed_solve(ik,*a,**kw):
        nonlocal serial
        start=time.perf_counter_ns();serial+=1
        physics,state=env.capture_measured_state()
        with use_backend('fabric'):snapshot={r.group:plain(r.sample()) for r in records}
        xr=getattr(ik.device,'xr_input',None)
        result=solve(ik,*a,**kw)
        row=dict(tick=serial,reset_epoch=env.camera.reset_epoch,physics_step=physics,state=state,
                 snapshot=snapshot,action=result.dataset_action.tolist(),native_preclip=result.native_preclip,
                 native_command=result.native_clipped,processor_identity=result.processor_identity,
                 intent=jsonable(asdict(result.cartesian_intent)),xr=jsonable(asdict(xr)) if xr else None,
                 dataset_admissible=False,reason='Diagnostic cost probe; snapshot transaction adapter not qualified')
        if enrich:row.update(enrich(serial))
        with (out/'state_action.jsonl').open('a') as stream:
            stream.write(json.dumps(row,separators=(',',':'))+'\n')
        log=getattr(env,'performance_logger',None)
        if log:log.add_nested('state_snapshot_and_ik',time.perf_counter_ns()-start)
        return result
    runtime._BimanualDifferentialIk.solve=observed_solve
    return space['run_s2'](env,args,app)
