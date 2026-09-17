# Cross-user cache swap experiment

Date: 2026-09-17

## Setup

- Stopped all Isaac/teleop processes owned by `ebulochkin`.
- Preserved the original `uid-1006` portable state at:
  `/data/vla-infrastructure/cache/robosyn-vr-demo/users/uid-1006.backup-20260917T161950Z`
- Preserved the incomplete unprivileged copy attempt at:
  `/data/vla-infrastructure/cache/robosyn-vr-demo/users/uid-1006.partial-20260917T162117Z`
- Used `alpine:3.20` as root with the per-user cache directory bind-mounted.
- Copied `uid-1011/kit` and `uid-1011/xdg` to a new `uid-1006` and changed the copied ownership to UID/GID 1006.
- Did not copy transient `uid-1011/tmp` files or locks.

## Copy verification

- Source file count: 254.
- Destination file count: 254.
- `diff -qr` reported no content differences for either `kit` or `xdg` immediately after the copy.

## Test run

Run directory:

`/data/vla-infrastructure/cache/robosyn-vr-demo/runs/20260917T162253509123Z-dual_cube_to_matching_plates-hud-on`

Observed runtime state:

- CloudXR/OpenXR session started.
- Both controllers reached `motion`.
- Both wrist cameras remained valid.
- Diagnostic publications 1, 30, 120, 300, and 600 were captured.
- Every captured source/upload pair had identical RGBA SHA-256 values.
- Visual inspection of publication 600 for both cameras showed clean robot wrist views without camera-panel recursion.

## Interpretation

Replacing the server-side Kit and XDG persistent state with an exact copy of the colleague's state did not introduce recursion into the Isaac camera tensor or the CPU-staged SceneUI upload image. If recursion is visible in the headset during this run, it is introduced after the upload boundary, with the CloudXR runtime/session or headset client/compositor being the remaining boundary.

## Remaining observation

Record whether recursion was visible in the headset during this exact run. This distinguishes a server-side cache hypothesis from CloudXR/home-directory or headset-client state.

## Restore procedure

Stop Isaac and CloudXR before restoring. Preserve the experiment copy, move the current `uid-1006` aside, then rename `uid-1006.backup-20260917T161950Z` back to `uid-1006`.

## Restoration performed

The original state was restored on 2026-09-17 by renaming the untouched full backup back to `uid-1006`. The tested colleague-cache state was preserved at:

`/data/vla-infrastructure/cache/robosyn-vr-demo/users/uid-1006.colleague-cache-experiment-20260917T163019Z`

After restoration, `uid-1006`, `kit`, and `xdg` were owned by `ebulochkin:ebulochkin`; the restored state occupied 563 MiB. No Isaac, teleop, or CloudXR process was running.
