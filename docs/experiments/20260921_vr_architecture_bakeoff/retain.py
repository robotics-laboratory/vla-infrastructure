"""Retain this bounded experiment's outputs; exclude disposable Kit caches."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
args.output.mkdir(parents=True,exist_ok=False)
staging=args.output/'files';staging.mkdir()
locators={}

def copy_file(source,dest):
    if source.is_symlink() or not source.is_file():return
    if '__pycache__' in source.parts:return
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,dest)
    locators[str(source)]=str(dest.relative_to(staging))

for source in sorted(Path('/tmp').glob('vr4p5*')):
    if source.name in ('vr4p5-phase-state','vr4p5-runtime','vr4p5-physical'):continue  # Kit caches; phase retention already has run outputs.
    if source==args.output:continue
    if source.is_dir():
        for file in source.rglob('*'):copy_file(file,staging/'tmp'/source.name/file.relative_to(source))
    else:copy_file(source,staging/'tmp'/source.name)
# Only runtime dirs named by experiment launch logs, never an entire portable root.
for log in staging.glob('tmp/**/launch.log'):
    for line in log.read_text(errors='replace').splitlines():
        if line.startswith('VR output: '):
            run=Path(line.split(': ',1)[1])
            for file in run.rglob('*'):
                copy_file(file,staging/'runtime'/run.name/file.relative_to(run))
# Retain directly resolved USD asset dependencies, not just their hashes.
for manifest in staging.glob('tmp/**/full_offline_manifest.json'):
    for name,expected in json.loads(manifest.read_text()).get('dependencies',{}).items():
        source=Path(name)
        if expected is None or not source.is_file():continue
        if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Captured asset changed: '+name)
        copy_file(source,staging/'captured_assets'/name.lstrip('/'))
# Preserve the public/pinned sources independently of an installed SDK changing later.
audit=json.loads(Path(__file__).with_name('source_audit.json').read_text())
for name in audit['sources']:
    source=Path(name)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=audit['sources'][name]:
        raise RuntimeError('Pinned source changed: '+name)
    copy_file(source,staging/'audited_sources'/name.lstrip('/'))
for file in Path(__file__).parent.iterdir():
    if file.is_file() and (file.suffix=='.py' or file.name=='source_audit.json'):
        copy_file(file,staging/'experiment_source'/file.name)
(staging/'locator-map.json').write_text(json.dumps(locators,indent=2)+'\n')
hashes={str(p.relative_to(staging)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(staging.rglob('*')) if p.is_file()}
(staging/'sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
archive=args.output/'architecture-bakeoff.tar.gz'
with tarfile.open(archive,'w:gz',compresslevel=5) as tar:tar.add(staging,arcname='architecture-bakeoff')
# Verify uncompressed member bytes against the frozen inventory.
with tarfile.open(archive,'r:gz') as tar:
    for name,expected in hashes.items():
        if hashlib.sha256(tar.extractfile('architecture-bakeoff/'+name).read()).hexdigest()!=expected:
            raise RuntimeError('Archive mismatch: '+name)
result=dict(archive=str(archive),sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            files=len(hashes),uncompressed_bytes=sum((staging/n).stat().st_size for n in hashes),
            compressed_bytes=archive.stat().st_size,verified=True)
(args.output/'retention.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
