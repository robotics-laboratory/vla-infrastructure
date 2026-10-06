# Canonical Quest → Isaac VR operations

`./run-vr` is the operator entrypoint. `./run-vr diag` runs the same implementation
with diagnostics. `./run-vr record` writes a native NVIDIA Episode Recorder HDF5 V2
state/action/provenance artifact. It does not create a D1 dataset; S2 physical
acceptance and D1 remain unresolved.

RUN and DIAG start with the existing three head-locked camera previews visible.
X toggles preview visibility in these modes. Use `./run-vr --no-hud-on-start`
to start with hidden previews. RECORD displays the recording status/review UI;
`record --hud-on-start` is rejected because camera rendering is forbidden.

The 2026-10-06 operator selection replaces the VR render cadence with FFFT.
The [earlier rejected substep experiment](../evidence/S2/20260921_vr_render_substeps/README.md)
retains its original rejection and exact tested source. This selection does not
establish Quest comfort, wall FPS or physical acceptance of the new source.

Upstream audit: pinned Isaac Lab 17.0.2 (materialization `0c2e2c64`), Isaac Sim
6.1 / Kit 110.3 own `SimulationContext.step(render=False/True)`, render interval,
USD pinhole-camera spawning, orientation/look-at math and `CameraRecordable`.
The [upstream simulation context reference](https://isaac-sim.github.io/IsaacLab/develop/_modules/isaaclab/sim/simulation_context.html)
describes the render flag and Kit app pump; the installed pinned source was
checked before using these APIs.
The existing upstream `XrCameraFeedSession` owns RUN panel binding/lifetime.
The remaining composition gap is choosing the cadence before the first control
and spawning only camera prims in RECORD. The local code holds one render phase,
rounds settling to a completed group and reuses the existing camera configuration.
No dependency, environment, control processor or recorder format changes.

RECORD starts in `WAITING` with no demonstration or episode. On the existing
single controller pipeline, press **X** (left primary) to Start, **Y** (left
secondary) to Stop, then **X** to Save or **B** (right secondary) to Discard.
After Save, explicitly classify the saved task with **X** for success, **Y** for
failure, or **B** for incomplete. Each press is a rising edge; release a button
before using it in another state. In particular, holding X after Save cannot
select success. Stop seals the
source recording before review while XR input stays live. The state and button
mapping are printed as `human_recording_state` events and the final state is
included in the run report. Human RECORD also displays a head-locked status strip
and a Stop review window, selected by `recording_ui` in the
[canonical VR config](../../configs/isaac61_vr_runtime.yaml). The strip shows
`[ready]` with Start, `[recording]` with Stop, or `[stopped]` during review.
An ineligible recording tick adds `Input gap: no sample`; it does not open review.
The review window shows the current X/Y/B choices and held buttons with a release
reminder. Save remains visible as the accepted choice on the outcome screen;
completed outcome selection or Discard highlights the accepted item and retains
its confirmation after the existing scene reset for the configured duration.
Confirmation does not delay reset or prevent another Start. "Demonstration saved"
appears only after successful saved-index publication and reset; it does not mean
dataset admission. Physical Quest visibility/readability is still unqualified.
A saved demonstration gets a separate
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

The recording UI composes the installed Kit `XRSceneView` and `xr_utils`
`UiContainer` / `WidgetComponent`, as already used by the upstream camera-feed
presenter. The pinned candidates are `omni.kit.scene_view.xr` 1.0.4 and
`omni.kit.scene_view.xr_utils` 1.0.2 in the declared Isaac environment; upstream
owns scene placement, rendering and panel visibility. The remaining S2/D1 gap is
displaying accepted recording events and retaining visible feedback across the
synchronous reset. [The display adapter](../../tools/isaac_vr_recording_ui.py)
observes the existing lifecycle and single controller pipeline, reads no RGB,
uses on-demand widget invalidation and retains containers with show/hide.
For text, `unit_to_pixel_scale` converts stage units to the configured UI pixels
per metre and `resolution_scale` stays at one. Copying the camera-image
presenter's resolution scale alone made the layout smaller than one UI pixel
and produced blank panels. Texture resolution alone does not establish a usable
text layout. The head-locked anchor, metric distance and sensor isolation reuse
the upstream placement unchanged; no desktop `DISPLAY` is required for this
offscreen widget rendering. The [upstream sizing contract](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.scene_view.xr_utils/1.0.2/WidgetComponent.html)
distinguishes layout size from texture supersampling. Native Kit rendering with
a synthetic camera checks drawing and state updates, not physical Quest visibility.
It reuses the existing scene-partition exclusion for dataset sensors; the existing
snapshot sanitizer removes the runtime `/_xr` and `/ui` graphs before offline replay.
No dependency, environment, recorder, processor, protocol or gate-state change is
needed. Ordinary RUN/DIAG and recorder-only/injected smoke do not construct these
panels. Automated model/presenter checks are regression checks, not registered
physical acceptance evidence for [[gate:S2]] or dataset evidence for [[gate:D1]].

When UI settings were added, the registered `vr_three_camera_boundary_config`
input was relocated from `configs/isaac61_vr_runtime.yaml` to the
[frozen pre-UI configuration](../evidence/S2/20261006_recording_ui_inputs/isaac61_vr_runtime_before_ui.yaml).
Its bytes come from `63c6db11fb1d882e023bf12277d247b665ce8052` and retain the original
registered SHA-256 `309697428a2281972ca9780f579cf43377fd247e2e3c73d9886441e8c5f65643`.
Only the artifact locator/description changed; existing evidence bindings and tested
scope remain unchanged. That source snapshot is not a UI qualification result.

In RECORD, tracked intentional clutch engagement, hold and release rebase are
causal action rows in the same technical episode as motion. Both arms may have
different transitions in one row. The recorded action is the processed IK
solution actually applied, with per-arm transition provenance. Tracking loss,
tracking recovery rebase, sensitivity switches, session/reference changes and
missing XR receipts remain gaps. After at least one committed transition, a gap
causally seals the current episode before the next physics step; the CloudXR session
stays open and the next control boundary starts a new, independently finalized
artifact in a sibling directory suffixed `-<demo_id>-episode_000001`, etc.
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
RECORD also accepts `--performance-window-steps` and
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

Every live launch retains `stdout.log` (combined stdout and stderr). DIAG and
explicitly profiled RECORD additionally retain `performance.jsonl`.
Ctrl-C latches an S2 stop request; the Python control loop unwinds outside Kit's
event dispatcher, finalizes pending recording work, writes its report and stops
XR/owned CloudXR before Kit closes. A native callback can consume a raised
`KeyboardInterrupt`, so stopping cannot depend on that exception escaping a
callback. Repeated Ctrl-C does not interrupt finalization or teardown.
The launcher prints the run, recording, result
and performance paths on exit. Optional bounded camera
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

## RECORD timing and state-only reset

For a later physical Quest recording, connect the headset normally and stop with
Ctrl-C. This command does not establish physical acceptance by itself:

```sh
ROOT="/data/ebulochkin/vla-runtime/manual-record-04/$(date +%Y%m%dT%H%M%S)"
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
    episode_000000/
    episode_000001/
    episode_000002/
    ...
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
synchronization. Effective Hz excludes logging and inter-control work; the
instrumentation-write statistic excludes summary/flush and timer overhead.
Blackfire's separate paired recorder benchmark remains the resource and recorder
overhead evidence owner. Unmeasured metrics must not be inferred as zero.

VR RUN/DIAG/RECORD share F,F,F,T rendering from startup onward: four physics
integrations at 120 Hz and one Kit pump on the fourth step (simulation 30 Hz).
There is no cadence switch on the first X or when a recording stops. Reset uses
28 settling integrations, seven complete groups, with no dataset transitions.
Startup preflight still totals 120 integrations. Plain S1 retains its 25-step
reset and per-step rendering. Simulation rates do not guarantee wall-clock FPS.

RECORD authors only the canonical USD camera prims, preserving mount poses,
intrinsics and scene look-at. It never constructs dataset Camera sensors,
annotators or RenderProducts, including preflight, WAITING, RECORDING, review
and subsequent resets. The headset scene and recording UI still render. Its
preflight checks state, contacts and camera prims without claiming RGB validity.
Reset returns only the measured state boundary, then the recorder captures
immutable O_t through Fabric/CameraRecordable for offline RGB in REPLAY. A
physical reset request ends the technical episode and cannot bridge a committed
transaction across reset.

Plain `record --smoke` checks only capture/discard/finalization and commits no
rows. Use the existing `--smoke --injected-actions --recording-benchmark` path for
bounded automated committed transitions, with `--benchmark-pair-id`,
`--benchmark-warmup-steps` and `--benchmark-measured-steps`. Performance window
size controls reporting, not run duration. The injected sweep stays bounded
around the initial state so long benchmarks do not accumulate into joint limits.

## Feature development

Keep long-lived implementation worktrees under `.worktrees/`; this branch uses
`.worktrees/run-vr-primary`. Keep runtime state outside the checkout.

Experimental shared implementation → `./run-vr diag` → automated + physical
qualification → promote canonical config/status → `./run-vr` inherits it → future
record consumer inherits the same base semantics. Promotion changes selection,
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

In RUN/DIAG all three cameras publish one boundary after reset completion or
four control substeps. Scene capture remains active while previews are hidden.
RECORD uses the separate snapshot-backed state boundary and renders no camera RGB. RUN keeps only
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
