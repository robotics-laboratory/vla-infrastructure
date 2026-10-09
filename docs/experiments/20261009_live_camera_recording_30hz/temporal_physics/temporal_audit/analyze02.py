"""Read-only offline temporal audit; imports numpy/h5py, never Kit/CUDA."""
import hashlib,json,platform,sys,time
from pathlib import Path
import h5py
import numpy as np
ROOT=Path('/data/ebulochkin/vla-runtime/live30-meaningful-episode-20261009')
REPO=Path('/home/ebulochkin/vla_infrastructure')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stats(v):
 a=np.asarray(v,dtype=float)
 return dict(n=len(a),min=float(a.min()),mean=float(a.mean()),p50=float(np.percentile(a,50)),p95=float(np.percentile(a,95)),p99=float(np.percentile(a,99)),max=float(a.max()))
def lines(p):return [json.loads(x) for x in p.read_text().splitlines()]
def audit(name):
 p=ROOT/name;rp=p/'result.json';r=json.loads(rp.read_text());wp=p/'mirror/worker-rows.jsonl';rows=lines(wp);hp=p/'episode/session.hdf5';pp=p/'performance.jsonl';perf=[x for x in lines(pp) if x['event']=='performance_step'];tp=p/'physics/timings.json';timings=json.loads(tp.read_text());used=[rp,wp,hp,pp,tp]
 with h5py.File(hp) as h:
  g=h['episodes/episode_00000'];t=g['d0/committed_transition'];sim=g['meta/time/sim_time'][:];wall=g['meta/time/wall_time'][:];phys=g['meta/time/physics_step'][:]
  check={
   'count_960':len(sim)==960,'sequence_0_959':np.array_equal(t['observation_capture_sequence'][:],np.arange(960)),
   'successor_sequence_plus1':np.array_equal(t['successor_capture_sequence'][:],np.arange(1,961)),
   'physics_plus4':np.all(t['successor_physics_step'][:]-t['observation_physics_step'][:]==4),
   'meta_physics_matches_observation':np.array_equal(phys,t['observation_physics_step'][:]),
   'meta_sim_eq_physics_div120':np.allclose(sim,phys/120,rtol=0,atol=1e-12),
   'successor_state_promoted_exact':np.array_equal(t['successor_observation_state'][:-1],t['observation_state'][1:]),
   'worker_source_seq_exact':np.array_equal([x['source_id'] for x in rows],np.arange(961)),
   'worker_physics_matches':np.array_equal([x['physics_step'] for x in rows[:-1]],phys),
   'worker_sim_matches':np.array_equal([x['source_sim_time_s'] for x in rows[:-1]],sim),
   'source_wall_exact_hdf_conversion':np.array_equal([x['source_wall_ns'] for x in rows[:-1]],np.asarray([int(float(v)*1e9) for v in wall])),
   'all_committed':np.all(t['committed'][:]),
   'same_epoch':np.all(t['reset_epoch'][:]==t['successor_reset_epoch'][:]),
   'all_injected_deviceio_epochs_match_tick':np.array_equal(t['deviceio_update_epoch'][:],t['control_tick_id'][:]),
   'all_injected_returned_submitted_match':np.array_equal(t['submitted_frame_id'][:],t['returned_frame_id'][:]),
  }
  task_success_true_count=int(np.count_nonzero(t['success'][:]))
  d0_time_fields=[k for k in t if any(s in k for s in ['time','stamp','_ns'])]
 enqueue=np.array([x['enqueued_ns'] for x in rows],dtype=np.int64);done=np.array([x['worker_complete_ns'] for x in rows],dtype=np.int64);total=np.array([x['worker_total_ms'] for x in rows]);queue=(done-enqueue)/1e6-total
 clocks=np.array([x['source_wall_ns'] for x in rows],dtype=np.int64)
 # Source generation mono is approximately previous perf end minus committed/capture/view duration;
 # DO NOT directly subtract CLOCK_REALTIME source_wall from CLOCK_MONOTONIC enqueue.
 offset=clocks-enqueue
 packet=[]
 for role in range(3):
  pk=p/f'mirror/media/role{role}/packets.jsonl';used.append(pk);pack=lines(pk)
  pending=np.array([x['frames'][role]['gpu']['pending'] for x in rows]);available=np.arange(961)+1-pending
  ready_bounds=[];newer=[]
  for source in range(961):
   indices=np.flatnonzero(available>source)
   if len(indices):
    i=int(indices[0]);ready_bounds.append((done[i]-enqueue[source])/1e6);newer.append(i-source)
  packet.append(dict(role=role,counts=len(pack),ordinal_exact=[x['encoder_packet_timestamp'] for x in pack]==list(range(961)),source_tag_exact=[x['submitted_source_tag'] for x in pack]==list(range(961)),flush_packets=sum(x['flush'] for x in pack),pending_after_encode=stats(pending),packet_return_seen_by_triplet_complete_upper_bound_ms=stats(ready_bounds),future_source_submissions_before_packet_visible=stats(newer),unresolved_until_final_drain=961-len(ready_bounds),has_wall_timestamp=any(any(k.endswith('_ns') for k in x) for x in pack)))
 camera_delta=np.array([[f['capture_end']-x['source_sim_time_s'] for f in x['frames']] for x in rows]);starts=np.array([[f['capture_start'] for f in x['frames']] for x in rows]);ends=np.array([[f['capture_end'] for f in x['frames']] for x in rows])
 # Same-host perf and monotonic implementations are recorded below. Perf event timestamp is after body;
 # duration reconstructs begin with tiny host bookkeeping skew, so label these approximations.
 step_begin=np.array([x['monotonic_ns']-round(x['total_ms']*1e6) for x in perf]);observation_ages=(step_begin-enqueue[:-1])/1e6
 return dict(run=name,checks={k:bool(v) for k,v in check.items()},d0_host_event_timestamp_fields=d0_time_fields,task_success_true_count=task_success_true_count,task_success_semantics='Task success is false; committed transition execution is independently checked. Not a temporal failure.',source_wall_clock='Unix time.time cached at worker reply; initial SourceClock constructor before startup',time_domains_must_not_subtract=True,source_sim_range=[rows[0]['source_sim_time_s'],rows[-1]['source_sim_time_s']],physics_range=[rows[0]['physics_step'],rows[-1]['physics_step']],wall_source_initial_gap_ms=float((wall[1]-wall[0])*1e3),wall_source_interval_excluding_initial_ms=stats(np.diff(wall)[1:]*1e3),enqueued_to_worker_triplet_submitted_ms=stats((done-enqueue)/1e6),worker_total_ms=stats(total),pre_worker_wait_ms=stats(queue),relative_clock_offset_span_excluding_initial_ms=float(np.ptp(offset[1:])/1e6),source0_enqueue_offset_deviation_from_later_median_ms=float((np.median(offset[1:])-offset[0])/1e6),previous_observation_enqueue_to_next_decision_loop_begin_approx_ms=stats(observation_ages[1:]),stage_ms={k:stats([x[k] for x in rows]) for k in ['apply_publish_ms','render_ms','output_consume_ms']},native_and_view_ms={k:stats([x[k]/1e6 for x in timings]) for k in ['physics_ipc_ns','passive_view_ns','physics4','capture']},camera_end_minus_source_time_maxabs_s=float(np.max(np.abs(camera_delta))),camera_exposure_duration_maxabs_s=float(np.max(np.abs(ends-starts))),sensor_clock_interval_s=stats([x['sensor_clock'][1]-x['sensor_clock'][0] for x in rows]),packets=packet,ack_age_p95_ms=r['mirror']['ack_age_p95_ms'],ack_semantics=r['mirror'].get('ack_semantics','not annotated in old receipt; source audit required'),working_s=r['working_s'],physical_sim_rtf=32/r['working_s'],logger_wall_rtf=r['performance']['wall_rtf'],input_pump_calls=r['transitions']['input_pump_calls'],provenance={str(x):sha(x) for x in used})
result=dict(schema='read_only_temporal_audit_v1',command=[sys.executable,*sys.argv],script_sha256=sha(Path(__file__)),python=platform.python_version(),gpu_imports=False,clock_info={k:vars(time.get_clock_info(k)) for k in ['time','perf_counter','monotonic']},runs=[audit(x) for x in ['reach-demo08','reach-witness10']],head='fbdee2055efa325c352e13b321223cdf6c2f3e40',master='beaedfd1116577fd4d8026232cfb96cba0b030fa')
Path('/tmp/live30-correctness-temporal-analysis02.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
