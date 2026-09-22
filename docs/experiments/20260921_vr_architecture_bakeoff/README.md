# Reproducible XR architecture experiments

Maintained experiment launcher and return-to-lab instructions; owner
`vr.performance`. [Research report](REPORT.md), [phase findings](phase_findings.md),
[source audit](source_audit.json). No canonical selection or gate acceptance.
All commands run in `/home/ebulochkin/vla_infrastructure/.worktrees/vr-recording`
on branch `wip/vr-recording`. Tested base HEAD is
`8d854b94c91a3a9e051e742fa7dd6b6a0a0939c4`; runtime identity is
`bd288917ac44a873feef04df9a488c4046927d87`. Exact executed source SHA-256s, configs,
commands and environments are copied into each output; repository delivery of
these experiment files does not qualify a later runtime revision.

The bounded [LIVE-MIN60-NONTILED run](runs/20260922_live_min60_phase/REPORT.md)
is retained as a camera-alignment failure: its fixed scene camera matched P-2 at
all 35 changing accepted boundaries. Do not advance it to the physical queue or
use its 70-sample diagnostic timings as the required short benchmark.

The follow-up [LIVE-MIN60-DEFERRED run](runs/20260922_live_min60_deferred/REPORT.md)
qualified an exact one-control producer delay across 9,000 long-run camera bundles.
That result qualifies deferred camera association, not human display latency or
120-to-60 contact-dynamics equivalence.

The bounded [LIVE-MIN120-DEFERRED run](runs/20260922_live_min120_deferred/REPORT.md)
is retained as a temporal-binding failure. At the second accepted changing
boundary both wrist cameras depicted N-1 while the scene camera depicted N.
Per the stop rule, no long performance run or physical candidate was attempted.

The follow-up [per-camera 120 Hz characterization](runs/20260922_live_min120_camera_latency/REPORT.md)
tested zero through four render-only primes and then retained 1,000 consecutive
changing-boundary classifications without publishing observations. All cameras
showed time-varying content offsets; a fixed role-specific temporal join is unsafe.
No joined correctness, drain, lifecycle, performance, or physical-candidate phase
was attempted after that stop condition.

The bounded [one-`Camera` 120 Hz experiment](runs/20260922_live_min120_batched/REPORT.md)
confirmed that the pinned `Camera` already owns one vectorized tiled render product
and can expose the three heterogeneous prims as `[3,H,W,C]`; deprecated
`TiledCamera` was not used. Dynamic wrist/world-fixed role semantics passed, but
the mandatory 300-boundary content test still found nine cross-view disagreements,
including four right-wrist N-3 classifications. The candidate stopped before long
or performance qualification and is not in the physical queue.

## LIVE-MIN60-DEFERRED prototype

`LIVE-MIN60-DEFERRED` preserves the exact LIVE-MIN60 runtime and adds an opt-in,
experiment-only one-deep observation binder plus content-sensitive qualification.
It does not alter canonical runtime files, D0 schema, gate state, or dataset
persistence. `deferred_probe.py` moves an existing robot finger and both existing
PhysX cubes deterministically, retains state/render/extraction identities, and
checks offsets 0/-1/-2 independently for all three cameras. The unreliable
camera-child USD marker was disabled. `deferred_binding.py` owns only prepare,
complete, abort, epoch invalidation, and immutable publication for one pending
three-camera observation. `dynamics_probe.py` provides the bounded deterministic
120-to-60 comparison required after temporal correctness passes.

Mandatory upstream/size re-audit:

- Capability/gates: LIVE-MIN60 temporal binding experiment; D0/S1/S2/D1 scope,
  with no gate acceptance.
- Pinned candidates inspected: Isaac Lab `SensorBase`, `Camera`, `RenderContext`,
  `IsaacRtxRenderer`, `SimulationContext`, PhysX `forward`, and `KitVisualizer` in
  the declared Isaac 6.1 / Kit 110.3 environment.
- Upstream ownership: one Kit app pump per render, RTX annotator extraction,
  camera frame/data generations, render generation, physics/Fabric synchronization,
  and camera buffers.
- Exact gap: upstream identities attest extraction completion but expose no token
  identifying the simulation state depicted by RGB annotator pixels.
- Narrow project code: a qualification-only visible source witness and a fail-closed
  one-pending binder. No acquisition, rendering, physics, recorder, or scheduling
  framework is replaced.
- Environment impact: none; the existing frozen Isaac environment and canonical
  scene/loop are reused through the process-local experiment hook.
- Framework decision: a general asynchronous observation API is unnecessary for
  one measured pipeline depth. The existing `CausalTransactionValidator` can be
  invoked after the edge completes the immutable observation.

