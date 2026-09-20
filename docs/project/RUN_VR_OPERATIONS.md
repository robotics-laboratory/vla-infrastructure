# Canonical Quest → Isaac VR operations

`./run-vr` is the operator entrypoint. `./run-vr diag` runs the same implementation
with diagnostics. Dataset recording is not implemented; S2 physical acceptance
and D1 remain unresolved.

## Start and qualify

From your implementation checkout, after accepting the NVIDIA Isaac Sim and
CloudXR EULAs:

```sh
export OMNI_KIT_ACCEPT_EULA=Y
export ISAACLAB_CXR_ACCEPT_EULA=1
./run-vr
```

Use the exact client URL and headset setup in the canonical config's
`cloudxr_web_client`. The host prints these instructions; browser localStorage is
owned by the headset. The physical launch requires tracking from both controllers.
Client start/stop controls teleoperation activity. Client reset resets the scene,
processor and IK and requires fresh rebase. Disconnect holds targets; reconnect
rebases. Host Ctrl-C preserves available reports and exits 130, never PASS.

```sh
./run-vr --dry-run
./run-vr diag --dry-run
./run-vr --smoke
./run-vr diag --smoke
./run-vr diag --xr-smoke
./run-vr --stack legacy
```

Dry-run verifies installed pins and selected assets and writes provenance/config,
without starting simulation. Smoke is a bounded no-client run with an injected
reset. XR smoke additionally exercises Kit XR; diagnostic XR smoke enables
synthetic presentation-button checks. Neither implies physical Quest acceptance.
Use [the physical worksheet](GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md) for acceptance
of the canonical run mode. Diagnostic qualification uses the same execution profile.

## Ownership and launch path

| Source | Owns |
|---|---|
| [Normative model](../NORMATIVE_MODEL.md) and policies | Static rules |
| [Resolved contract](../../configs/resolved_contract.yaml) | Selected facts, `isaac_vr` execution profile, environment, gate state |
| [Shared S2 config](../../configs/isaac61_s2_runtime.yaml) | Processor revision, clutch/gripper, tracking/rebase and teleop dependency pins |
| [Canonical VR config](../../configs/isaac61_vr_runtime.yaml) | Selected stack/profile, controls/sliders, scene/bases/home, camera extrinsics, XR/recenter, preview layout, drive/contact tuning, runtime guards |
| [Environment specification](../../configs/environments/isaac1103/ENVIRONMENT.yaml) | Reproducible SDK/environment installation |
| [Experimental asset lab](../../configs/experiments/robosyn_asset_lab.yaml) | Explicit optional external asset manifest and experimental classification |

Read current numeric values and button mappings from these configs. This guide
intentionally does not maintain another table of settings. The selected scene
preview camera is outside the canonical D0 wrist-camera inputs.

```text
./run-vr [diag]
  -> tools/launch_isaac_vr.py
  -> tools/run_isaac_s1.py --vr-runtime --s2-mode run|diagnostic
  -> tools/isaac_vr_runtime.py::run_vr / VRRuntime
  -> tools/isaac_s2_runtime.py::run_s2
```

The launcher generates the lower-level S1 `runtime.yaml` with private asset paths.
The VR builder reads the canonical composition, and the single S2 loop applies its
selected controls over the shared S2 semantics. There is no recursive YAML merge.
Both modes share scene/controllers/processor/IK/cameras/XR and reset/reconnect/shutdown.
The default profile has no RoboSyn checkout or asset-manifest dependency.

## Modes and flags

RUN keeps lifecycle, tracking and finite-data handling, processor holds/rebases,
IK limits, required camera availability/progression, Scene Partitions and fatal
error propagation. Camera health reads source-owned frame counters and buffer
shape/type; only counters cross to CPU. A bounded stale tolerance is configured in
`validation`; reset starts a new sequence epoch. This catches stalled acquisition,
not content frozen upstream while its source counter falsely advances. Static
images are valid; image hashes alone do not prove source freshness either.

DIAG adds strict frame progression, image hashes, per-step/nested performance
logs with mean/percentiles/max, GPU sampling, transition/tracking windows, slider
statistics and presentation counters. Bounded preview PPM capture is opt-in.

Both modes support `--stack`, `--profile`, `--cloudxr-mode`, `--state-root`,
`--hud-on-start`, `--max-control-steps`, `--dry-run`, `--smoke` and `--xr-smoke`.
Diagnostic-only flags fail in run mode with a `./run-vr diag ...` suggestion:
`--performance-window-steps`, `--performance-warmup-steps`,
`--capture-preview-evidence`, `--scene-preview`, `--preview-isolation` and
`--preview-cameras`. Preview overrides are qualification experiments; physical
acceptance uses canonical defaults. Select the asset lab explicitly:

```sh
./run-vr diag --profile robosyn_asset_lab --dry-run
```

It verifies its own pinned external checkout/assets and has no S2 acceptance claim.
`--stack legacy` is the explicit rollback/debug path with its pinned environment
and preview limitations recorded in the config; it is not the current S2 target.
The old generic S2 wrapper was removed; low-level S1 `--teleop` remains internal.

## Artifacts and troubleshooting

The launcher prints `VR output:` under the current user's private state root.
`--state-root` may select an absolute, current-UID directory outside the repository.
Every run retains:

- `run_manifest.json`: schema/run id/mode, exact top-level argv and child command,
  Git commit and full tracked/untracked status/list, stack/profile/pins, generated
  config and source hashes, processor revision and effective controls/preview.
- `runtime.yaml`: generated lower-level runtime configuration.
- `result.json`: runtime result and process/shutdown status, when the child reaches
  reporting. Early failures may leave only manifest/config; nonzero exit remains fatal.

DIAG also retains `stdout.log` and `performance.jsonl`. Optional bounded camera
captures live under `camera_feed_diagnostics/`; scene snapshots use the supplied
path. RUN does not create the diagnostic bundle. Retain a completed physical
worksheet and observed shutdown facts alongside the manifest for human evidence.

If a pin check fails, restore the declared clean SDK/model installation rather than
patching packages. A missing RoboSyn checkout affects only the asset-lab profile.
If the CloudXR port is occupied, its owner must stop it normally. Use
`--cloudxr-mode existing` only with your own server and readable current-UID IPC
under the selected state root. If feeds fail freshness or partitions fail, fix the
source/setup and restart; do not disable guards. Restart for camera teardown or XR
recreation. Inspect `result.json` and use diagnostic mode for detailed investigation.

## Feature development

Keep long-lived implementation worktrees under `.worktrees/`; this branch uses
`.worktrees/run-vr-primary`. Keep runtime state outside the checkout.

Experimental shared implementation → `./run-vr diag` → automated + physical
qualification → promote canonical config/status → `./run-vr` inherits it → future
record consumer inherits the same base semantics. Promotion changes selection,
not Python ownership. Never copy control loops or builders across modes.
Recording will attach at the shared observation/action/native/outcome boundary;
there is currently no record command, dataset writer or D1 acceptance claim.
