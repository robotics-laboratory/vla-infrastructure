# Cross-user XR client and configuration provenance — 2026-09-17

This is experimental S2 diagnostic evidence. It does not accept or change a gate.

No Isaac, teleop, or CloudXR process was started for this investigation. No
running process was signalled or modified. Docker and root access were not used.

## Finding

The strongest remaining explanation for the user-specific camera recursion is
different headset WebXR client state, with a concrete version-selection defect
in the project instructions:

- `tools/quest_xr_diagnostics.py` advertised the unversioned
  `https://nvidia.github.io/IsaacTeleop/client` URL.
- NVIDIA currently redirects that URL through `client/stable/` to immutable
  client `v1.3.131`.
- The host environment is pinned to `isaacteleop==1.4.98rc1` and CloudXR
  runtime `6.2.1`.
- NVIDIA's v1.3.131 release notes identify CloudXR Runtime/Web SDK 6.2.0. The
  1.4 release series moves both SDKs to 6.3.0.
- The known-good user's CloudXR native logs report `client: 6.3.0`, protocol
  `6.1.0`, and packed stream `4096x4032`. Thus the working headset did not use
  the currently advertised stable 1.3 Web SDK path.
- NVIDIA issue #585 explicitly added versioned client URLs to prevent users
  from connecting with the wrong WebXR client version.
- NVIDIA's 1.4 client stores settings in global and per-project browser
  `localStorage`; the UI's `Reset to defaults` clears both. This state exists
  in the headset browser and is neither passed by the host launcher nor tracked
  by this repository.

The exact colleague client build and saved browser settings are not present in
the project stdout logs. The colleague's native CloudXR logs and browser state
are under `/home/blackfire/.cloudxr` and the headset respectively. Unix mode
`0700` prevents read access to that home, and this investigation intentionally
did not use root. Therefore client mismatch is the leading, testable cause, not
yet a completed physical proof.

## What is already ruled out

- The old feed-owned Replicator feedback path is disabled. Both colleague runs
  report `source=isaac_lab_camera_rgba`.
- The later colleague run used a saved local patch that attached both panels to
  XR only. Recursion was reported both before and after that patch, so the patch
  is not the cause. It was not committed or pushed.
- Post-XR diagnostic samples from the user's run remain clean at both the
  Isaac camera tensor and CPU upload boundaries through publication 600; every
  source/upload RGBA hash pair is identical.
- Replacing the user's complete Kit/XDG state with an exact copy of the
  colleague's state did not contaminate either boundary. The two copies had 254
  files and `diff -qr` found no differences immediately after copying.
- Good-user, bad-colleague, and cache-swap runs use the same Kit 110.1.2,
  kernel 210.1.11, CloudXR runtime 6.2.1, CUDA device 0, 2048x1792 per-eye XR
  swapchains, two XRSceneViews, and the same camera/panel dimensions.
- There are no post-session warnings or errors in the relevant Kit logs that
  distinguish the good and bad cases.

## Configuration flow and Git ownership

| Layer | Effective source | Passed by | Git / origin status |
|---|---|---|---|
| Scene, wrist camera pose, panel placement, R3 and speed slider | `configs/experiments/robosyn_vr_demo.yaml` | Demo runtime reads YAML | Tracked; present in `origin/experiment/robosyn-vr-demo` |
| Camera source and SceneUI upload | `tools/isaac_robosyn_vr_demo.py` | Demo runtime | Tracked; working file matched origin before this fix |
| XR/profile arguments | `--xr --s2-cloudxr-profile cloudxrjs --s2-reset-step 0 --s2-require-tracking` | `tools/launch_isaac_robosyn_vr_demo.py` | Tracked; present in origin |
| Kit portable state | `/data/vla-infrastructure/cache/robosyn-vr-demo/users/uid-<uid>/kit` | `--kit_args --portable-root ...` | Outside repository; never pushed |
| Shader/Warp/XDG cache | `/data/vla-infrastructure/cache/robosyn-vr-demo/users/uid-<uid>/xdg` | `XDG_CACHE_HOME` | Outside repository; never pushed |
| CloudXR device profile | pinned `cloudxrjs-cloudxr.env` (`auto-webrtc`, push devices off, pose wait off) | Host runtime passes env file to upstream lifecycle | Upstream checkout is pinned; generated resolved env is local |
| CloudXR install, generated env, certificates, native logs | `$HOME/.cloudxr` | Upstream `CloudXRLauncher(Path.home() / ".cloudxr")` | Outside repository and not isolated by the project launcher |
| WebXR client URL | Manually opened in headset | Operator; not a host process argument | A recommendation can be tracked; loaded client is external |
| WebXR settings/cache | Headset browser cache, URL parameters and per-project `localStorage` | Web client | Outside repository; never pushed |

