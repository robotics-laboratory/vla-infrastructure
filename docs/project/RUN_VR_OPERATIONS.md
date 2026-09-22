# Canonical Quest → Isaac VR operations

`./run-vr` is the operator entrypoint. `./run-vr diag` runs the same implementation
with diagnostics. `./run-vr record` writes a native NVIDIA Episode Recorder HDF5 V2
state/action/provenance artifact. It does not create a D1 dataset; S2 physical
acceptance and D1 remain unresolved.

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
./run-vr --xr-smoke
./run-vr diag --xr-smoke
./run-vr record --smoke --max-control-steps 30
./run-vr replay --recording /private/state/recordings/<run>/session.hdf5 --episode 0
./run-vr --stack legacy
```

Dry-run verifies installed pins and selected assets and writes provenance/config,
without starting simulation. Smoke is a bounded no-client run with an injected
reset. XR smoke additionally exercises Kit XR; diagnostic XR smoke enables
synthetic presentation-button checks. Neither implies physical Quest acceptance.
Use [the physical worksheet](GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md) for acceptance
of the canonical run mode. Diagnostic qualification uses the same execution profile.

## Multi-episode recording and replay

Record to a chosen dataset root:

```sh
./run-vr record --recording-dir /data/my_dataset
```

The existing NVIDIA/Isaac XR main overlay remains authoritative: press its Start
to begin each episode. During recording, Quest Y opens the small recording menu;
X selects Save and B selects Discard. Either choice resets the scene, stops teleop,
and returns to the existing main overlay, where Start is required again. Main Reset,
disconnect, and Ctrl-C discard only the current incomplete episode; previously saved
episodes remain intact.

Saved recordings are published atomically as `episode_000000`, `episode_000001`,
and so on. Replay needs only one such path:

```sh
./run-vr replay /data/my_dataset/episode_000000
```

Replay uses the existing main Start and Reset lifecycle: Start plays state frames;
Reset reapplies frame 0 and requires Start again. Replay applies no controller
actions and performs no physics steps. This workflow is simulated/tested only until
the relevant physical gate has registered evidence.

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
intentionally does not maintain another table of settings. The scene sensor `demo_scene` maps explicitly to canonical
`observation.images.scene`, alongside `left_wrist` and `right_wrist`. Its production
does not depend on preview visibility.

```text
./run-vr [diag|record|replay]
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

RUN, DIAG and RECORD support `--stack`, `--profile`, `--cloudxr-mode`, `--state-root`,
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
RECORD reuses that shared scene, XR, controller, processor, IK and native actuation
path. It exports one `stage_snapshot.usd`, records articulated robots, dynamic cubes,
SimTime and the numeric D0 transition track through public NVIDIA Recordables. Each
sample is explicitly taken at O0 and after each four-substep control transition. Live
canonical RGB and preview panels are off in RECORD; no RGB is read, retained or uploaded.

`./run-vr replay --recording <session.hdf5> --episode 0` uses the unmodified NVIDIA
`SessionReader` and `EpisodeReplayer` with the USD pose backend. It disables the S2
decision loop, controller actuation and physics stepping. Add
`--render-cameras <output-dir>` to write first/middle/last 640x480 RGB images for
`left_wrist`, `right_wrist` and `scene` from synchronously rendered replay state.
The native record artifact is not yet a final D0 observation dataset; canonical
three-camera images are produced at replay/materialization. Runtime round-trip
qualification remains pending manual validation outside the agent execution host.

For the bounded manual round-trip, choose a new private directory and run this
exact command from the branch checkout (the second command writes the only
machine-readable validation report):

```sh
set -e
export OMNI_KIT_ACCEPT_EULA=Y ISAACLAB_CXR_ACCEPT_EULA=1
recording="$HOME/.local/state/piper-x/recordings/manual-$(date +%Y%m%dT%H%M%S)"
./run-vr record --smoke --max-control-steps 30 --recording-dir "$recording"
./run-vr replay --smoke --recording "$recording/session.hdf5" --episode 0 \
  --render-cameras "$recording/replay-renders" --replay-report "$recording/validation_report.json"
```

Pass only when `session.hdf5`, `stage_snapshot.usd`, and
`validation_report.json` exist; the report must show at least 30 applied frames,
unchanged `physics_steps_before/after`, `native_action_replay: false`, valid D0
observation/action indexing, and nine first/middle/last role images.

## Historical references

The [historical pre-canonical documentation audit](RUN_VR_DOCUMENTATION_AUDIT.md)
records baseline `6430dc1` / documentation commit `2e80d23`. Its retained launcher,
config and architecture statements are forensic history; current operation follows
the machine sources and launch path above.

## Observation capture availability

All three cameras publish one boundary after reset completion or four control
substeps. Scene capture remains active while previews are hidden. RUN keeps only
the current GPU-backed images and immutable identity/state; it does not record
actions or episodes. Consumers must use a successful current capture before the
next transition.

Use canonical Kit rendering without `HEADLESS=1`. The pinned headless Kit path
can advance camera counters without pumping fresh pixels; the capture barrier
rejects it. A no-client `--smoke` run does not require headless rendering or Quest.
For capture validity and S1 scope, see the
[simulation policy](../SIMULATION_POLICY.md#three-camera-observation-boundary).

## In-memory decision boundary

The shared loop latches the qualified three-camera observation before one synchronous
XR update. Its owned input receipt records both resolved controller tensor groups,
the exact world transform, session/reference/update epochs and matching upstream
request/result IDs. These are application provenance, not physical acquisition time.
The post-IK solution exposes immutable float32[14] preclip degree/mm labels and
separate original native radians/metres, clipped targets, residuals and saturation.
Native actuation never converts the float32 label back to radians.

`env.last_control_decision` and `env.prepared_control_transaction` expose the latest
eligible applied decision and validator preparation. They are cleared on each loop;
RUN aborts pending validator work on the next loop and never claims a committed
transition. A future recording consumer must freeze camera pixels at the existing
observation boundary, bind the native write and successful successor, then commit.
No episode buffer or recording storage is installed.

Control tick IDs count eligible attempts and never restart on reset/recenter.
Inactive sessions, invalid tracking, initial recovery and release/rebase frames
retain existing RUN holds but are ineligible. Reset discards the already-polled
action; the next loop acquires fresh input after the reset boundary. Recenter
invalidates the reference immediately and uses the existing hold/rebase path.
State, reference, session, update reuse or processor-generation mismatch rejects
application of a pending eligible solution.
