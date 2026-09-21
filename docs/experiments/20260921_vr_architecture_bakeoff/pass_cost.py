"""Post-control static render assay; no physics or configuration switching."""
import json
from pathlib import Path
import time


def sample(env,out):
    import carb.settings
    import omni.kit.app
    app=omni.kit.app.get_app()
    app.get_extension_manager().set_extension_enabled_immediate('omni.hydra.engine.stats',True)
    import omni.hydra.engine.stats as stats
    carb.settings.get_settings().set('/profiler/enabled',True)
    hd=stats.HydraEngineStats();rows=[];before=env.sim.get_physics_step_count()
    for i in range(150):
        start=time.perf_counter_ns();env.sim.render();elapsed=(time.perf_counter_ns()-start)/1e6
        if i>=50:rows.append(dict(render_host_ms=elapsed,gpu=hd.get_gpu_profiler_result()))
    assert env.sim.get_physics_step_count()==before
    (Path(out)/'pass_cost.json').write_text(json.dumps(dict(physics_step=before,warmup=50,samples=rows)))
