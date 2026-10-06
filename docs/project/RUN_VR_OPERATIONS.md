# Canonical Quest → Isaac VR operations

`./run-vr` is the operator entrypoint. `./run-vr diag` runs the same implementation
with diagnostics. `./run-vr record` writes a native NVIDIA Episode Recorder HDF5 V2
state/action/provenance artifact. It does not create a D1 dataset; S2 physical
acceptance and D1 remain unresolved.

RECORD starts in `WAITING` with no demonstration or episode. On the existing
single controller pipeline, press **X** (left primary) to Start, **Y** (left
secondary) to Stop, then **X** to select Save or **B** (right secondary) to Discard.
After selecting Save, explicitly classify the task with **X** for success, **Y** for
failure, or **B** for incomplete. Each press is a rising edge; release a button
before using it in another state. In particular, holding X after Save cannot
select success. Stop seals the
source recording before review while XR input stays live. The state and button
mapping are printed as `human_recording_state` events and the final state is
included in the run report. Physical Quest visibility of these events or a
headset menu has not been qualified. A saved demonstration gets a separate
`saved_demos/<demo_id>.json` index beside the recording directory only after
task outcome selection. It records separate `save_classification: saved` and
`task_outcome: success|failure|incomplete`, ordered technical episode directories,
the source profile, committed row/schema identity, control boundaries and a
`saved_and_classified` lifecycle disposition without changing canonical episode manifests.
Save means operator retention only; a saved failure or incomplete demo remains
saved. None of these outcomes establishes dataset admission.
Discard leaves canonical episode artifacts for forensic inspection, writes a
separate `discarded_demos/<demo_id>.json` disposition, and publishes no saved
index. An interrupted active demonstration similarly gets an
`interrupted_demos/<demo_id>.json` disposition, including when review or outcome
classification is interrupted. Discard and completed classification run a state-only
scene/device/processor/IK reset
and returns to `WAITING`; another Start creates a new causal scope. Disconnect
seals an active episode conservatively and never saves the demonstration.
These buttons replace RUN/DIAG's presentation controls. RECORD keeps previews
off and does not currently consume the R3 recenter button; RUN/DIAG retain the
configured preview, backdrop and recenter controls.

In RECORD, tracked intentional clutch engagement, hold and release rebase are
causal action rows in the same technical episode as motion. Both arms may have
different transitions in one row. The recorded training action is the post-IK,
preclip float32[14] label in degrees/millimetres, with per-arm transition
provenance. The original native preclip and applied clipped command in
radians/metres, residual and saturation are stored separately. Tracking loss,
tracking recovery rebase, sensitivity switches, session/reference changes and
missing XR receipts remain gaps. After at least one committed transition, a gap
causally seals the current episode before the next physics step; the CloudXR session
stays open and the next control boundary starts a new, independently finalized
artifact. Without `--recordings-root`, its sibling directory is suffixed
`-<demo_id>-episode_000001`, etc.; with that option, it is placed under the demo ID.
The closed HDF and terminal successor remain non-finalized until a single bounded
filesystem worker verifies, hashes and publishes them after the next episode's
first committed transition. Stop/shutdown waits for that work; a worker failure
blocks further recording and saved-demo publication. An unfinished artifact keeps
a non-finalized state marker.
The first episode of the first demonstration remains at the requested output
directory; later demonstrations use unique sibling directories. With
`--recordings-root`, the first episode remains `<root>/episode_000000`; later
episodes use `<root>/<demo_id>/episode_000001`, etc.
The run report lists every directory in `recording_episodes`. These segments
are independent technical episodes inside one Start-to-Stop demonstration.
Tracking gaps do not open review. The same
session-level `performance.jsonl` and timing observer continue across every
episode and gap; episode closure never closes or replaces that log. Rejected
tracking ticks still apply the safe processed command, including motion from
the opposite valid arm, without rearming processor tracking or recording a row.
Tracking recovery emits its natural rebase before the next motion decision can
be recorded. A future no-physics pause/resume may avoid segmentation, but it
requires separate XR/physics validation.

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
processor and IK and requires fresh rebase. RUN/DIAG disconnect holds targets;
reconnect rebases. A RECORD disconnect interrupts the active demonstration and
ends the loop rather than resuming it. Host Ctrl-C preserves available reports
and exits 130, never PASS.

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
without starting simulation. RUN/DIAG smoke is a bounded no-client run with an
injected reset. Plain RECORD smoke checks only recorder capture/discard/close
and commits no rows; use injected actions for committed-transition QA.
XR smoke additionally exercises Kit XR; diagnostic XR smoke enables
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