Short qualification command (use a fresh output directory and only when no other
Isaac process is active):

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py LIVE-MIN60-DEFERRED --mode xr-smoke --ticks 320 --warmup 300 --output /tmp/live-min60-deferred-short-repeat --state-root /tmp/live-min60-deferred-state --deferred-boundaries 300
```

The retained short phase passed 300/300 expected offsets for every camera and a
physics-free terminal drain. The saved physical command is intentionally one
candidate only:

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py LIVE-MIN60-DEFERRED --mode physical --ticks 3300 --warmup 300 --output /tmp/live-min60-deferred-physical-01 --state-root /tmp/live-min60-deferred-physical-state
```

## Safety and lifecycle scope

Simulation and Quest only; no real robot action is authorized here. Use the existing
[VR operations](../../project/RUN_VR_OPERATIONS.md) startup/network/headset procedure.
Each variant runs as a separate process through the canonical `./run-vr diag`
launcher. The opt-in `sitecustomize.py` selector changes only that experiment
process. Ordinary `./run-vr` does not import it. The selector checks the branch
and refuses canonical tools/runtime-config changes from the reference revision.

Use a fresh output directory every time. Do not run two candidates concurrently.
Quit another Isaac/VR process before starting. The portable root below is separate
from canonical runtime state; its shader cache may make the first startup take
several minutes. `DISPLAY=:0` needs the lab desktop session. The launcher declares
`OMNI_KIT_ACCEPT_EULA=Y`, `ISAACLAB_CXR_ACCEPT_EULA=1`, its candidate/output variables
and a PYTHONPATH pointing to the **copied run sources**; it removes HEADLESS.
Existing CloudXR setup credentials/settings remain in the established environment;
no secret values are stored in this bundle. All paths and non-secret required
environment variables are recorded in `launch.json`.

## PHYSICAL TEST QUEUE

Run commands from the assigned worktree. Ready selectors are listed below; use
only candidates whose unattended outcome in the report supports continuation.
Queue order follows information value/dependencies, not a combined score.
Baseline command, also repeated between candidates:

```sh
cd /home/ebulochkin/vla_infrastructure/.worktrees/vr-recording
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py A0 --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-A0-01
```

1. **J60 — two presentation pumps/control**, same three live cameras. It tests
   whether the intermediate cadence preserves comfort. Expect the same scene,
   panels and controls. Camera phase is still unqualified for recording.

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py J60 --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-J60-01
```

2. **B1-FULL-OFFLINE — maximal sensors-off live architecture**, all three
   products disabled and their annotators detached before XR session entry; no
   preview panels bound. Its fail-fast guards reject image extraction/frame
   advancement. The native startup validation precedes that live boundary.
   Compare this separately from the older B1-cost probe and all previews.

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py B1-FULL-OFFLINE --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-B1-FULL-OFFLINE-01
```

   **B1-FULL-OFFLINE-D — rejected reproduction only**, same camera/panel
   suppression plus viewport updates disabled. The automatic XR-display probe
   produced 0/2 requested images, versus 2/2 with viewport updates enabled.
   Do not treat its 23.73 Hz as usable XR performance or advance it as a
   surviving physical candidate. Exact selector retained to reproduce the failure.

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py B1-FULL-OFFLINE-D --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-B1-FULL-OFFLINE-D-01
```

   **B1-cost / C0 — earlier state-only cost probe, panels disabled**. Expect the normal
   headset world and controls; X does not show camera panels. Native snapshots and
   actual post-IK/preclip labels are diagnostic only, explicitly dataset-ineligible.
   This tests comfort/response without live training-camera products. A successful
   trial does not qualify the missing D0 snapshot transaction adapter.

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py B1-cost --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-B1-cost-01
```

3. **C1-320 — one scene-only 320×240 operator preview**, conditional on B1-FULL-OFFLINE
   being useful. Expect one low-resolution scene panel, normal world/controls.
   The full offline dataset camera identity remains 640×480.

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py C1-320 --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-C1-320-01
```

4. **C2-320 — three 320×240 operator previews**. Compare usefulness with C1;
   expect left/right/scene panels, held between new control-boundary uploads.
   Test C2-256 only if 320 appears comfortably readable and reducing cost matters.

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py C2-320 --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-C2-320-01
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py C2-256 --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-C2-256-01
```

5. **E08, then E06 if necessary — XR resolution quality tradeoff**. Expect the
   same world at reduced headset sharpness, with unchanged 640×480 dataset cameras.
   Concentrate on cube/plate edges, depth judgement and gripper contacts.

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py E08 --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-E08-01
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py E06 --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-E06-01
```

6. **F-minimal — textured diffuse MinimalRendering**, selected before scene
   products attach. Expect simpler lighting/material appearance. Assess task
   colors, object edges, shadows/depth cues and manipulation, not just smoothness.
   Do not switch render mode hot inside a process.

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py F-minimal --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-F-minimal-01
```

