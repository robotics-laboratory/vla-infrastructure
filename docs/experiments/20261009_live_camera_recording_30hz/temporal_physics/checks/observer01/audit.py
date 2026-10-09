"""Independent read-only event/state/packet audit. No simulator imports."""
import argparse,hashlib,json,sys
from pathlib import Path
import h5py
import numpy as np

def rows(p):return [json.loads(v) for v in p.read_text().splitlines()]
def stats(v):
 a=np.array(v,float);return {'n':len(a),'p50_ms':float(np.percentile(a,50)),'p95_ms':float(np.percentile(a,95)),'max_ms':float(a.max()),'min_ms':float(a.min())}
def audit(d):
 result=json.loads((d/'result.json').read_text());n=result['transitions']['committed_frames'];w=rows(d/'mirror/worker-rows.jsonl');e=rows(d/'host-events.jsonl');checks={};bad=[]
 def check(name,value):checks[name]=bool(value)
 names=['capture_observation','decision_solve','_apply','_advance','capture_successor','commit_transition'];groups={k:[r for r in e if r['event']==k] for k in names};appends=[r for r in e if r['event']=='hdf_append_ms']
 check('counts',len(w)==n+1 and all(len(v)==n for v in groups.values()) and len(appends)==n)
 if not checks['counts']:return dict(checks=checks,all_passed=False,error='Missing event count, no positional indexing attempted')
 for i in range(n):
  obs,dec,apply,advance,suc,commit=[groups[k][i] for k in names];before=w[i]['physics_step'];after=w[i+1]['physics_step'];chain=[obs,dec,apply,advance,suc,commit]
  assertions={
   'phase_intervals_nonnegative':all(v['begin_monotonic_ns']<=v['end_monotonic_ns'] for v in chain),
   'complete_phase_order':all(a['end_monotonic_ns']<=b['begin_monotonic_ns'] for a,b in zip(chain,chain[1:])),
   'only_advance_changes_step':all(v['physics_step_after']==before for v in [obs,dec,apply]) and all(v['physics_step_after']==after for v in [advance,suc,commit]) and after==before+4,
   'source_ids':obs['source_id']==i and suc['source_id']==i+1 and commit['source_id']==i and commit['successor_source_id']==i+1,
   'source_steps':obs['source_physics_step']==before and suc['source_physics_step']==after and commit['source_physics_step']==before,
   'decision_tick':dec['tick']==i+1,
   'physical_receipt_inside_advance':advance['begin_monotonic_ns']<=w[i+1]['state_received_monotonic_ns']<=advance['end_monotonic_ns'],
   'successor_sample_inside_successor_event':suc['begin_monotonic_ns']<=w[i+1]['observation_sample_monotonic_ns']<=suc['end_monotonic_ns'],
   'append_inside_commit':commit['begin_monotonic_ns']<=appends[i]['begin_monotonic_ns']<=appends[i]['end_monotonic_ns']<=commit['end_monotonic_ns'],
  }
  if i:assertions['promoted_observation_no_resample']=w[i]['observation_capture_end_monotonic_ns']<=obs['begin_monotonic_ns'] and groups['commit_transition'][i-1]['end_monotonic_ns']<=obs['begin_monotonic_ns']
  for k,v in assertions.items():
   checks[k]=checks.get(k,True) and bool(v)
   if not v:bad.append(dict(control=i,check=k))
 check('initial_sample_inside_first_observation',groups['capture_observation'][0]['begin_monotonic_ns']<=w[0]['observation_sample_monotonic_ns']<=groups['capture_observation'][0]['end_monotonic_ns'])
 check('native_engine_frozen',result['source_owner']['native_physics_frozen'])
 check('native_total_steps_exact',result['source_owner']['tail']['physics_steps']==4*n and w[-1]['physics_step']-w[0]['physics_step']==4*n)
 for k in ['observation_capture_begin_monotonic_ns','observation_sample_monotonic_ns','observation_capture_end_monotonic_ns','enqueued_ns','ipc_send_begin_monotonic_ns','ipc_received_monotonic_ns','worker_render_submitted_monotonic_ns']:
  check(k+'_strictly_increasing',all(a[k]<b[k] for a,b in zip(w,w[1:])))
 keys=['state_received_monotonic_ns','observation_capture_begin_monotonic_ns','observation_sample_monotonic_ns','observation_capture_end_monotonic_ns','enqueued_ns','ipc_send_begin_monotonic_ns','ipc_received_monotonic_ns','worker_render_submitted_monotonic_ns']
 check('source_sample_ipc_submit_chain',all(all(r[a]<=r[b] for a,b in zip(keys,keys[1:])) for r in w))
 with h5py.File(d/'episode/session.hdf5') as f:
  g=f['episodes/episode_00000'];t=g['d0/committed_transition']
  check('hdf_obs_successor_sequences',np.array_equal(t['observation_capture_sequence'][:],np.arange(n)) and np.array_equal(t['successor_capture_sequence'][:],np.arange(1,n+1)))
  check('hdf_physics_steps_join',np.array_equal(t['observation_physics_step'][:],[r['physics_step'] for r in w[:-1]]) and np.array_equal(t['successor_physics_step'][:],[r['physics_step'] for r in w[1:]]))
  check('promoted_states_exact',np.array_equal(t['successor_observation_state'][:-1],t['observation_state'][1:]))
  check('cached_state_receipt_not_written_as_sample',all(float(a)!=float(b['state_received_unix_s']) for a,b in zip(g['meta/time/wall_time'][:],w)))
 lat=[]
 for role in range(3):
  p=rows(d/f'mirror/media/role{role}/packets.jsonl');check(f'packet_role{role}_full_sequence',[x['submitted_source_tag'] for x in p]==list(range(n+1)));check(f'packet_role{role}_valid_order',all(w[x['submitted_source_tag']]['observation_sample_monotonic_ns']<=x['packet_ready_monotonic_ns']<=x['packet_write_completed_monotonic_ns'] for x in p))
  metrics={}
  for field in ['state_received_monotonic_ns','observation_sample_monotonic_ns','enqueued_ns']:
   values=[(x['packet_ready_monotonic_ns']-w[x['submitted_source_tag']][field])/1e6 for x in p];metrics[field]=dict(initial_ms=values[0],all_after_initial=stats(values[1:]),nonflush_after_initial=stats([v for v,x in zip(values[1:],p[1:]) if not x['flush']]))
  lat.append(dict(role=role,metrics=metrics))
 inputs=[d/'result.json',d/'host-events.jsonl',d/'episode/session.hdf5',d/'mirror/worker-rows.jsonl',*[d/f'mirror/media/role{i}/packets.jsonl' for i in range(3)]]
 return dict(schema='independent_observer_temporal_audit_v1',input=str(d),controls=n,checks=checks,all_passed=all(checks.values()),failures=bad,packet_latency=lat,observer_scope='Only completed normal control phases; no extra physics steps observed in this run. Failed-call events and cleanup restoration are separate source-audit concerns.',source_sample_initial_age_ms=(w[0]['observation_sample_monotonic_ns']-w[0]['state_received_monotonic_ns'])/1e6,provenance={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();assert not a.output.exists();r=audit(a.input);r.update(command=[sys.executable,*sys.argv],script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest());a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2));raise SystemExit(0 if r['all_passed'] else 1)