The launcher deliberately inherits `HOME`, `XDG_CONFIG_HOME`, and
`XDG_DATA_HOME`. It overrides only `XDG_CACHE_HOME`, `UV_CACHE_DIR`,
`UV_PROJECT_ENVIRONMENT`, `PYTHONPATH`, and `PYTHONNOUSERSITE`, and supplies a
per-UID Kit portable root. Consequently copying Kit/XDG does not copy
`$HOME/.cloudxr` or any headset state.

## Git state before this local fix

- Branch: `experiment/robosyn-vr-demo`
- Local and directly queried remote head:
  `ca885b3823d5146cbd3702a8c37fcafaf9c5cce4`
- The four runtime/config files checked byte-for-byte equal to origin.
- `origin/master` does not contain the demo launcher/config; a colleague on
  master cannot receive the experiment through a normal pull.
- The colleague's 20:57 run contained `scene_view_attachment`, which is absent
  from every Git commit. `/tmp/robosyn_camera_fix.patch`, timestamped four
  minutes before that run, contains the exact XR-only experiment. This explains
  the source divergence but not the recursion, which also occurred before it.

## Fix applied locally

- Pin the operator-facing URL to
  `https://nvidia.github.io/IsaacTeleop/client/release-1.4.x/`.
- Tell the operator to select `Isaac Lab`, reset stored defaults, and select the
  Quest 3 profile before connecting.
- Print this URL and setup rule from the normal demo launcher.
- Write `launch_manifest.json` before the child process starts. It records the
  repository branch/commit/tracked dirty state, SHA-256 of runtime inputs,
  effective command, UID, Kit/XDG/CloudXR paths, and the fact that browser state
  is not passed by the host.

This fix is intentionally local and is not pushed.

## Required physical discriminator

On the colleague's next permitted run:

1. Use the exact experiment branch and require an empty tracked diff.
2. Open only `https://nvidia.github.io/IsaacTeleop/client/release-1.4.x/`.
3. Select `Isaac Lab`, press `Reset to defaults`, select `Quest 3`, and connect.
4. Preserve `launch_manifest.json`, `stdout.log`,
   `camera_feed_diagnostics/manifest.json`, and the native
   `~/.cloudxr/logs/cxr_server.*.log` line containing `client:`.
5. Record whether the headset panel is recursive at the same publication time.

If the versioned/reset client removes recursion while source/upload hashes stay
clean, the cause is confirmed as headset client build/state. If recursion
remains, the next A/B boundary is the colleague's `$HOME/.cloudxr`; Kit/XDG
does not need another swap.

## Upstream audit

CAPABILITY / GATE: experimental Isaac S2 XR presentation reproducibility; no
gate acceptance.

PINNED UPSTREAM CANDIDATES: Isaac Lab `913ac53f`, Isaac Sim `6.0.1.0`,
isaaclab_teleop `0.8.0`, IsaacTeleop `1.4.98rc1`, CloudXR runtime `6.2.1`, and
the NVIDIA-hosted Isaac Teleop 1.4.x WebXR client.

WHAT UPSTREAM ALREADY OWNS: CloudXR runtime launch, OpenXR bridge, SceneUI
composition, browser client, per-project client settings and versioned client
hosting.

EXACT REMAINING GAP: the project exposed a floating client URL and did not
persist host-side source/config provenance before interrupted physical runs.

PROCESSOR / CONFIG / ADAPTER REQUIRED: one pinned operator URL plus a bounded
launcher provenance manifest. No camera, renderer, transport or compositor
replacement is required.

ENVIRONMENT IMPACT: no dependency or runtime pin changes. One small JSON file
is added to each run directory before Isaac starts.

WHY NO PROJECT FRAMEWORK IS NEEDED: the existing launcher already owns the
effective command and host paths, and upstream owns the WebXR client.

## Primary upstream references

- NVIDIA Isaac Teleop issue #585, versioned client URL rationale:
  https://github.com/NVIDIA/IsaacTeleop/issues/585
- NVIDIA Isaac Teleop 1.4 release notes, CloudXR 6.3 and resettable client
  settings: https://github.com/NVIDIA/IsaacTeleop/issues/1065
- Versioned 1.4.x client:
  https://nvidia.github.io/IsaacTeleop/client/release-1.4.x/
- Stable redirect and v1.3.131 client:
  https://nvidia.github.io/IsaacTeleop/client/stable/
