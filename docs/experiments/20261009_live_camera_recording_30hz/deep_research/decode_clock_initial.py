"""CPU software-decode optical clocks; report missing/duplicate source generations."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import optical_witness as witness

p = argparse.ArgumentParser()
p.add_argument('--input', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--codec-layout', action='store_true')
p.add_argument('--atlas', action='store_true')
a = p.parse_args()
rows, streams = [], []
packets = json.loads((a.input/'packets.json').read_text()) if (a.input/'packets.json').exists() else None
for role in range(3):
    source = a.input/f'role{role}/stream.h264' if a.codec_layout else a.input/f'view_{role}.h264'
    source = a.input/'atlas.h264' if a.atlas else source
    x, y = 300, 260
    if a.atlas:
        x += (role % 2)*960
        y += (role // 2)*600
    command = ['/usr/bin/ffmpeg','-hide_banner','-loglevel','error','-i',str(source),
               '-vf',f'crop=360:80:{x}:{y}','-vsync','0','-f','rawvideo','-pix_fmt','rgb24','pipe:1']
    decoded, ordinals = [], []
    with a.output.with_name(a.output.stem+f'-role{role}.log').open('wb') as log:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)
        while True:
            raw = proc.stdout.read(360*80*3)
            if not raw:
                break
            if len(raw) != 360*80*3:
                raise RuntimeError('Short decoded RGB frame')
            value = witness.decode(np.frombuffer(raw,dtype=np.uint8).reshape(80,360,3))
            decoded.append(value)
            ordinals.append(value['row'])
        if proc.wait(timeout=30):
            raise RuntimeError('Software decode failed')
    reads = [x['control_tick'] for x in packets if x['packet_bytes'] and
             x['packet_bytes'][0 if a.atlas else role]] if packets is not None else []
    phases = [value-(tick-1) for value,tick in zip(ordinals,reads)]
    r = dict(role=role, frames=len(decoded), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
             source_rows=ordinals, first=ordinals[:6], last=ordinals[-6:],
             unique=len(set(ordinals)), consecutive=all(b==a+1 for a,b in zip(ordinals,ordinals[1:])),
             all_confident=all(x['confident'] and x['role']==role for x in decoded),
             min_contrast=min(x['min_contrast'] for x in decoded) if decoded else None,
             phase_min=min(phases) if phases else None, phase_max=max(phases) if phases else None,
             decoder_command=command)
    streams.append(r)
    rows.extend(dict(role=role,decoded_index=i,**v) for i,v in enumerate(decoded))
result=dict(dataset_admissible=False, scope='optical clock freshness, not full physical-pose alignment',
            input=str(a.input),streams=streams,
            passed=all(x['frames'] and x['all_confident'] and x['consecutive'] for x in streams),
            source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
a.output.write_text(json.dumps(result,indent=2)+'\n')
a.output.with_suffix('.rows.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
print(json.dumps({**result,'streams':[{k:v for k,v in x.items() if k!='source_rows'} for x in streams]},indent=2))
raise SystemExit(0 if result['passed'] else 1)
