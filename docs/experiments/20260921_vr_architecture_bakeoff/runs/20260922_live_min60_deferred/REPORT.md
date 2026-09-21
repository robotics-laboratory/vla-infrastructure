# LIVE-MIN60-DEFERRED qualification

Frozen experiment record. Owner: `vr.performance`. This report qualifies the
measured one-control camera producer delay only. It does not change canonical
runtime selection, accept a gate, prove human display latency, or claim physical
teleoperation success.

## Scope and runtime

- Worktree: `/home/ebulochkin/vla_infrastructure/.worktrees/vr-recording`
- Branch: `wip/vr-recording`
- Experiment parent HEAD: `cda9cd87c799fb4683845b728f3d5010769c641f`
- Required base: `7998726500ecf15abc2c853e152ebe70bf05c119`
- Physics/control: 60/30 Hz, two physics steps and one render per control
- Renderer/XR: RTX Minimal mode 2, scale 0.4
- Cameras: independent non-tiled left wrist, right wrist, and scene products,
  640 x 480 uint8 RGB; previews off
- Owned payload: 2,764,800 bytes per finalized observation
- Recorder/HDF5/compression/LeRobot: off

The content classifier used the right cube in the left-wrist view, the left cube
in the right-wrist view, and an existing moving `gripper_link1` in the scene view.
The camera-child USD marker was disabled because it was absent from both wrist
products under RTX Minimal. Thirty changing calibration boundaries established
three separated native feature references before accepted sampling.

## Temporal result

Two render-only primes were required and discarded; they advanced no physics and
cost 48.706 ms total. The 300-boundary short run then produced the exact histogram
below for every camera:

| camera | offset 0 | offset -1 | offset -2 | other |
|---|---:|---:|---:|---:|
| left wrist | 0 | 300 | 0 | 0 |
| right wrist | 0 | 300 | 0 | 0 |
| scene | 0 | 300 | 0 | 0 |

All 300 triples shared one extraction identity, advanced render and Kit generation
by exactly one, and agreed on the same source boundary. The available image at
control N depicts state N-1, equivalent to P-2 at 60 Hz. Short control timing,
including the content classifier, was 32.332 ms mean, 1.635 ms standard deviation,
CV 0.0506, p50 31.965, p90 34.727, p95 35.393, p99 37.084, p99.9 38.918, and
39.432 ms maximum. Binding itself was 1.353 ms mean.

Three independent long runs each accepted 3,000 changing boundaries. Every camera
reported exactly 3,000 offset -1 and zero offset 0, offset -2, or unresolved
associations: 9,000 atomic three-camera bundles total with no failure.

| run | controls | mean ms | stddev ms | CV | p50 | p90 | p95 | p99 | p99.9 | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3000 | 32.597 | 3.517 | 0.1079 | 32.029 | 35.275 | 36.222 | 37.652 | 46.853 | 183.976 |
| 2 | 3000 | 32.573 | 3.442 | 0.1057 | 32.035 | 35.136 | 36.122 | 37.570 | 41.396 | 182.885 |
| 3 | 3000 | 32.383 | 3.231 | 0.0998 | 31.901 | 34.774 | 35.830 | 37.424 | 43.141 | 181.344 |

## Deferred transaction and lifecycle

The one-deep binder prepares the immutable state identity at boundary N, including
observation/control ID, reset/reference/session epochs, state generation, physics
step, owned 14-vector state, and expected render request. At availability N+1 it
requires the exact expected source observation, availability tick, render
generation, common extraction identity, ordered three-camera bundle, monotonic
per-camera identity, and owned immutable RGB before publication. Action N and its
native command retain dataset index N; only completion of observation N is delayed.
Unit attacks for a one-index action/source shift are rejected.

A 60-control live lifecycle run finalized 55 observations and discarded five
pipeline slots: initial startup plus reference changes at ticks 18 and 48 and reset
changes at ticks 30 and 31. No pending state crossed an epoch. Mid-run XR session
recreation was not feasible without the operator; the same abort-and-reject path
was exercised in the unit suite with the `session_recreation` reason. The live
hook derives its session epoch from observed `device.session_running` edges; it
does not invent a renderer source identity. No physical tracking result is claimed.

Failure tests reject a missing image bundle, a missing/reordered/delayed camera,
camera extraction disagreement, a stale camera, wrong source observation, wrong
availability tick, render-generation slip, duplicate observation/render request,
non-monotonic camera identity, and mutable/non-owned RGB. Failure is closed; a
later image cannot be silently rebound.