Read selected numeric values and RUN/DIAG presentation mappings from these configs.
RECORD's X/Y/B lifecycle mapping is described above and implemented in the shared
S2 loop and `RecordingLifecycle`. This guide
intentionally does not maintain another table of settings. The scene sensor `demo_scene` maps explicitly to canonical
`observation.images.scene`, alongside `left_wrist` and `right_wrist`. Its production
does not depend on preview visibility.

```text
./run-vr [diag|record]
  -> tools/launch_isaac_vr.py
  -> tools/run_isaac_s1.py --vr-runtime --s2-mode run|diagnostic
  -> tools/isaac_vr_runtime.py::run_vr / VRRuntime
  -> tools/isaac_s2_runtime.py::run_s2
     -> RUN/DIAG/human RECORD: shared teleoperation loop
     -> RECORD smoke: recorder lifecycle or injected-transition QA

./run-vr replay
  -> tools/launch_isaac_vr.py
  -> tools/run_isaac_s1.py::main (early replay branch)
  -> tools/isaac_vr_replay.py::replay_from_snapshot
```

The launcher generates the lower-level S1 `runtime.yaml` with private asset paths.
The VR builder reads the canonical composition, and the single S2 loop applies its
selected controls over the shared S2 semantics. There is no recursive YAML merge.
RUN/DIAG share scene/controllers/processor/IK/cameras/XR and reset/reconnect/shutdown.
Human RECORD reuses control and native actuation while using snapshot observations
and state-only recording. REPLAY opens the recorded snapshot before current scene
construction and runs without the S2 device/control loop.
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
RUN and RECORD also accept `--performance-window-steps` and
`--performance-warmup-steps`; supplying either enables the existing S2 timing
logger without diagnostic camera observers or GPU subprocess sampling.
`--recordings-root` selects the parent of numbered episodes and excludes
`--recording-dir`. `--run-dir` selects an exact new run-bundle directory; without
it, the existing timestamped directory under `<state-root>/runs/` is retained.
`--xr-resolution-scale` is an explicit RECORD-only Isaac61 render-buffer override.
It does not alter `xr_presentation.scale`, camera dimensions or offline RGB.
Diagnostic-only flags fail in run mode with a `./run-vr diag ...` suggestion:
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

The human RECORD report has an open bookkeeping defect: review, outcome-selection
and reset branches can skip camera counters while the final PASS check counts
every loop iteration. A normal Stop/Save/classify workflow can therefore yield
`failed` and exit 1 even when episode artifacts were published. This needs a code
fix; a saved artifact does not turn a failed report into qualification evidence.
Episode startup also has incomplete rollback after HDF acquisition if later
manifest publication fails. Both defects remain implementation work under the
[recording remediation plan](../plans/ISAAC_VR_RECORDING_REMEDIATION.md).

DIAG and explicitly profiled RUN/RECORD also retain `stdout.log` (combined stdout
and stderr) and `performance.jsonl`. The launcher prints the run, recording, result
and performance paths on exit. Optional bounded camera
captures live under `camera_feed_diagnostics/`; scene snapshots use the supplied
path. Unprofiled RUN does not retain the stdout/performance logs. Retain a
completed physical worksheet and observed shutdown facts alongside the manifest
for human evidence.

