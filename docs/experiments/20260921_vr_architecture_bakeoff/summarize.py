"""Summarize retained timings without dropping samples or clipping outliers."""
import argparse
import json
from pathlib import Path
import numpy as np


def distribution(values):
    x=np.asarray(values,dtype=float)
    if not len(x):return None
    mean=float(x.mean());std=float(x.std())
    return dict(n=len(x),mean_ms=mean,stddev_ms=std,cv=std/mean,
                **{f'p{str(q).replace(".","_")}_ms':float(np.percentile(x,q)) for q in (50,90,95,99,99.9)},
                max_ms=float(x.max()))


def summarize(directory):
    directory=Path(directory)
    launch=json.loads((directory/'launch.json').read_text())
    paths=[]
    for line in (directory/'launch.log').read_text(errors='replace').splitlines():
        if line.startswith('VR output: '):paths.append(Path(line.split(': ',1)[1]))
    result=dict(candidate=launch['candidate'],exit_code=launch.get('exit_code'),directory=str(directory),runtime_paths=[str(p) for p in paths])
    if not paths or not (paths[-1]/'performance.jsonl').exists():return result
    rows=[json.loads(line) for line in (paths[-1]/'performance.jsonl').read_text().splitlines()]
    steps=[r for r in rows if r['event']=='performance_step']
    measured=[r for r in steps if r['post_warmup']]
    values=[r['total_ms'] for r in measured]
    result.update(total_ticks=len(steps),measured_ticks=len(measured),warmup_ticks=len(steps)-len(measured),
                  tick=distribution(values),control_hz=1000/np.mean(values) if values else None,
                  rtf=1000/(30*np.mean(values)) if values else None,
                  rolling={str(n):[distribution(values[i:i+n]) for i in range(0,len(values)-n+1)] for n in (100,300)},
                  camera_failures=sum(not r.get('camera_valid',False) for r in measured),
                  tracking_valid={s:sum(r.get(s+'_tracking_valid',False) for r in measured) for s in ('left','right')},
                  stages={k:distribution([r['stage_ms'].get(k,0) for r in measured]) for k in measured[0]['stage_ms']} if measured else {})
    if measured:
        result['nested_stages']={k:distribution([r.get('nested_stage_ms',{}).get(k,0) for r in measured])
                                 for k in measured[0].get('nested_stage_ms',{})}
        previous={r['step']:steps[i-1]['monotonic_ns'] if i else r['monotonic_ns']-int(r['total_ms']*1e6)
                  for i,r in enumerate(steps)}
        periods=[(r['monotonic_ns']-previous[r['step']])/1e6 for r in measured]
        result['observed_wall_tick']=distribution(periods)
        result['wall_control_hz']=1000/float(np.mean(periods))
        result['wall_rtf']=result['wall_control_hz']/30
        samples_path=directory/'experiment_samples.jsonl'
        if samples_path.exists():
            selected={r['step'] for r in measured}
            probes=[json.loads(line) for line in samples_path.read_text().splitlines()]
            probes=[r for r in probes if r['tick'] in selected]
            result['loop_counts']={k:sorted(set(r[k] for r in probes)) for k in ('renders','updates','physics_delta')}
            if probes:
                result['kit_update_hz_proxy']=sum(r['updates'] for r in probes)/(sum(periods)/1000)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('runs',nargs='+');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(json.dumps([summarize(p) for p in args.runs],indent=2)+'\n')
