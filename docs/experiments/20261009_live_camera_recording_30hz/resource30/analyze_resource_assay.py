"""Summarize passive resource samples against actual post-warmup control timestamps."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lines(path):
    return [json.loads(v) for v in Path(path).read_text().splitlines() if v.strip()]


def distribution(values):
    values = sorted(float(v) for v in values if v is not None)
    if not values:
        return dict(count=0)
    def percentile(q):
        index = (len(values)-1)*q
        low = int(index)
        return values[low] + (values[min(low+1, len(values)-1)]-values[low])*(index-low)
    return dict(count=len(values), mean=statistics.fmean(values), min=values[0],
                p50=percentile(.5), p95=percentile(.95), p99=percentile(.99), max=values[-1])


def numeric(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None  # Unsupported NVIDIA metrics remain unknown, never zero.


def overlap(a, b, start, end):
    return max(0, min(b, end)-max(a, start))/1e9


def tree(row, name):
    return {(p['pid'], p['start_ticks']):p for p in row['processes'].get(name, [])}


def analyze(folder, explicit_recording=None):
    receipt = json.loads((folder/'receipt.json').read_text())
    config_name = receipt.get('copied_inputs', {}).get(receipt.get('config'))
    config = json.loads((folder/config_name).read_text()) if config_name else {}
    recording = Path(explicit_recording or config['recording_output'])
    perf_path = recording/'performance.jsonl'
    steps = [p for p in lines(perf_path) if p.get('event') == 'performance_step' and p.get('post_warmup') is True]
    if not steps:
        raise ValueError('No post-warmup control rows')
    clock = receipt.get('clock_info', {})
    if clock and clock['monotonic']['implementation'] != clock['perf_counter']['implementation']:
        raise ValueError('Performance and monitor clocks require an explicit calibrated join')
    start = int(steps[0]['monotonic_ns'])-round(float(steps[0]['total_ms'])*1e6)
    end = int(steps[-1]['monotonic_ns'])
    if end <= start:
        raise ValueError('Invalid post-warmup window')
    samples = lines(folder/'samples.jsonl')
    selected = [r for r in samples if start <= r['begin_monotonic_ns'] <= end]
    cpu, process, gpu, memory = {}, {}, {}, {}
    hz, page = receipt['clock_ticks_per_s'], receipt['page_size_bytes']
    active, cpu_seconds, intervals = {}, {}, []
    for previous, row in zip(samples, samples[1:]):
        a, b = previous['begin_monotonic_ns'], row['begin_monotonic_ns']
        seconds = (b-a)/1e9
        shared = overlap(a, b, start, end)
        if seconds <= 0 or not shared:
            continue
        intervals.append(dict(begin_monotonic_ns=a, end_monotonic_ns=b, overlap_s=shared))
        for name, current in row['cpu_ticks'].items():
            prior = previous['cpu_ticks'].get(name)
            if prior is None:
                continue
            deltas = [v-p for v,p in zip(current[:8], prior[:8])]
            total = sum(deltas)
            if total > 0 and min(deltas) >= 0:
                busy = total-deltas[3]-deltas[4]
                cpu.setdefault(name, []).append(100*busy/total)
        for name in ('recorder', 'background', 'monitor'):
            old, new = tree(previous, name), tree(row, name)
            ticks = sum(max(0, p['utime_ticks']+p['stime_ticks']-old[key]['utime_ticks']-old[key]['stime_ticks'])
                        for key,p in new.items() if key in old)
            core_seconds = ticks/hz
            process.setdefault(name, {}).setdefault('cpu_percent_one_core', []).append(100*core_seconds/seconds)
            cpu_seconds[name] = cpu_seconds.get(name, 0)+core_seconds*shared/seconds
            active[name] = active.get(name, 0)+(shared if ticks > 0 else 0)
    for row in selected:
        for name, procs in row['processes'].items():
            process.setdefault(name, {}).setdefault('rss_sum_bytes', []).append(sum(p['rss_pages']*page for p in procs))
        for key in ('MemTotal', 'MemAvailable', 'MemFree', 'Cached', 'SwapTotal', 'SwapFree'):
            value = row['meminfo'].get(key)
            memory.setdefault(key+'_kib', []).append(numeric(value.split()[0]) if value else None)
        for device in row.get('gpu', {}).get('devices', []):
            identity = device.get('uuid', device.get('index', 'unknown'))
            for key,value in device.items():
                if key not in ('index', 'uuid'):
                    gpu.setdefault(identity, {}).setdefault(key, []).append(numeric(value))
    cadence = [(b['begin_monotonic_ns']-a['begin_monotonic_ns'])/1e9 for a,b in zip(samples,samples[1:])]
    command = receipt['commands'].get('background')
    bg_overlap = overlap(command['launch_end_monotonic_ns'], command.get('exit_observed_monotonic_ns', receipt['finished_monotonic_ns']), start, end) if command else 0
    result = dict(schema='resource_assay_analysis_v1', physical=False, quest_connected=False, dataset_admissible=False,
                  harness_passed=receipt['passed'], telemetry_complete=receipt.get('telemetry_complete'),
                  source_pins={str(folder/'receipt.json'):digest(folder/'receipt.json'), str(folder/'samples.jsonl'):digest(folder/'samples.jsonl'),
                               str(perf_path):digest(perf_path), str(Path(__file__)):digest(__file__)},
                  recording_output=str(recording), steady_window=dict(start_monotonic_ns=start,end_monotonic_ns=end,duration_s=(end-start)/1e9,
                      definition='first post-warmup end minus its total_ms through final post-warmup end; includes between-step pacing',
                      first_step=steps[0].get('step'),last_step=steps[-1].get('step'),control_rows=len(steps)),
                  control_total_ms=distribution(p['total_ms'] for p in steps),
                  control_end_spacing_s=distribution((b['monotonic_ns']-a['monotonic_ns'])/1e9 for a,b in zip(steps,steps[1:])),
                  cadence_s=distribution(cadence), sampled_steady_rows=len(selected),
                  coverage=dict(first_sample_monotonic_ns=samples[0]['begin_monotonic_ns'],last_sample_monotonic_ns=samples[-1]['begin_monotonic_ns'],
                                entire_steady_window_bracketed=samples[0]['begin_monotonic_ns'] <= start and samples[-1]['begin_monotonic_ns'] >= end,
                                max_gap_s=max(cadence) if cadence else None, raw_interval_rows=intervals),
                  cpu_busy_percent={k:distribution(v) for k,v in cpu.items()},
                  processes={k:{metric:distribution(v) for metric,v in values.items()} for k,values in process.items()},
                  memory={k:distribution(v) for k,v in memory.items()},
                  gpu={identity:{k:distribution(v) for k,v in fields.items()} for identity,fields in gpu.items()},
                  background=dict(requested=command is not None,alive_overlap_s=bg_overlap,
                      observed_positive_cpu_interval_overlap_s=active.get('background',0),estimated_core_seconds_in_window=cpu_seconds.get('background',0),
                      alive_overlap_ge20s=bg_overlap >= 20 if command else None,
                      observed_cpu_interval_overlap_ge20s=active.get('background',0) >= 20 if command else None),
                  limitations=['CPU utilization uses /proc/stat first eight fields; guest time is already included and iowait is an approximate kernel counter.',
                      'Tree RSS sums shared pages repeatedly; it is not unique physical memory.',
                      'CPU increments are interpolated over sampling intervals; exited-before-next-sample CPU fragments are unknown.',
                      'Positive CPU ticks establish observed work, not a particular materialization phase or CPU saturation.',
                      'GPU utilization describes whole devices, including any unrelated contexts; unsupported metrics are unknown.',
                      'Control window is not camera exposure or GPU execution timestamps; no physical or Quest qualification.'])
    worker = recording/'mirror/worker-rows.jsonl'
    if worker.is_file():
        rows = lines(worker)
        result['source_observation_clock'] = dict(rows=len(rows), available_rows=sum('observation_sample_monotonic_ns' in r for r in rows),
              first_monotonic_ns=rows[0].get('observation_sample_monotonic_ns') if rows else None,
              last_monotonic_ns=rows[-1].get('observation_sample_monotonic_ns') if rows else None,
              source_wall_ns_clock='retained only in raw worker rows; never mixed with CLOCK_MONOTONIC')
        result['source_pins'][str(worker)] = digest(worker)
        chosen = {r['source_id']:r for r in rows if start <= r.get('observation_sample_monotonic_ns', -1) <= end}
        deltas = {}
        for label, first, last in [('sample_to_worker_complete_ms', 'observation_sample_monotonic_ns', 'worker_complete_ns'),
                                   ('sample_to_render_submission_ms', 'observation_sample_monotonic_ns', 'worker_render_submitted_monotonic_ns'),
                                   ('capture_ms', 'observation_capture_begin_monotonic_ns', 'observation_capture_end_monotonic_ns'),
                                   ('queue_to_worker_complete_ms', 'enqueued_ns', 'worker_complete_ns')]:
            deltas[label] = distribution((r[last]-r[first])/1e6 for r in chosen.values() if first in r and last in r)
        packets_by_role = {}
        for role in range(3):
            path = recording/f'mirror/media/role{role}/packets.jsonl'
            if path.is_file():
                packet_rows = lines(path)
                tags = [p['submitted_source_tag'] for p in packet_rows]
                if len(tags) != len(set(tags)):
                    raise ValueError('Duplicate packet source tags')
                packets_by_role[str(role)] = distribution((p['packet_ready_monotonic_ns']-chosen[p['submitted_source_tag']]['observation_sample_monotonic_ns'])/1e6
                    for p in packet_rows if p['submitted_source_tag'] in chosen and 'packet_ready_monotonic_ns' in p)
                result['source_pins'][str(path)] = digest(path)
        result['host_pipeline_age_ms'] = dict(stages=deltas, sample_to_packet_ready_by_role=packets_by_role,
            semantics='Packet ready is host Encode/EndEncode returned. Render submission is a host boundary, not GPU-completion or camera exposure proof.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assay', type=Path, required=True)
    parser.add_argument('--recording-output', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.assay,args.recording_output)
    with args.output.open('x') as handle:
        handle.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('harness_passed','telemetry_complete','sampled_steady_rows','background')}))


if __name__ == '__main__':
    main()