## Startup and terminal drain

Startup needs two render/extraction operations, discards both, and performs zero
physics or accepted transitions. The first accepted observation is published only
after content identity is established.

After the final physics transition, one render-only operation recovered the final
successor observation. Across short/long runs it cost 26.632, 27.982, 26.566, and
26.567 ms. Physics step and state bytes were unchanged, and all three terminal
views matched offset 0. No dummy action, extra physics, duplicate, fabricated
frame, or dropped terminal observation was used.

## Steady-state performance

Each run used 300 warmup plus 3,000 measured controls. During every measured window
the pipeline finalized one observation and one transition per control; left,
right, and scene finalized FPS therefore equal finalized dataset Hz. Five slots
outside measurement were discarded for startup/reset/recenter epoch changes.

| run | wall control/finalized Hz | RTF | mean ms | stddev ms | CV | p50 | p90 | p95 | p99 | p99.9 | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 28.937 | 0.965 | 34.558 | 4.704 | 0.1361 | 32.985 | 37.961 | 48.814 | 52.612 | 55.611 | 58.957 |
| 2 | 29.282 | 0.976 | 34.150 | 4.639 | 0.1358 | 32.582 | 37.268 | 48.361 | 52.334 | 56.074 | 64.040 |
| 3 | 29.197 | 0.973 | 34.250 | 4.662 | 0.1361 | 32.660 | 37.643 | 48.408 | 52.434 | 55.221 | 58.525 |

Mean stage timings by run (milliseconds; nested stages are not additive):

| stage | run 1 | run 2 | run 3 |
|---|---:|---:|---:|
| XR/input | 1.105 | 1.088 | 1.098 |
| IK | 2.625 | 2.556 | 2.578 |
| physics | 8.084 | 8.054 | 8.064 |
| sync | 0.772 | 0.773 | 0.776 |
| render/app | 9.505 | 9.365 | 9.405 |
| extraction | 4.922 | 4.887 | 4.873 |
| RGB freeze | 0.860 | 0.839 | 0.842 |
| deferred finalization | 1.565 | 1.561 | 1.557 |
| other/unattributed | 0.023 | 0.022 | 0.023 |

The measured delay adds one control of availability latency but not a steady-state
throughput bubble. It does not repair headset/display latency.

## Bounded 120-to-60 dynamics comparison

The deterministic 120-control trace used the same target at each 30 Hz boundary,
with four 120 Hz versus two 60 Hz integrations. Free-motion differences were
small: robot joints 0.0571 degrees maximum, gripper aperture 0.0127 mm maximum,
TCP position 2.494 mm maximum, and TCP orientation 0.391 degrees maximum. The
untouched cube differed by at most 1.92 micrometers. Both resets restored robot
and TCP identically within numerical precision and cube position within 1.87
micrometers.

Contact dynamics were **not equivalent**. A bounded native cube/left-arm collision
peaked at 165.060 N and ended after two sampled boundaries at 120 Hz; at 60 Hz it
peaked at 82.291 N, remained in contact through the trace, and the struck cube
diverged by 0.213 m and 133.52 degrees. This is a measured 60 Hz dynamics limitation,
not a camera-binding failure. No alternative dynamics, tuning, or contact search
was attempted.

## Contract, validator, gates, and physical follow-up

No D0 contract change is required. D0 continues to mean state N plus images N;
the observation is merely published after its payload is complete. The canonical
`CausalTransactionValidator` already requires an immutable bound observation at
transaction commit and does not require pixels to materialize at state selection.
No core validator change was made; the experiment-only binder supplies
prepare-state, complete-images, and publish/freeze.

Canonical D0, S0, and S1 acceptance remain unchanged. S2 and D1 remain unresolved.
The 60 Hz contact result prevents any claim that the candidate preserves canonical
120 Hz dynamics. The physical candidate is saved for operator evaluation only:

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py LIVE-MIN60-DEFERRED --mode physical --ticks 3300 --warmup 300 --output /tmp/live-min60-deferred-physical-01 --state-root /tmp/live-min60-deferred-physical-state
```

The later run must measure wall/finalized Hz, RTF, tracking interruptions, and
binding failures and separately answer whether teleoperation is usable. It cannot
be cited as approved until an operator actually runs it.

## Verdict

**DEFERRED ONE-TICK CAMERA BINDING QUALIFIED**
