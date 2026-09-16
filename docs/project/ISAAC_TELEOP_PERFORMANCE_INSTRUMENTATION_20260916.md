# Isaac teleop performance instrumentation and experiment plan — 2026-09-16

This document covers the experimental RoboSyn VR demo through commit
`cb0b521` plus the instrumentation changes on
`experiment/robosyn-vr-demo-fps`. It does not accept or reopen a gate and
does not change the D0 action/observation contract.

## Scope

The severe oversized-panel regression is already addressed by the current
raw CPU upload, camera-pixel panel layout, and hidden/duplicate-frame filters.
The measurements in `ISAAC_CAMERA_PERFORMANCE_20260915.md` predate some of
those fixes and must not be presented as current baseline performance.

The remaining task is fine-grained observability and controlled scaling tests
for more complex scenes and future augmentation. No optimization described
below is implemented by this change.

## Instrumentation

The demo launcher now creates `performance.jsonl` beside `result.json` and
`stdout.log`. It records every control step and emits a rolling summary every
30 post-warmup steps by default. The first 30 steps are excluded from aggregate
statistics but remain in the JSONL.

Per-step exclusive host-wall stages:

- TCP pose read before control;
- upstream teleop `device.advance()`;
- control-event polling;
- processor/demo-control handling;
- differential IK and native target application;
- four-step simulation advance;
- TCP pose read after control;
- runtime bookkeeping;
- camera observation transfer/validation/hash;
- the existing synchronous GPU probe;
- periodic status output.

The simulation-advance stage additionally contains explicitly non-additive
nested measurements accumulated over its four physics ticks:

- robot target writes;
- `sim.step()`, including the pinned XR/Kit render/application work;
- robot state updates;
- camera updates;
- physics-probe update;
- demo asset/presentation update.

Each step also records `monotonic_ns`, session/action/tracking state, camera
validity/advancement, HUD and backdrop visibility, total time, unattributed
time, and a 30 Hz control-deadline miss flag. Summaries contain mean,
p50/p90/p95/p99/max, effective Hz, and miss count/fraction.

These are host-observed timings. The logger deliberately adds no
`cuda.synchronize()`; GPU work appears where the pinned runtime already
synchronizes. Nested measurements must not be added to their parent
`simulation_advance` value.

Launcher options:

```text
--performance-window-steps N
--performance-warmup-steps N
```

The low-level S2 entry point also accepts `--s2-performance-log PATH`.
Without that option, timing collection is disabled.

## Current bottleneck hypotheses

These are candidates for measurement, not claims about the new current
baseline:

1. `sim.step()` still pumps XR/Kit four times per 30 Hz control action.
2. RTX acquisition for two wrist cameras plus the non-D0 scene camera may
   consume most of the remaining 33.33 ms budget as scene complexity grows.
3. Visible wrist preview still performs a synchronous device-to-host stage and
   two raw CPU image-provider uploads for each fresh publication.
4. TCP pose reads, IK output conversion, native dispatch, and camera
   observation contain several GPU-to-CPU-to-GPU synchronization boundaries.
5. Full-frame finite scans and SHA-256 of both wrist images run every control
   step although their values are only validation evidence.
6. The existing `nvidia-smi` subprocess every 15 demo steps can create a
   periodic latency spike. It is retained for this first run but timed as
   `gpu_probe` so its disturbance is visible.
7. CloudXR render, encode, network, and client presentation can dominate
   perceived headset FPS independently of controller-pose arrival cadence.

## Controlled experiment sequence

Use the same pinned environment, scene, warmup, run length, Quest state, and
GPU isolation. Change one factor at a time and retain all run directories.

1. Current scene, physical Quest, HUD hidden: establish the optimized baseline.
2. Same run with HUD visible: isolate preview publication cost.
3. Diagnostic-only 0/1/2/3-camera ablation: determine per-camera RTX scaling.
4. Diagnostic-only 320x240 versus 640x480 and 15 versus 30 camera Hz.
5. Sampled versus per-step image validation/hash, without changing dataset
   observation semantics.
6. Scene complexity ladder: baseline, added rigid assets, added lights,
   contacts, materials/textures, and domain-randomization components.
7. Renderer/XR scheduling probes only after the physical baseline: separate
   120 Hz physics, 30 Hz control/cameras, and headset presentation cadence.
8. A sustained run to detect thermal, VRAM, allocator, or callback drift.

For each condition use at least three runs after warmup and compare p50, p95,
p99, maximum, deadline-miss fraction, nested `sim_step` and camera-update
time, GPU-probe spikes, and CloudXR server timing aligned by timestamps.
A camera-disabled run is an ablation, not a usable D0 runtime.

## Optimization candidates after evidence

- Decouple physics, camera/control, and XR presentation cadence through the
  pinned upstream lifecycle rather than globally reducing headset updates.
- Keep the current raw provider and hidden/fresh filtering; investigate a
  supported GPU texture path only with physical gray-panel qualification.
- Avoid continuously rendering a non-policy scene camera when it is not
  required, or schedule it at its actual consumer cadence.
- Keep IK/native targets on GPU longer and remove redundant host round trips.
- Move full-frame hashes and finite scans to sampled diagnostics.
- Replace in-loop `nvidia-smi` with start/end samples or an external
  low-rate NVML sampler after the first measured run.
- Evaluate renderer quality, DLSS, stream resolution, and material complexity
  only as explicit visual-quality tradeoffs.

## Mandatory upstream reuse audit

CAPABILITY / GATE: experimental S2 performance observability; no gate
acceptance.

PINNED UPSTREAM CANDIDATES: Isaac Lab
`913ac53f51b2f8d02c9e121caa4cbdd06262948e`, Isaac Sim 6.0.1.0,
IsaacTeleop 1.4.98rc1, isaaclab_teleop 0.8.0, CloudXR 6.2.1.

WHAT UPSTREAM ALREADY OWNS: SimulationContext/PhysX, RTX Camera,
Kit/XR rendering, XrCameraFeedSession, SceneUI/ByteImageProvider, controller
acquisition/retargeting, DifferentialIKController, and CloudXR lifecycle.

EXACT REMAINING GAP: identify where the existing concrete S2 frame budget is
spent and correlate local control/render latency with physical XR behavior.

PROCESSOR / CONFIG / ADAPTER REQUIRED: one S2-specific host-timing logger and
launcher wiring. No processor semantics or action width changes.

ENVIRONMENT IMPACT: none; standard-library-only instrumentation, optional at
the low-level entry point, automatically enabled only by the experimental demo
launcher.

WHY NO PROJECT FRAMEWORK IS NEEDED: the concrete S2 loop and existing upstream
boundaries expose every measured stage; no simulator backend, RPC, recorder,
or custom XR protocol is introduced.