7. **D-desktop-off — rejected standalone trial**: repeated LdrColor render-buffer
   errors were found despite exit zero. Do not advance this selector to physical
   qualification. The combined B1-FULL-OFFLINE-D also failed its XR-output precondition. The retained reproduction command disables active
   viewport updates at XR scale 1.0.
   The desktop may stop updating; the headset world, panels and controls must
   remain usable. If headset rendering also freezes, stop this trial and record
   that failure. Reconnect once and verify orderly exit.

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py D-desktop-off --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-D-desktop-off-01
```

Secondary selectors are retained, not automatically promoted to costly physical
qualification: C1-640 (one full-size operator scene preview), G-tiled640 (three
640×480 tiled operator views, **not** qualified 4B capture), H-cpu (CPU physics,
requires additional dynamics/contact qualification). Their exact commands are:

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py C1-640 --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-C1-640-01
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py G-tiled640 --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-G-tiled640-01
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py H-cpu --mode physical --ticks 18000 --warmup 300 --state-root /tmp/vr4p5-physical --output /tmp/vr4p5-physical-H-cpu-01
```

No J60+B1/scale/Minimal Cartesian-product combination is claimed tested. No
90/45/30 or 30 Hz physics selector exists.

## Same procedure for every comparison

Use the same operator, machine, task and warmup. Interleave **A C A C** (or A C C A).
Increment output suffixes for repeated runs. Wait for the startup scene and Quest
session to be ready, allow at least 300 controls warmup, then exercise for at least
five wall minutes where practical. The 18000-control cap is a generous ceiling;
press Ctrl-C in the launching terminal after the timed run. This is a deliberate
interruption, not a failed functional assertion; retain the final partial interval.

During each five-minute measured interval:

- First minute: look left/right/up/down, lean and rotate the head at comparable
  speeds; move both tracked controllers with no object interaction.
- Second minute: independent arm motion, squeeze/clutch each hand and release;
  analog triggers open/close each gripper; horizontal thumbsticks exercise each
  arm's sensitivity range. Keep the same approximate motion sequence each run.
- Third and fourth minutes: reach for both cubes, grasp, lift and place on their
  matching plates. Report task success and difficulty; do not infer success from
  frame counters. For CPU physics, specifically watch contacts/penetration/grip.
- Fifth minute: X toggles available panels, B toggles backdrop, R3 recenters;
  briefly remove/recover tracking, disconnect/reconnect once if practical, and
  verify controls recover without a jump. B1-cost and B1-FULL-OFFLINE intentionally have no X panels.
  For C1 only the scene preview should appear; C2/G should show all three roles.

Record operator observations **separately from measurements**: world smoothness,
head-motion latency, controller/hand response, panel smoothness/latency/readability,
manipulation difficulty/success, discomfort/nausea and interruption/recovery
behavior. Describe concrete changes relative to the immediately adjacent baseline;
there is no weighted score. Record operator identity, candidate, run output path,
start/end time and actual measured duration. Do not invent compositor/drop metrics.

The launcher creates `operator_observations.json` with pending fields to fill
after the run.

Automatic outputs: `launch.json`, copied sources/hashes, exact runtime command and
config locators, per-control total/stage/render-app timings, physics/render/Kit
counts, tracking/session/capture diagnostics, nvidia-smi utilization/VRAM/power,
Kit update timestamps, native CloudXR logs where the launcher exposes them.
State-only variants add diagnostic state/action JSONL; C variants add preview
shape/progression/upload proxies. CloudXR transport/reprojection/drop counters
are reported only if actually exposed; no physical proxy is called motion-to-photon.

Stop/rollback: Ctrl-C, wait for the owned CloudXR/Kit process to exit, keep all logs,
then launch A0 with a new output suffix. No source patch needs undoing. Do not
reset/stash/clean the worktree. If a crash leaves a process, identify the PID from
that run's logs before stopping only that process. The dedicated portable root
may be removed later after confirming no run uses it and evidence is retained;
cleanup is not needed between runs. Do not delete run outputs or canonical caches.

## Unattended reproduction

Short or long examples (one GPU process at a time):

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py J60 --mode xr-smoke --ticks 160 --warmup 30 --state-root /tmp/vr4p5-runtime --output /tmp/vr4p5-repeat-J60
python docs/experiments/20260921_vr_architecture_bakeoff/benchmark.py J60 --long --output /tmp/vr4p5-repeat-long-J60
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py B1-capture --mode smoke --output /tmp/vr4p5-repeat-capture
```

The replay command and exact original arguments are retained with its run sources
and logs; `offline_probe.py --help` exposes capture/output options. Run it with
the declared Isaac Python, not core Python. Require completed `metrics.json` and
`memory.json`, nonempty three-camera arrays and the stopped-physics assertions;
Kit can log an exception and nevertheless return shell exit zero. Never qualify
an incomplete materialization solely from its process exit code.

B1-FULL-OFFLINE forbids `--profile-passes`: no additional profiling renders are
permitted for that candidate. Use the ordinary control-loop telemetry. Its state
stream also carries articulation coordinates/velocities, scene and asset identities,
camera attributes and task context. Unknown task outcome remains explicitly null;
that and the unqualified causal snapshot adapter prevent dataset admission.
