#!/usr/bin/env python3
"""Reproduce the reviewed lock-only amendment and frozen Isaac environment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from isaac_demo_launch import git

ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/'configs/environments/isaac1103'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('/data/vla-infrastructure/isaac61_production'))
    p.add_argument('--source',default='https://github.com/isaac-sim/IsaacLab.git')
    p.add_argument('--check',action='store_true',help='Read-only exact pin and frozen dry-run check.')
    a=p.parse_args();meta=json.loads((SPEC/'materialization.json').read_text())
    assert hashlib.sha256((SPEC/'upstream-lock.patch').read_bytes()).hexdigest()==meta['patch_sha256']
    lab=a.root/'IsaacLab';envpath=a.root/'env'
    if not a.check:
        if a.root.exists():raise RuntimeError('Refusing to overwrite an existing installation; use --check')
        a.root.mkdir(parents=True)
        subprocess.run(['git','clone','--no-checkout',a.source,str(lab)],check=True)
        subprocess.run(['git','-C',str(lab),'checkout','--detach',meta['parent']],check=True)
        subprocess.run(['git','-C',str(lab),'apply',str(SPEC/'upstream-lock.patch')],check=True)
        subprocess.run(['git','-C',str(lab),'add','uv.lock'],check=True)
        e=os.environ.copy()
        for role in ('AUTHOR','COMMITTER'):
            for suffix in ('NAME','EMAIL','DATE'):e[f'GIT_{role}_{suffix}']=meta[f'{role.lower()}_{suffix.lower()}']
        subprocess.run(['git','-C',str(lab),'commit','-m',meta['message']],env=e,check=True)
    assert git(lab, 'rev-parse', 'HEAD')==meta['commit']
    assert not git(lab, 'status', '--porcelain')
    for name,key in [('uv.lock','lock_sha256'),('pyproject.toml','pyproject_sha256')]:
        assert hashlib.sha256((lab/name).read_bytes()).hexdigest()==meta[key]
    e=os.environ.copy();e.pop('UV_PYTHON_PREFERENCE',None)
    e['UV_PROJECT_ENVIRONMENT']=str(envpath)
    e['UV_CACHE_DIR']='/data/vla-infrastructure/isaac61_qualification/cache/uv'
    command=['uv','sync','--project',str(lab),'--python',
             '/data/vla-infrastructure/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12',
             '--no-managed-python','--frozen','--extra','teleop']
    if a.check:command+=['--offline','--dry-run']
    r=subprocess.run(command,env=e,capture_output=True,text=True)
    print(r.stdout+r.stderr,end='')
    if r.returncode:return r.returncode
    if a.check and 'Would make no changes' not in r.stdout+r.stderr:
        raise RuntimeError('Frozen materialization is not idempotent')
    return 0

if __name__=='__main__':raise SystemExit(main())