If a pin check fails, restore the declared clean SDK/model installation rather than
patching packages. A missing RoboSyn checkout affects only the asset-lab profile.
If the CloudXR port is occupied, its owner must stop it normally. Use
`--cloudxr-mode existing` only with your own server and readable current-UID IPC
under the selected state root. If feeds fail freshness or partitions fail, fix the
source/setup and restart; do not disable guards. Restart for camera teardown or XR
recreation. Inspect `result.json` and use diagnostic mode for detailed investigation.

## RECORD timing and state-only reset

For a later physical Quest recording, connect the headset normally and stop with
Ctrl-C. This command does not establish physical acceptance by itself:

```sh
ROOT="/data/$(id -un)/vla-runtime/manual-record/$(date +%Y%m%dT%H%M%S)"
./run-vr record \
  --state-root "$ROOT/run/host" \
  --run-dir "$ROOT/run" \
  --recordings-root "$ROOT/recordings" \
  --xr-resolution-scale 0.4 \
  --performance-warmup-steps 60 --performance-window-steps 300
```

This uses the EULA acceptance established above. Choose a new timestamp for each
launch, including dry-run: existing run bundles are never overwritten. The layout is:

```text
<ROOT>/
  run/
    performance.jsonl
    result.json
    stdout.log
    run_manifest.json
    runtime.yaml
    host/                 # existing Kit/CloudXR, cache, asset and temporary state
  recordings/
    episode_000000/        # first segment of the first demonstration
    <first-demo-id>/
      episode_000001/
      episode_000002/
    <next-demo-id>/
      episode_000000/
    saved_demos/<demo_id>.json
    discarded_demos/<demo_id>.json
    interrupted_demos/<demo_id>.json
```

Every episode retains the normal native `session.hdf5`, `manifest.json`,
`recording_state.json`, terminal successor (for committed episodes), stage snapshot,
asset closure and visual provenance. Dry-run writes only config/provenance and
private directories; it cannot produce episode, performance or result artifacts.

