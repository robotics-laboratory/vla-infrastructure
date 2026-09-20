# Isaac runtime operations

For current physical Quest operation, the **PRIMARY OPERATOR ENTRYPOINT** is
`./run-vr`; follow [RUN_VR_OPERATIONS.md](../../RUN_VR_OPERATIONS.md).
This maintenance note also covers the **BASE / GENERIC S2 LAUNCHER**,
`tools/launch_isaac_s2.py`, which remains supported for base S2 and smokes.

Run project commands from your own `~/vla_infrastructure` checkout. Shared SDKs,
assets, converted USD, CloudXR, shader caches, logs, PNG and per-frame metadata
live under `/data`; `/data/vla-infrastructure/robosyn-kit1103` is not the production
project entry point. Do not run under another person's HOME or reuse their XR IPC.

## Paths and ownership

- Final SDK: `/data/vla-infrastructure/isaac61_production/{IsaacLab,env}`.
- Legacy SDK: `/data/vla-infrastructure/isaaclab_candidate_qualification/20260907/candidate_b_exact`
  and `/data/vla-infrastructure/envs/isaac-s1-candidate-b`.
- Mutable state: `/data/<Linux username>/vla-runtime/isaac-isaac61/` (legacy uses `isaac-legacy`).
  Each account needs its own writable `/data/<username>` provisioned by the host administrator.
  Each account must be able to read/execute the shared SDK/assets. No account needs write access to them.
- `--state-root /data/<your-private-directory>` overrides the default. The launcher
  rejects a foreign-owned or symlink state root; it does not chmod another user's files.
- Kit's portable root and CUDA/Warp/XDG/temp/converted assets are all per account.
  `PYTHONNOUSERSITE=1` and explicit SDK paths prevent importing another checkout.
- Only one active CloudXR server may use default port 48322. An occupied port
  fails before launch; it is never taken over. `--cloudxr-mode existing` means
  the **current account's** server in its selected `/data` state root.

## Current operator command

After accepting the NVIDIA EULAs:

```sh
cd ~/vla_infrastructure
export OMNI_KIT_ACCEPT_EULA=Y
export ISAACLAB_CXR_ACCEPT_EULA=1
./run-vr
```

This selects run-vr + RoboSyn demo overlay + final Isaac61 stack. The overlay
selects independent 2x–4x–6x sliders, Scene Partitions and three previews. It
remains experimental and requires physical S2 re-acceptance; use the
[current worksheet](../../GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md). Operator status
does not make demo logs evidence for the complete S1 contract.

## Base S1/S2 and automated checks

```sh
python3 tools/launch_isaac_s1.py
python3 tools/launch_isaac_s2.py
```

S1 runs the bounded complete contract validation. The base/generic S2 launcher
runs the canonical S1 robot
scene with the existing processor/IK and three previews (two policy wrist roles
plus a presentation-only scene feed); it is simulation-only and does not record D1.
Its selected sensitivity remains toggle normal 2x / precise 0.5x. This base path
is not the primary operator workflow or the next physical acceptance target.

Temporary checks also use the project launchers:

```sh
python3 tools/launch_isaac_s2.py --smoke
python3 tools/launch_isaac_s2.py --xr-smoke
python3 tools/launch_isaac_s1.py --combined-preview-test 3000
python3 tools/launch_isaac_s1.py --combined-preview-test 40 --preview-control
```

The combined diagnostic uses the upstream standalone CloudXR profile without a
physical client, on the real robot/sensor/preview path. Its presentation watermark
and witness cameras are test-only. `--preview-control` intentionally disables
isolation and must never be used as a normal teleop launch. Both raw and Camera
buffers are inspected on every captured tick, including reset settling. No test
uses hardware PIPER commands. Close test sessions before normal teleop.

## Frozen materialization

```sh
python3 tools/materialize_isaac1103.py --check
```

For a new installation use the same script without `--check` and an empty `--root`.
The base CPython path in `configs/environments/isaac1103/ENVIRONMENT.yaml` must exist.
It reproduces an exact lock-only amendment to the upstream commit, then frozen
materialization. It refuses to overwrite an existing installation. A subsequent
check must print `Would make no changes`. No manual pip repair is permitted.

## Rollback

Keep the legacy environment, source and spec intact. Stop the current simulation
normally, then use the same project checkout and explicit legacy selection:

```sh
cd ~/vla_infrastructure
./run-vr --stack legacy
```

This is the operator rollback/debug path, not the current acceptance target.
Base S1/S2 rollback checks remain available separately:

```sh
python3 tools/launch_isaac_s1.py --stack legacy
python3 tools/launch_isaac_s2.py --stack legacy --smoke
python3 tools/launch_isaac_s2.py --stack legacy
```

This selects the old exact SDK and separate per-user cache without checking out
history, reinstalling dependencies or altering Gate B/core. New canonical Scene
Partitions presentation is not enabled for legacy. Rollback retains the preexisting
processor v3 code; it is a **runtime rollback**, not a return to historical processor
v1 behavior. Do not advertise the old SDK as providing the new anti-recursion guarantee.

## Historical migration bundle distribution

The following records the migration release branch/bundle distribution. For a
current operator run use your current master checkout and the operator guide;
this historical bundle is not the final-master acceptance target.

After the migration commit is published as the local release bundle, an existing
clean project checkout can obtain the exact tested branch without accessing another
account's home:

```sh
cd ~/vla_infrastructure
git fetch /data/vla-infrastructure/releases/isaac1103-production.bundle codex/isaac1103-production
git switch -c isaac1103-production FETCH_HEAD
```

Keep any local work on its current branch; Git will refuse conflicting uncommitted
changes. For an account without a project checkout, clone that bundle into its own
`~/vla_infrastructure` using branch `codex/isaac1103-production`. The commands above
then use that account's private `/data/<username>` state. The shared release bundle
contains project code/config/evidence references, not SDKs or per-frame captures.
