#!/usr/bin/env python3
"""Canonical Isaac launcher: pinned final runtime, explicit legacy rollback."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess

from isaac_demo_launch import configure_cloudxr, git, user_environment, verify_stack, write_runtime_config

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stack', choices=('isaac61', 'legacy'), default='isaac61')
    parser.add_argument('--teleop', action='store_true')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--xr-smoke', action='store_true')
    parser.add_argument('--max-control-steps', type=int, default=18000)
    parser.add_argument('--combined-preview-test', type=int, default=0, metavar='FRAMES')
    parser.add_argument('--preview-control', action='store_true', help='Diagnostic positive control, isolation disabled.')
    parser.add_argument('--cloudxr-mode', choices=('auto', 'existing'), default='auto')
    parser.add_argument('--state-root', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--eval-socket', type=Path)
    parser.add_argument('--eval-run-manifest', type=Path)
    parser.add_argument('--performance-window-steps', type=int, default=30)
    parser.add_argument('--performance-warmup-steps', type=int, default=30)
    args = parser.parse_args(argv)
    if (args.eval_socket is None) != (args.eval_run_manifest is None):
        parser.error('--eval-socket and --eval-run-manifest must be provided together')
    if args.eval_socket is not None and (args.teleop or args.combined_preview_test or args.smoke or args.xr_smoke):
        parser.error('EVAL endpoint is separate from teleop/preview/smoke execution modes')
    if args.smoke and args.xr_smoke:
        parser.error('Choose --smoke or --xr-smoke')
    if args.combined_preview_test and (args.stack != 'isaac61' or args.teleop):
        parser.error('Combined validation uses final isaac_env, separate from physical S2')
    if args.preview_control and not args.combined_preview_test:
        parser.error('--preview-control is diagnostic-only')
    stack = verify_stack(args.stack)
    if not args.dry_run and os.environ.get('OMNI_KIT_ACCEPT_EULA', '').upper() not in ('Y', 'YES', '1'):
        raise RuntimeError('Set OMNI_KIT_ACCEPT_EULA=Y after accepting NVIDIA EULA')
    environment, state = user_environment(stack, args.stack, state_root=args.state_root)
    environment.update({'UV_PROJECT_ENVIRONMENT': str(stack['environment']),
                        'UV_CACHE_DIR': str(state / 'cache/uv')})
    xr = bool(args.combined_preview_test or (args.teleop and not args.smoke))
    if xr or args.teleop:
        environment['VLA_CLOUDXR_INSTALL_DIR'] = str(state / 'cloudxr')
        configure_cloudxr(environment, mode=args.cloudxr_mode, dry_run=args.dry_run)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = state / 'runs' / stamp
    output.mkdir(parents=True, exist_ok=False)
    config = write_runtime_config(ROOT, stack, state, output)
    kit_args = ['--portable-root', str(state / 'kit')]
    if xr:
        kit_args += ['--enable', 'omni.kit.scene_view.xr', '--enable', 'omni.kit.scene_view.xr_utils']
        if args.stack == 'isaac61':
            kit_args += ['--/renderer/scenePartitioning/enabled=true',
                         '--/rtx/scenePartitioning/showAllPartitionsByDefault=true']
    command = ['uv', 'run', '--project', str(stack['lab']), '--frozen', '--no-sync',
               '--no-managed-python', 'python', str(ROOT / 'tools/run_isaac_s1.py'),
               '--device', 'cuda:0', '--config', str(config), '--kit_args', shlex.join(kit_args),
               '--report', str(output / 'result.json')]
    if args.eval_socket is not None:
        command += ['--eval-socket', str(args.eval_socket.resolve()),
                    '--eval-run-manifest', str(args.eval_run_manifest.resolve())]
    if args.stack == 'isaac61':
        command += ['--viz', 'kit']
    if xr:
        command += ['--xr']
    if args.teleop:
        command += ['--s2-performance-log', str(output / 'performance.jsonl'),
                    '--s2-performance-window-steps', str(args.performance_window_steps),
                    '--s2-performance-warmup-steps', str(args.performance_warmup_steps)]
        command += ['--s2-teleop', '--s2-config', str(ROOT / 'configs' / stack['s2']),
                    '--s2-max-control-steps', str(60 if args.smoke or args.xr_smoke else args.max_control_steps),
                    '--s2-cloudxr-profile', 'standalone' if args.smoke else 'cloudxrjs']
        if args.smoke or args.xr_smoke:
            command += ['--no-s2-require-session', '--s2-reset-step', '30']
        else:
            command += ['--s2-require-tracking', '--s2-reset-step', '0']
        if xr and args.stack == 'isaac61':
            command += ['--production-preview']
    if args.combined_preview_test:
        command += ['--production-preview', '--combined-preview-test', str(args.combined_preview_test)]
        if args.preview_control:
            command += ['--preview-control']
    source = sorted((ROOT / 'tools').glob('isaac*.py')) + [ROOT / 'tools/run_isaac_s1.py', ROOT / 'tools/check_isaac_s1_preview.py', Path(__file__)]
    manifest = {'profile': 'isaac_vr_record' if args.teleop else 'isaac_env',
                'stack': args.stack, 'environment_id': 'isaac' if args.stack == 'isaac61' else 'isaac_legacy',
                'project_sha': git(ROOT, 'rev-parse', 'HEAD'), 'cwd': str(ROOT),
                'command': command, 'lab_commit': stack['commit'], 'sdk': str(stack['environment']),
                'pyproject_sha256': stack['pyproject'], 'lock_sha256': stack['lock'],
                'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source},
                'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(), 'dry_run': args.dry_run}
    (output / 'launch_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Isaac evidence output: {output}', flush=True)
    if args.dry_run:
        print(shlex.join(command)); return 0
    stop_requested = False
    process = None

    def request_stop(_signum, _frame):
        nonlocal stop_requested
        if stop_requested:
            return
        stop_requested = True
        print('Stop requested; waiting for final report...', flush=True)
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)

    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    try:
        with (output / 'stdout.log').open('w') as log:
            with subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, start_new_session=True) as process:
                assert process.stdout is not None
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    print(line, end='', flush=True)
                code = process.wait()
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
    result = output / 'result.json'
    if args.eval_socket is not None:
        # Endpoint exit is not an S1 or E1 acceptance report.
        result.write_text(json.dumps({'mode': 'eval_endpoint', 'process': {
            'exit_code': code, 'stop_requested': stop_requested,
            'stdout_log': str(output / 'stdout.log')}, 'acceptance_claim': False}, indent=2) + '\n')
        return code
    if not result.exists():
        return code or 1
    report = json.loads(result.read_text())
    report['process'] = {'exit_code': code, 'clean_shutdown': code in (0, 130), 'stop_requested': stop_requested, 'stdout_log': str(output/'stdout.log')}
    result.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
    return code if code else (0 if report.get('passed') else 1)


if __name__ == '__main__':
    raise SystemExit(main())