During an actual human demo, explicitly Stop, Save and classify the human task
outcome. The saved `saved_demos/<demo_id>.json` keeps the ordered technical
episodes. Tracking gaps may split one successful human demo into multiple
`operator_stopped` technical episodes; keep each segment separate. Follow the
[materialization and admission workflow](../DATASET_MATERIALIZATION.md#human-demo-admission)
for projection, strict replay/RGB, one LeRobot output per segment and a final
demo-level decision. Save plus human task success does not admit training data:
the current physical Quest qualification is still unresolved.

### Pinned upstream XR resolution audit

The Isaac Sim 6.1 / Kit 110.3 installation's
`omni.kit.xr.core-109.1.0+00c488ae.lx64.r.cp312/include/omni/kit/xr/tokens/XRTokens.h`
defines `XRProfileSettingTokens::renderResolutionMultiplier` as
`profile/persistent/render/resolutionMultiplier` (lines 468–469).
The bundled `omni.kit.xr.ui.window.profile-109.0.0+00c488ae` implementation,
`omni/kit/xr/ui/window/profile/menu/xr_menu_resolution_frame.py` (lines 60–73),
binds that token to the stereo render-buffer multiplier, range 0.1–2.0.
Isaac Lab's pinned `apps/isaaclab.python.xr.openxr.kit` selects profile `ar`
(line 75), yielding the exact Carb path
`/persistent/xr/profile/ar/render/resolutionMultiplier`.
This agrees with NVIDIA's [XR settings reference](https://docs.omniverse.nvidia.com/xr/omniverse-spatial-docs/latest/server/03-xr-settings.html#resolution-and-rendering).
The CloudXR 6.2.1 transport remains unchanged.

The launcher supplies this path as a Kit command-line override, records it and its
requested value in `runtime.yaml` and `run_manifest.json`, then the child verifies
the Carb readback before scene construction and again after entering the XR
session. A mismatch fails the launch. The initial readback is retained as
`xr_render_runtime` in the run manifest and `xr_render` in each episode's session
metadata. Dry-run records configuration only; framebuffer dimensions and physical
Quest performance still require the manual run. World/spatial scale stays 1.0.

Reuse audit for this S2/D1 experiment: upstream Kit owns XR resolution; the existing
launcher owns state/config/log paths; NVIDIA Episode Recorder and the existing S2
loop own episode contents and segmentation. The only gaps are explicit CLI paths,
the render setting override and readback provenance. These are configuration and
small launch/runtime seams; environments, dependencies, processors and gate states
are unchanged. No new output framework or gate acceptance evidence is introduced.

Summarize the printed performance path with
`python tools/summarize_vr_performance.py <run-directory>/performance.jsonl`.
For the default state root, this selects the newest profiled RECORD run by timestamp:

```sh
python tools/summarize_vr_performance.py "$(printf '%s\n' /data/$(id -un)/vla-runtime/isaac-isaac61/runs/*-record-*/performance.jsonl | sort | tail -n 1)"
```

The dependency-free readout rejects malformed, incomplete or unmeasured logs.
It prints warmup-excluded control statistics, stage mean/p95, and separately
labelled non-additive nested stages. These are host timings without added CUDA
synchronization. `effective_hz` describes the control body and excludes logging
and inter-control work. `wall_effective_hz`, wall RTF and wall deadline statistics
use start-to-start intervals, including inter-control work and excluding the
interval crossing warmup. The instrumentation-write statistic excludes
summary/flush and timer overhead.
Blackfire's separate paired recorder benchmark remains the resource and recorder
overhead evidence owner. Unmeasured metrics must not be inferred as zero.

RECORD's environment reset shares native seed/object/robot/home reset, camera
bookkeeping and 25 physics settling integrations with RUN/DIAG. Once live RGB is
disabled for RECORD, it returns only the measured state boundary: the recorder
then captures immutable O_t through its existing Fabric/native path. It neither
requires a live camera capture nor reads RGB. After RECORD setup, settling uses
24 non-rendered steps and one final render/pump; this is not 25 control
transitions. The three dataset RenderProducts remain suspended. Ordinary RECORD
controls retain four integrations with F,F,F,T. Startup preflight before RECORD
setup and RUN/DIAG retain their existing per-step rendering and RGB observations.
No reset performance claim is made. A physical reset request still ends the
current recording episode; it does not bridge a committed transaction across reset.

Plain `record --smoke` checks only capture/discard/finalization and commits no
rows. Use the existing `--smoke --injected-actions --recording-benchmark` path for
bounded automated committed transitions, with `--benchmark-pair-id`,
`--benchmark-warmup-steps` and `--benchmark-measured-steps`. Performance window
size controls reporting, not run duration. The injected sweep stays bounded
around the initial state so long benchmarks do not accumulate into joint limits.

## Feature development

Use the assigned checkout/worktree at its intended commit. Keep long-lived
implementation worktrees under `.worktrees/` and runtime state outside the checkout.

Experimental shared implementation → `./run-vr diag` → automated + physical
qualification → promote canonical config/status → RUN and RECORD inherit the
selected shared control semantics. Promotion changes selection,
not Python ownership. Never copy control loops or builders across modes.
RECORD reuses that shared scene, XR, controller, processor, IK and native actuation
path. It exports one `stage_snapshot.usd`, records static scene from that snapshot,
and stores articulated robots, dynamic cubes, camera pose/intrinsics, SimTime and
the numeric D0 transition track through public NVIDIA Recordables. Each sample is
explicitly taken at O0 and after each four-substep control transition. Live canonical
RGB and preview panels are off in RECORD; no RGB is read, retained or uploaded.

`./run-vr replay --recording <session.hdf5> --episode 0` uses the unmodified NVIDIA
`SessionReader` and `EpisodeReplayer` with the USD pose backend. It disables the S2
decision loop, controller actuation and physics stepping. Add
`--render-cameras <output-dir>` to write 640x480 RGB images for every committed
observation and each of `left_wrist`, `right_wrist` and `scene` from synchronously
rendered replay state, with their materialization identities.
The native record artifact is not yet a final D0 observation dataset; canonical
three-camera images are produced at replay/materialization. Runtime round-trip
qualification remains pending manual validation outside the agent execution host.

For bounded automated injected-transition round-trip QA, choose a new private
directory and run these commands from the intended checkout. The second command
writes the strict replay report; this is not physical Quest or human-VR admission:

```sh
set -e
export OMNI_KIT_ACCEPT_EULA=Y ISAACLAB_CXR_ACCEPT_EULA=1
recording="$HOME/.local/state/piper-x/recordings/injected-$(date +%Y%m%dT%H%M%S)"
./run-vr record --smoke --injected-actions --injected-count 30 --recording-dir "$recording"
./run-vr replay --recording "$recording/session.hdf5" --episode 0 \
  --render-cameras "$recording/replay-renders" --replay-report "$recording/validation_report.json"
```

Pass only when `session.hdf5`, `stage_snapshot.usd`, and
`validation_report.json` exist. For this injected count, the replay report must
show `frames_applied: 30`, `physics_callbacks: 0`, `native_action_replay: false`,
`strict_policy: true`, every required group in `prepared_groups` and 30 applied
frames per group in `applied_group_frames`. It must retain 30 D0 observation IDs
and `d0.committed_count: 30`, plus 90 render entries covering every observation
and all three roles. The output count is three images per committed row; there
is no first/middle/last-only mode. Plain `record --smoke` produces no replayable
committed episode, and REPLAY rejects `--smoke` and XR/CloudXR options.

## Historical references

The [historical pre-canonical documentation audit](RUN_VR_DOCUMENTATION_AUDIT.md)
records baseline `6430dc1` / documentation commit `2e80d23`. Its retained launcher,
config and architecture statements are forensic history; current operation follows
the machine sources and launch path above.

## Observation capture availability

RUN/DIAG attempt one all-or-none three-camera capture after reset completion or
four control substeps. Scene capture remains active while previews are hidden.
Rejected bundles publish no observation identity; ordinary RUN retains its
configured camera-health/staleness policy. RUN keeps only the current GPU-backed
images and immutable identity/state; it does not record
actions or episodes. Consumers must use a successful current capture before the
next transition. RECORD instead captures native/Fabric state snapshots and
materializes the three camera roles offline; it does not publish live RGB captures.

Use canonical Kit rendering without `HEADLESS=1`. The pinned headless Kit path
can advance camera counters without pumping fresh pixels; the capture barrier
rejects it. A no-client `--smoke` run does not require headless rendering or Quest.
For capture validity and S1 scope, see the
[simulation policy](../SIMULATION_POLICY.md#three-camera-observation-boundary).

## In-memory decision boundary

For eligible RUN/DIAG decisions, the shared loop latches the qualified live
three-camera observation before one synchronous XR update. Human RECORD uses the
immutable scene-state snapshot at the same pre-action boundary. The owned input
receipt records both resolved controller tensor groups, the exact world transform,
session/reference/update epochs and matching upstream
request/result IDs. These are application provenance, not physical acquisition time.
The post-IK solution exposes immutable float32[14] preclip degree/mm labels and
separate original native radians/metres, clipped targets, residuals and saturation.
Native actuation never converts the float32 label back to radians.

`env.last_control_decision` and `env.prepared_control_transaction` expose the latest
eligible applied decision and validator preparation. They are cleared on each loop;
RUN aborts pending validator work on the next loop and never claims a committed
transition. RECORD buffers the pre-action snapshot, binds native actuation and
the successful successor, then persists only a completed causal commit through
the existing native recorder. The exact successor can become the next row's
pre-action observation without resampling. Its stored snapshot identities are
joined to offline RGB during materialization.

Control tick IDs count eligible attempts and never restart on reset/recenter.
Inactive sessions, invalid tracking and tracking/session/reference recovery
rebases retain existing RUN holds but are ineligible. Tracked intentional clutch
engagement, hold and release rebase are eligible transitions; release rebase
emits zero Cartesian delta. Reset discards the already-polled action; the next
loop acquires fresh input after the reset boundary. Recenter
invalidates the reference immediately and uses the existing hold/rebase path.
State, reference, session, update reuse or processor-generation mismatch rejects
application of a pending eligible solution.
