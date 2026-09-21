"""Bounded selectors over pinned native settings; no canonical source writes."""
import hashlib
import json
import os
import time
from pathlib import Path


def install(env, args):
    import carb.settings
    import omni.kit.app
    candidate = os.environ['VR_BAKEOFF_CANDIDATE']
    out = Path(os.environ['VR_BAKEOFF_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    settings = carb.settings.get_settings()
    from isaac_s2_performance import S2PerformanceLogger
    counts={'renders':0,'updates':0}
    original_render=env.sim.render
    def render(*a,**kw):
        start=time.perf_counter_ns()
        try:return original_render(*a,**kw)
        finally:
            counts['renders']+=1
            logger=getattr(env,'performance_logger',None)
            if logger:logger.add_nested('render_app',time.perf_counter_ns()-start)
    env.sim.render=render
    begin=S2PerformanceLogger.begin_step;end=S2PerformanceLogger.end_step
    physics_before=env.sim.get_physics_step_count()
    first_step=True
    def begin_step(log):
        nonlocal physics_before,first_step
        if first_step:
            first_step=False
            # XR profile settings persist in Kit's portable root. Declare the
            # baseline each process so a preceding E06 cannot contaminate A0/D/J.
            try:
                from omni.kit.xr.core import XRSettings
                XRSettings.get_singleton().set_setting('profile/persistent/render/resolutionMultiplier',{'E08':.8,'E06':.6,'LIVE-MIN60-NONTILED':.4,'LIVE-MIN60-DEFERRED':.4}.get(candidate,1.0))
            except ModuleNotFoundError:
                pass
            if candidate in ('E08','E06'):
                from omni.kit.xr.core import XRSettings
                XRSettings.get_singleton().set_setting('profile/persistent/render/resolutionMultiplier',{'E08':.8,'E06':.6}[candidate])
            elif candidate in ('D-desktop-off','B1-FULL-OFFLINE-D'):
                from omni.kit.viewport.utility import get_active_viewport
                get_active_viewport().updates_enabled=False
            elif candidate in ('F-minimal','LIVE-MIN60-NONTILED','LIVE-MIN60-DEFERRED'):
                settings.set('/rtx/rendermode','MinimalRendering');settings.set('/rtx/minimal/mode',2)
        counts.update(renders=0,updates=0)
        physics_before=env.sim.get_physics_step_count()
        return begin(log)
    def end_step(log,number,**state):
        result=end(log,number,**state)
        sample=dict(tick=number,**counts,physics_delta=env.sim.get_physics_step_count()-physics_before)
        if number%100==0:
            import resource
            usage=resource.getrusage(resource.RUSAGE_SELF)
            sample['process']=dict(wall_ns=time.monotonic_ns(),user_s=usage.ru_utime,
                                   system_s=usage.ru_stime,max_rss_kib=usage.ru_maxrss)
            try:
                from omni.kit.xr.core import XRCore,XRSettings
                xr=XRSettings.get_singleton();core=XRCore.get_singleton()
                sample['xr']=dict(enabled=core.is_xr_enabled(),display=core.is_xr_display_enabled(),
                    profile=core.get_current_profile_name(),resolution=xr.get_setting('status/renderResolution'),
                    scale=xr.get_setting('profile/persistent/render/resolutionMultiplier'))
            except ModuleNotFoundError:
                sample['xr']=dict(enabled=False,extension_loaded=False)
        if number==100 and candidate in ('F-minimal','A0'):
            import numpy as np
            images=env.camera.capture.freeze()
            np.savez(out/'validation_100.npz',**{k:v for k,v in images.items() if 'images' in k})
        with (out/'experiment_samples.jsonl').open('a') as stream:stream.write(json.dumps(sample,default=str)+'\n')
        if number==args.s2_max_control_steps and os.environ.get('VR_BAKEOFF_PROFILE_PASSES')=='1':
            from pass_cost import sample as sample_cost
            sample_cost(env,out)
        return result
    S2PerformanceLogger.begin_step=begin_step;S2PerformanceLogger.end_step=end_step
    if candidate == 'J60':
        previous = env.sim.step
        count = 0
        def step(*a, **kw):
            nonlocal count
            count += 1
            # Preserve final render even for 25-step reset boundaries.
            kw['render'] = count % 2 == 0 or count == 25
            return previous(*a, **kw)
        env.sim.step = step
        advance = env._advance
        def bounded(repeat):
            nonlocal count
            count = 0
            return advance(repeat)
        env._advance = bounded
    elif candidate.startswith('E'):
        from omni.kit.xr.core import XRSettings
        scale = {'E08': .8, 'E06': .6}[candidate]
        XRSettings.get_singleton().set_setting('profile/persistent/render/resolutionMultiplier', scale)
    elif candidate in ('F-minimal','LIVE-MIN60-NONTILED','LIVE-MIN60-DEFERRED'):
        settings.set('/rtx/rendermode', 'MinimalRendering')
        settings.set('/rtx/minimal/mode', 2)
    elif candidate in ('D-desktop-off','B1-FULL-OFFLINE-D'):
        from omni.kit.viewport.utility import get_active_viewport
        get_active_viewport().updates_enabled = False
    elif candidate not in ('A0', 'B1-capture', 'B1-cost', 'B1-FULL-OFFLINE', 'B1-FULL-OFFLINE-D', 'C1-640', 'C1-320', 'C2-320', 'C2-256', 'G-tiled640', 'G-assay', 'H-cpu', 'H-cpu-capture', 'render-assay', 'phase'):
        raise ValueError(candidate)
    updates = []
    def updated(event):
        updates.append(time.monotonic_ns());counts['updates']+=1
    subscription = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(updated)
    env._bakeoff_subscription = subscription
    manifest = dict(candidate=candidate, argv=__import__('sys').argv,
                    physics_dt=env.sim.cfg.dt, device=env.sim.device, shaders=settings.get('/rtx/rendermode'),
                    source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in Path(__file__).parent.glob('*.py')})
    (out/'variant.json').write_text(json.dumps(manifest, indent=2))
    import atexit
    atexit.register(lambda: (out/'kit_updates.json').write_text(json.dumps(updates)))
