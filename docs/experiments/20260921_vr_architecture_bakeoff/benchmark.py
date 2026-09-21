"""Sequential, independent-process benchmark repetitions; no concurrent GPU load."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

parser=argparse.ArgumentParser()
parser.add_argument('candidate')
parser.add_argument('--mode',default='smoke',choices=['smoke','xr-smoke'])
parser.add_argument('--long',action='store_true')
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--state-root',default='/tmp/vr4p-audit')
args=parser.parse_args();runs=[]
for rep in range(1,4 if args.long else 2):
    out=args.output/f'rep{rep}'
    cmd=[sys.executable,str(Path(__file__).with_name('launch.py')),args.candidate,
         '--mode',args.mode,'--ticks','3300' if args.long else '160',
         '--warmup','300' if args.long else '30','--state-root',args.state_root,'--output',str(out)]
    result=subprocess.run(cmd)
    runs.append({'repetition':rep,'command':cmd,'exit_code':result.returncode,'output':str(out)})
    (args.output/'repetitions.json').write_text(json.dumps(runs,indent=2))
    if result.returncode:break
raise SystemExit(runs[-1]['exit_code'])
