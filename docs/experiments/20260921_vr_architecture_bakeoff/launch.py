"""Launch isolated architecture experiments using the canonical scene and loop."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import shutil

ROOT = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser()
parser.add_argument('candidate', choices=['A0', 'J60', 'E08', 'E06', 'F-minimal', 'D-desktop-off', 'B1-capture', 'B1-cost', 'B1-FULL-OFFLINE', 'B1-FULL-OFFLINE-D', 'C1-640', 'C1-320', 'C2-320', 'C2-256', 'G-tiled640', 'G-assay', 'H-cpu', 'H-cpu-capture', 'render-assay', 'phase', 'LIVE-MIN60-NONTILED'])
parser.add_argument('--mode', choices=['smoke', 'xr-smoke', 'physical'], default='smoke')
parser.add_argument('--ticks', type=int, default=160)
parser.add_argument('--warmup', type=int, default=30)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--state-root', type=Path, default=Path('/tmp/vr4p5-runtime'))
parser.add_argument('--verify-xr-display',action='store_true',help='Two XR-display screenshots during ordinary pumps; functional probe only')
parser.add_argument('--profile-passes',action='store_true',help='150 post-control render-only frames, outside control timing')
parser.add_argument('--phase-qualification',action='store_true',help='Run the bounded content phase witness after timed controls')
args = parser.parse_args()
if args.candidate.startswith('B1-FULL-OFFLINE') and args.profile_passes:
    raise SystemExit('B1-FULL-OFFLINE forbids auxiliary profiling render passes')
branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
if branch!='wip/vr-recording':raise SystemExit('Wrong experiment branch: '+branch)
subprocess.run(['git','diff','--exit-code','bd288917ac44a873feef04df9a488c4046927d87','--',
                'tools','run-vr','configs/isaac61_s1_runtime.yaml','configs/isaac61_s2_runtime.yaml',
                'configs/isaac61_vr_runtime.yaml'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
if args.output.exists():
    raise SystemExit('Use a new output directory; never overwrite evidence')
args.output.mkdir(parents=True)
(args.output/'sources').mkdir()
for source in Path(__file__).parent.glob('*.py'):
    shutil.copy2(source,args.output/'sources'/source.name)
env = os.environ.copy()
env.pop('HEADLESS', None)
env.update(DISPLAY=env.get('DISPLAY', ':0'), OMNI_KIT_ACCEPT_EULA='Y',
           ISAACLAB_CXR_ACCEPT_EULA='1', VR_BAKEOFF_CANDIDATE=args.candidate,
           VR_BAKEOFF_OUTPUT=str(args.output.resolve()), PYTHONPATH=str((args.output/'sources').resolve()))
env['VR_BAKEOFF_VERIFY_XR_DISPLAY']='1' if args.verify_xr_display else '0'
env['VR_BAKEOFF_PROFILE_PASSES']='1' if args.profile_passes else '0'
env['VR_LIVE_MIN60_PHASE']='1' if args.phase_qualification else '0'
cmd = ['./run-vr', 'diag', '--state-root', str(args.state_root.resolve()),
       '--max-control-steps', str(args.ticks), '--performance-warmup-steps', str(args.warmup),
       '--performance-window-steps', '100']
if args.mode != 'physical':
    cmd.append('--' + args.mode)
manifest = dict(candidate=args.candidate, command=cmd, cwd=str(ROOT),
                head=subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
                env={k: env[k] for k in ['DISPLAY','OMNI_KIT_ACCEPT_EULA','ISAACLAB_CXR_ACCEPT_EULA',
                                       'VR_BAKEOFF_CANDIDATE','VR_BAKEOFF_OUTPUT','VR_BAKEOFF_PROFILE_PASSES','VR_BAKEOFF_VERIFY_XR_DISPLAY','VR_LIVE_MIN60_PHASE','PYTHONPATH']},
                sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
                started=time.time())
(args.output/'launch.json').write_text(json.dumps(manifest, indent=2))
if args.mode=='physical':
    observations=dict(classification='OPERATOR-REPORTED; pending',candidate=args.candidate,
        operator=None,measured_interval_start=None,measured_interval_end=None,
        adjacent_baseline_output=None,world_smoothness=None,head_motion_latency=None,
        controller_response=None,panel_smoothness=None,panel_latency=None,panel_readability=None,
        manipulation_difficulty=None,task_success=None,discomfort_nausea=None,
        tracking_and_reconnect=None,shutdown=None,notes=None)
    (args.output/'operator_observations.json').write_text(json.dumps(observations,indent=2)+'\n')
print(f"Starting {args.candidate}; log: {args.output/'launch.log'}",flush=True)
returncode=130
with (args.output/'gpu.csv').open('w') as gpu, (args.output/'launch.log').open('w') as stream:
    monitor=subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,name,utilization.gpu,memory.used,power.draw',
                              '--format=csv','-l','1'],stdout=gpu,stderr=subprocess.STDOUT)
    try:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        returncode=result.returncode
    except KeyboardInterrupt:
        pass
    finally:
        monitor.terminate()
        monitor.wait()
manifest.update(exit_code=returncode, ended=time.time())
(args.output/'launch.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps(manifest, indent=2))
raise SystemExit(returncode)
