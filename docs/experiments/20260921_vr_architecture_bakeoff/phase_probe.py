"""Experiment-only native-pose versus USD-material image phase witness.

Recolors the existing gripper_base visual geometry and one existing
PhysX cube. No additional integration/render occurs inside a measured boundary.
This is a visual transform-path witness, not a trajectory or S1 qualification.
"""
import json
from pathlib import Path
import numpy as np


def qualify(env, out, set_marker):
    from pxr import UsdGeom, UsdShade, UsdPhysics, Sdf, Gf
    import torch
    from isaac_s1_runtime import quaternion_xyzw_to_matrix
    stage = env.sim.stage
    roles = env.camera.capture.cameras
    robot = env.robots[0]
    cube = env.vr_runtime.dynamic_assets[0]
    def host(value):
        value = getattr(value, 'torch', value)
        return value.detach().cpu().numpy().copy()
    def material(path, color):
        mat = UsdShade.Material.Define(stage, path)
        shader = UsdShade.Shader.Define(stage, path + '/Shader')
        shader.CreateIdAttr('UsdPreviewSurface')
        diffuse = tuple(min(1.0, float(value)) for value in color)
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*diffuse))
        emission = shader.CreateInput('emissiveColor', Sdf.ValueTypeNames.Color3f)
        emission.Set(Gf.Vec3f(*color))
        mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
        return mat, emission
    links = [p for p in stage.Traverse() if p.GetName() == 'gripper_base' and p.HasAPI(UsdPhysics.RigidBodyAPI) and str(p.GetPath()).startswith(robot.cfg.prim_path)]
    if len(links) != 1:
        raise RuntimeError('Cannot resolve unique robot gripper_base: '+str([str(p.GetPath()) for p in links]))
    link = links[0]
    visual = next(p for p in stage.Traverse() if p.GetName() == 'gripper_base' and p != link and p.GetPath().HasPrefix(link.GetPath()))
    bounds = UsdGeom.BBoxCache(0, [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    offset = np.asarray(bounds.ComputeRelativeBound(visual, link).ComputeCentroid(), dtype=float)
    mat, _ = material('/World/PhaseArticulationMaterial', (8,0,8))
    UsdShade.MaterialBindingAPI.Apply(visual).Bind(mat, UsdShade.Tokens.strongerThanDescendants)
    mat, _ = material('/World/PhaseCubeMaterial', (0,8,8))
    cube_prim = stage.GetPrimAtPath(cube.cfg.prim_path)
    UsdShade.MaterialBindingAPI.Apply(cube_prim).Bind(mat, UsdShade.Tokens.strongerThanDescendants)
    marker_inputs=[]
    for role,camera in roles.items():
        path=camera._view.prim_paths[0]
        for bit in range(6):
            shape=UsdGeom.Cube.Define(stage,path+'/PhaseBit'+str(bit))
            shape.CreateSizeAttr(1.)
            xf=UsdGeom.Xformable(shape)
            xf.AddTranslateOp().Set(Gf.Vec3d((bit-2.5)*.019,-.045,-.15))
            xf.AddScaleOp().Set(Gf.Vec3f(.015,.016,.001))
            mat,_=material(path+'/PhaseBit'+str(bit)+'/Mat',(1,1,1))
            UsdShade.MaterialBindingAPI.Apply(shape.GetPrim()).Bind(mat)
            marker_inputs.append((bit,UsdGeom.Imageable(shape.GetPrim())))
    initial_q = host(robot.data.joint_pos)
    initial_pose = host(cube.data.root_link_pose_w)
    history={}
    rows=[]
    reference_samples=[]
    max_lag = 2 if abs(float(env.sim.cfg.dt) - 1.0 / 60.0) < 1.0e-12 else 3
    def points():
        pose=host(robot.data.body_link_pose_w)[0,env.wrist_ids[0]]
        return {'articulation': (pose[:3]+quaternion_xyzw_to_matrix(pose[3:])@offset).tolist(),
                'rigid':host(cube.data.root_link_pose_w)[0,:3].tolist(),
                'joint_positions':host(robot.data.joint_pos).tolist()}
    def update(step):
        history[step-1]=points()
        # Coprime bounded sequences avoid the P versus P-2 ambiguity of a
        # short alternating witness while remaining deterministic.
        joint_phase = ((step * 17) % 97) / 96.0
        cube_phase = ((step * 29) % 101) / 100.0
        q=initial_q.copy();q[0,env.joint_ids[0][0]] += -.30 + .60 * joint_phase
        qt=torch.as_tensor(q,device=env.sim.device)
        robot.write_joint_position_to_sim_index(position=qt)
        robot.write_joint_velocity_to_sim_index(velocity=torch.zeros_like(qt))
        robot.actuators.target_command.set_position_index(value=qt)
        robot.write_data_to_sim()
        pose=initial_pose.copy();pose[0,:3]=[.65,-.12 + .24 * cube_phase,1.02]
        cube.write_root_pose_to_sim_index(root_pose=torch.as_tensor(pose,device=env.sim.device))
        cube.write_root_velocity_to_sim_index(root_velocity=torch.zeros((1,6),device=env.sim.device))
        for bit,imageable in marker_inputs:
            if step & (1 << bit):
                imageable.MakeVisible()
            else:
                imageable.MakeInvisible()
    def project(point,camera):
        pos=host(camera.data.pos_w)[0];q=host(camera.data.quat_w_opengl)[0]
        local=quaternion_xyzw_to_matrix(q).T@(np.asarray(point)-pos)
        k=host(camera.data.intrinsic_matrices)[0]
        return [float(k[0,0]*local[0]/-local[2]+k[0,2]),float(k[1,1]*-local[1]/-local[2]+k[1,2])]
    set_marker(update)
    try:
        # Five settling observations followed by 35 consecutive changing
        # accepted boundaries. This exceeds the LIVE-MIN60 minimum of 30.
        for tick in range(40):
            before=env.sim.render_generation
            env._advance(4)
            snap=env.latest_observation_capture();p=snap.producer.physics_step
            history[p]=points();frozen=env.camera.capture.freeze()
            row={'tick':tick,'physics':p,'render_delta':env.sim.render_generation-before,'views':{}}
            for role,camera in roles.items():
                rgb=frozen['observation.images.'+role]
                k=host(camera.data.intrinsic_matrices)[0]
                values=[]
                for bit in range(6):
                    u=int(round(k[0,0]*((bit-2.5)*.019)/.15+k[0,2]));v=int(round(k[1,1]*.045/.15+k[1,2]))
                    values.append(float(rgb[v-2:v+3,u-2:u+3].mean()))
                decoded=sum((v>200)*(1<<bit) for bit,v in enumerate(values))
                view={'usd_values':values,'usd_decoded':int(decoded),'usd_expected':p%64,'native':{}}
                # Bright static colors isolate geometry, independent of per-step material changes.
                arr=rgb.astype(float)
                masks={'articulation':(arr[:,:,0]>170)&(arr[:,:,2]>170)&(arr[:,:,1]<120),
                       'rigid':(arr[:,:,1]>170)&(arr[:,:,2]>170)&(arr[:,:,0]<120)}
                for kind,mask in masks.items():
                    ys,xs=np.where(mask)
                    center=[float(xs.mean()),float(ys.mean())] if len(xs)>5 else None
                    predicted={str(lag):project(history[p-lag][kind],camera) for lag in range(max_lag + 1)}
                    errors={lag:float(np.linalg.norm(np.asarray(xy)-center)) for lag,xy in predicted.items()} if center else {}
                    view['native'][kind]={'pixels':int(len(xs)),'observed_center':center,'predicted_centers':predicted,'errors_px':errors,'best_lag':min(errors,key=errors.get) if errors else None}
                row['views'][role]=view
                if role == 'scene' and tick >= 37:
                    reference_samples.append((tick, p, masks['articulation'].copy()))
                if tick in (8,9):
                    (out/f'phase-{tick}-{role}.ppm').write_bytes(b'P6\n640 480\n255\n'+rgb.tobytes())
            rows.append(row)
            (out/'phase.json').write_text(json.dumps({'method':'existing native PhysX cube + existing gripper_base mesh + USD material bits','articulation_visual':str(visual.GetPath()),'articulation_local_centroid':offset.tolist(),'history':history,'rows':rows,'limitations':['articulation measures existing gripper_base mesh, not all robot meshes','centroid versus projected center has perspective/occlusion bias; use separation and residuals','wrist camera current extrinsics can confound previous-state projections; scene camera is fixed']},indent=2))
        # Reference renders are explicitly outside every measured boundary.
        # Restore native articulation coordinates and never integrate actions/physics.
        references=[]
        reference_physics=env.sim.get_physics_step_count()
        camera=roles['scene']
        for tick, physics, measured_mask in reference_samples:
            for lag in range(max_lag + 1):
                q=torch.as_tensor(history[physics-lag]['joint_positions'],device=env.sim.device)
                robot.write_joint_position_to_sim_index(position=q)
                robot.write_joint_velocity_to_sim_index(velocity=torch.zeros_like(q))
                env.sim.forward()
                start_render=env.sim.render_generation
                for _ in range(4):
                    env.sim.render()
                camera.update(1./30.,force_recompute=True)
                rgb=host(camera.data.output['rgba'])[0,:,:,:3]
                mask=(rgb[:,:,0]>170)&(rgb[:,:,2]>170)&(rgb[:,:,1]<120)
                union=int((mask|measured_mask).sum())
                intersection=int((mask&measured_mask).sum())
                yy,xx=np.where(mask)
                my,mx=np.where(measured_mask)
                centroid_error=float(np.linalg.norm([xx.mean()-mx.mean(),yy.mean()-my.mean()])) if len(xx) and len(mx) else None
                references.append(dict(tick=tick, source_physics=physics, lag=lag,
                    native_joint_positions=history[physics-lag]['joint_positions'],
                    reference_physics_before=reference_physics,reference_physics_after=env.sim.get_physics_step_count(),
                    settling_renders=env.sim.render_generation-start_render,
                    iou=intersection/union if union else None,centroid_error_px=centroid_error,
                    reference_pixels=int(mask.sum()),measured_pixels=int(measured_mask.sum())))
                if tick==23 and lag in (0,1):
                    (out/f'phase-reference-{tick}-lag{lag}.ppm').write_bytes(b'P6\n640 480\n255\n'+rgb.tobytes())
                if env.sim.get_physics_step_count()!=reference_physics:
                    raise RuntimeError('Physics advanced during articulation image reference generation')
        (out/'phase-articulation-references.json').write_text(json.dumps(references,indent=2))
        summarize(out)
    finally:
        set_marker(None)


def install(env, args, out):
    """Invoke from an experiment import hook before canonical run_s2(env,args,app).

    Requires diagnostic mode (S2PerformanceLogger). Runs at the final measured
    control, while XR remains active. Canonical source/config files are untouched.
    """
    from isaac_s2_performance import S2PerformanceLogger
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    previous_end = S2PerformanceLogger.end_step
    previous_step = env.sim.step
    callback = None
    def set_marker(value):
        nonlocal callback
        callback = value
    def step(*a, **kw):
        if callback is not None:
            callback(env.sim.get_physics_step_count() + 1)
        return previous_step(*a, **kw)
    def end(log, number, **state):
        result = previous_end(log, number, **state)
        if number == args.s2_max_control_steps:
            env.sim.step = step
            try:
                qualify(env, out, set_marker)
            finally:
                env.sim.step = previous_step
                S2PerformanceLogger.end_step = previous_end
        return result
    S2PerformanceLogger.end_step = end


def summarize(out):
    """Bounded statistics only; verdict requires checking visibility and residuals."""
    from collections import Counter
    import statistics
    data = json.loads((out / 'phase.json').read_text())
    rows = data['rows'][5:]
    result = dict(checked_boundaries=len(rows), render_deltas=sorted(set(r['render_delta'] for r in rows)), roles={})
    for role in rows[0]['views']:
        views = [r['views'][role] for r in rows]
        native = {}
        for kind in ('rigid', 'articulation'):
            witnesses = [v['native'][kind] for v in views]
            lag_keys = sorted(witnesses[0]['predicted_centers'], key=int)
            errors = {lag: [v['errors_px'][lag] for v in witnesses if v['errors_px']] for lag in lag_keys}
            native[kind] = dict(best_lag_counts=dict(Counter(v['best_lag'] for v in witnesses)),
                                minimum_visible_pixels=min(v['pixels'] for v in witnesses),
                                mean_error_px={lag: statistics.mean(values) if values else None for lag, values in errors.items()},
                                maximum_error_px={lag: max(values) if values else None for lag, values in errors.items()})
        result['roles'][role] = dict(usd_lag_mod64=dict(Counter(str((v['usd_expected']-v['usd_decoded']) % 64) for v in views)), native=native)
    (out / 'phase-analysis.json').write_text(json.dumps(result, indent=2))
