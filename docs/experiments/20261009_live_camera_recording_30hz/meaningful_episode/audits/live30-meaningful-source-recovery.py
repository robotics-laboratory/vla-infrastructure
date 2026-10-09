"""Recover exact helper bytes and compare them with receipts; never overwrite runs."""
from pathlib import Path
import subprocess,json,hashlib
repo=Path('/home/ebulochkin/vla_infrastructure')
runtime=Path('/data/ebulochkin/vla-runtime/live30-meaningful-episode-20261009')
relative='docs/experiments/20261009_live_camera_recording_30hz/deep_research/'
base='bc6d6a387b195025fded5c954fea8954e667c73c'
sha=lambda b:hashlib.sha256(b).hexdigest()
contents={}
for name in ('live_mirror.py','ovrtx_snapshot.py','ovrtx_gpu_consumer.py','optical_witness.py','verify_live_source.py'):
 contents.setdefault(name,[]).extend([subprocess.check_output(['git','show',base+':'+relative+name],cwd=repo),(repo/relative/name).read_bytes()])
# Reconstruct intermediate edits; only hash-identical bytes are ever admitted.
snapshot=contents['ovrtx_snapshot.py'][0].decode()
anchor='            self.stage.advance_write_floor(self.ordinal, ovstage.Scope.ALL).wait()\n'
addition='            # Nested mesh descendants must see the newly published rigid-body\n            # transforms; updating a camera/marker leaf alone cannot prove this.\n            self.stage.compute_hierarchy(\n                self.ordinal, self.ordinal, ovstage.HierarchyComputationModel.CPU_INCREMENTAL\n            )\n'
contents['ovrtx_snapshot.py'].append(snapshot.replace(anchor,anchor+addition).encode())
mirror=contents['live_mirror.py'][1].decode()
a=mirror.index('        # Diagnostic bypass:')
b=mirror.index('        self.entries,',a)
contents['live_mirror.py'].append((mirror[:a]+mirror[b:]).replace('            render_descendants=render_descendants,\n','').encode())
verify=contents['verify_live_source.py'][1].decode()
verify=verify.replace('witness.matrices(matrices[c], intrinsics[r], seq, r,\n                             depth_scale=seed.get("single_gpu", {}).get("witness_depth_scale", 1.0))','witness.matrices(matrices[c], intrinsics[r], seq, r)')
contents['verify_live_source.py'].append(verify.encode())
lookup={sha(b):b for values in contents.values() for b in values}
ledger=[]
for run in sorted(runtime.glob('reach-*')):
 if not run.is_dir():continue
 target=runtime/'tested-sources'/run.name
 target.mkdir(parents=True,exist_ok=False)
 launch=json.loads(run.with_suffix('.launch.json').read_text())
 for path,source in launch['sources'].items():
  (target/Path(path).name).write_text(source)
 seed=json.loads((run/'mirror/seed.json').read_text())
 hashes={**seed['helper_hashes'],**json.loads((run/'mirror-source-preimages.json').read_text())}
 join=run/'source-join.json'
 if join.exists():hashes[str(repo/relative/'verify_live_source.py')]=json.loads(join.read_text())['source_sha256']
 for path,digest in hashes.items():
  name=Path(path).name
  if (target/name).exists():
   actual=sha((target/name).read_bytes());assert actual==digest,(run.name,name,actual,digest)
  else:
   assert digest in lookup,(run.name,name,'unrecovered',digest)
   (target/name).write_bytes(lookup[digest])
  ledger.append(dict(run=run.name,source_path=path,sha256=digest,verified_against_receipt=True))
(runtime/'tested-sources'/'source-recovery.json').write_text(json.dumps(dict(passed=True,preservation_base=base,script_sha256=sha(Path(__file__).read_bytes()),files=ledger),indent=2)+'\n')
(runtime/'cpu-audits'/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
print('hash-identical recovery',len(ledger),'bindings')
