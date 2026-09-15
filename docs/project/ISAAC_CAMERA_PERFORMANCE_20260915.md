# Isaac camera performance diagnosis — 2026-09-15

The largest measured XR bottleneck is the CPU image-provider upload for wrist
panels, amplified by four Kit render/update calls per control action. Hidden
panels continue to publish images. This investigation changes no runtime code.

## Scope and measurement

Investigated the RoboSyn demo at worktree commit
9591f7f14a82ec33d0969c856b7ff52c97b5b842 on RTX 4090 / driver 580.159.03.
Isaac Sim 6.0.1.0, Lab 16.4.0 release/3.0.0, isaacteleop 1.4.98rc1,
isaaclab_teleop 0.8.0, CloudXR 6.2.1. Upstream checkout and Gate C assets
were checked clean at their recorded commits.

Four sequential XR runs used the existing S2 lifecycle, no Quest client,
60 control actions, no scheduled reset, initially hidden prebound panels,
two wrist cameras and one scene camera at unchanged 640x480 resolution.
The first five actions were excluded from detailed timings; 55 calls to
env._advance(4) were timed. Nested timing totals must not be added together.

| Temporary diagnostic variant | ms per four physics steps | Relative acceleration |
|---|---:|---:|
| Existing XR loop and upload | 193.89 | 1.00 |
| One XR render per four physics steps | 60.65 | 3.20 |
| Raw CPU buffer upload, existing four renders | 85.57 | 2.27 |
| Raw CPU buffer upload plus one render | 35.66 | 5.44 |

These are physics-stage latencies within a control action, excluding IK,
controller processing and subsequent observation validation. They are not
window, headset, or streaming FPS. A physical 70-to-10 FPS comparison was
not reproduced; its exact counter and launch command were not available.

## Confirmed expensive path

1. tools/run_isaac_s1.py:350 calls sim.step() for every physics tick.
   An action holds its native target for four ticks at the 120 Hz configured
   physics cadence.
2. With XR, SimulationContext auto-injects KitVisualizer. Each sim.step()
   calls sim.render(), pumping the Kit app and the feed frame subscription.
3. Upstream camera_feed.py:479 uses wall-clock max_update_hz, without
   checking panel visibility or whether the source sensor frame changed.
   At the measured slow render rate, every tick exceeds the 1/30 second
   throttle period. There were 220 manager updates and 440 panel uploads
   over 55 actions: four uploads per panel per action.
4. The demo presenter stages RGBA in CPU memory. Upstream
   camera_feed_kit_scene_ui.py:397 sends a flattened NumPy memoryview
   through ByteImageProvider.set_bytes_data().
5. Measured left/right upload cost: 17.24 / 15.88 ms per frame.
   The two-feed manager costs 34.16 ms per tick, or 136.64 ms per action:
   approximately 70% of the 193.89 ms physics-stage latency.
6. The GPU-to-CPU stage is only 0.178 ms per frame. Final RGB observation
   conversion costs 0.350 ms per action; camera validation including hashes
   costs 1.376 ms per action. These are secondary in the measured XR path.

The expensive boundary is the image-provider call. The probe does not
separate its internal sequence conversion, allocation, GPU transfer and
synchronization, so it does not attribute all its time to any one of them.

## Headless camera cost

A separate bounded no-XR probe measured:

| Variant | Control iteration Hz |
|---|---:|
| Existing cameras and observation validation | 32.19 |
| One sim.render() call per action | 32.05 |
| Repeat existing cameras | 32.08 |
| Disable all camera render products and skip image acquisition/validation | 80.46 |

In this headless configuration sim.render() itself is nearly empty.
Camera acquisition pumps RTX on demand, once per capture cycle, deduplicated
across the three camera objects. Acquisition costs approximately 16.6 ms
per action, compared with 0.46 ms for the ready RGB observation transfer.
Thus reducing sim.render() calls alone helps the XR path, but did not
help this no-XR path. The camera-disabled variant intentionally removes
image work and is an ablation, not a usable D0 observation runtime.

## Recommended implementation boundary

First replace the slow CPU sequence upload with the supported raw CPU
buffer API in an experiment-only presenter/panel delegate. The diagnostic
kept RGBA8_UNORM, resolution, the CPU compatibility path and upstream
capture/lifecycle, and reduced the measured physics-stage time by 2.27x.
The original direct GPU-pointer path has historical gray-panel failures;
this investigation supplies no new physical qualification for that path.

Publish only a fresh camera frame, and pause presentation uploads for hidden
panels while retaining camera acquisition and the existing final teardown.
Do not call feed.close() on hide: the documented pinned-stack shared
annotator detach defect would return.

The render-once variant is an isolation experiment. A production VR fix
must preserve a responsive headset/Kit loop and decouple presentation
publication from redundant physics-driven render work. Lowering all XR
updates to 30 Hz requires physical comfort/tracking verification. Changing
render_interval in config alone is insufficient: this pinned
SimulationContext.step() calls render whenever its render argument is true.

The CPU governor reads powersave and Isaac emits a corresponding warning.
No governor/frequency experiment was performed; it is not established as
the principal cause.

Upstream public API:
[ByteImageProvider](https://docs.omniverse.nvidia.com/kit/docs/omni.ui/2.25.22/omni.ui/omni.ui.ByteImageProvider.html).
Camera cadence guidance:
[Isaac Lab release/3.0.0 cameras](https://isaac-sim.github.io/IsaacLab/release/3.0.0/source/concepts/sensors/camera.html).

## Reproduction and artifacts

Scripts, full logs, result JSON, detailed nested timing JSON and SHA-256
manifest are under docs/project/performance/20260915.
Scripts compile the existing entrypoint and instrument it in memory.
They do not install dependencies or modify the frozen checkout.

Use the declared isaac environment interpreter with PYTHONPATH set to the
frozen Lab source/isaaclab directory, PYTHONNOUSERSITE=1, the existing
demo XDG_CACHE_HOME, and the previously accepted NVIDIA EULA setting.
Run piper_camera_probe.py with --robosyn-vr-demo --s2-teleop --device cuda:0.
Run piper_camera_xr_probe.py with those flags plus --xr,
--s2-cloudxr-profile cloudxrjs, --s2-max-control-steps 60,
--s2-reset-step 0, --no-s2-require-session and a temporary --report path.
PIPER_PROBE_MODE selects current, render_once, raw_cpu_upload or
raw_cpu_upload_render_once. Detailed probe outputs are written to /tmp.

## Historical physical-session logs

Additional review located retained CloudXR server and StreamSDK logs under
/home/ebulochkin/.cloudxr/logs, paired with the existing demo stdout files.
These provide physical-session measurements independent of the temporary
no-client probes above.

| Session | Server reports | Median average PredictEndToNextPredict | Approximate XR cycle Hz | Median average PredictEndToGpuEnd | Median average GpuEndToEncodeEnd |
|---|---:|---:|---:|---:|---:|
| 2026-09-08 14:04:47 UTC, stock S2 | 74 | 28.89 ms | 34.6 | 20.19 ms | 11.02 ms |
| 2026-09-11 14:56:27 UTC, demo | 258 | 34.22 ms | 29.2 | 24.66 ms | 11.03 ms |
| 2026-09-12 13:50:10 UTC, demo CPU-staged panels | 54 | 104.61 ms | 9.6 | 50.26 ms | 12.39 ms |

These are medians of reported averages, not medians of individual frames.
Reports may use overlapping aggregation windows. The dates are different
runs and do not constitute a controlled before/after camera-toggle experiment.
PredictEndToGpuEnd includes work before GPU completion; it is not a
measurement of GPU execution alone.

The September 12 StreamSDK log separately records seven BWE timing-reset
samples with avgFrameInterval=95..111 ms. The server confirms packed stream
size 4096x4032; StreamSDK confirms the corresponding encoder resolution and
a requested 90 Hz format. Encoding changes by approximately 1.4 ms compared
with September 11, while the XR cycle changes by approximately 70 ms.
Thus encoding alone does not explain the large historical slowdown.

The paired stdout explicitly proves CPU-staged, opaque, nonuniform wrist
images, a real controller-origin X display ON followed by OFF, and valid
camera observations through step 660. There is no final result.json for
that physical demo run. Display toggles and periodic S2 status messages
have no timestamps, preventing precise alignment of ON/OFF with server
timing samples.

PoseInterarrivalTime remains approximately 14.1 ms in the slow session,
about 71 Hz, while the XR cycle runs near 9.6 Hz. Incoming pose frequency
and rendered frame cadence are separate measurements. No saved XR render
report with a measured 70 Hz cycle was found in the inspected sessions.

StreamSDK warns about an unknown 4096x4032@90hz streaming format and
Unsupported Video Codec 2. It also reports nvstTraceClientBlobStats invalid
server state roughly every five seconds. The same warnings/errors appear
in the faster September 8 and 11 sessions, so their presence alone does
not identify the cause of the September 12 regression.

The CUDA invalid-context and VideoStream busy errors at 13:54:19 UTC
occur during client teardown, after the low cadence had already persisted.
The printed zero packet-loss counters concern the gamepad channel and
do not establish that video/network transport was loss-free.

Full original sources remain in their existing locations. The diagnostic
bundle now contains historical_cloudxr_summary.json,
historical_source_manifest.json and historical_log_excerpts.txt with exact
source line numbers. No new physical run or gate acceptance was performed.

## Upstream audit and final report

- CAPABILITY / GATE: experimental S2 camera-presentation diagnosis.
- PINNED UPSTREAM CANDIDATES: Lab 913ac53f51b2f8d02c9e121caa4cbdd06262948e;
  Gate C assets f6642ce0d7872c686f29c99e9e10cd23d1d49313;
  exact runtime package versions above.
- WHAT UPSTREAM ALREADY OWNS / REUSED: PhysX stepping, RTX Camera,
  KitVisualizer, XrCameraFeedSession, SceneUI panels, ByteImageProvider,
  CloudXR and S2 teleoperation lifecycle.
- EXACT REMAINING GAP: slow final presentation upload and publication of
  unchanged/hidden frames coupled to physics-driven Kit updates.
- PROCESSOR / CONFIG / ADAPTER REQUIRED: a narrow experiment-only
  presentation delegate and cadence/freshness handling; no policy,
  recorder, camera protocol or FK/IK replacement.
- ENVIRONMENT IMPACT / EXECUTION PROFILE: isaac_vr_record environment isaac,
  experimental bounded diagnostic variant; no dependency or driver change.
- WHY NO PROJECT FRAMEWORK IS NEEDED: existing upstream presentation and
  simulation boundaries already expose the required operations.
- PINNED / VERIFIED: clean source pins, actual package versions, four
  sequential no-client XR runs; diagnostics target recorded worktree bytes.
- CONTRACT CHANGES: none. D0 feature names, shapes and action labels unchanged.
- EVIDENCE ADDED: experimental measurements only; no gate evidence registry
  entry or acceptance claim.
- ARTIFACTS ADDED: this report and the reproducible diagnostic bundle.
- PROCESSORS / ADAPTERS: temporary in-memory probes only.
- TESTS: each successful XR variant passed 60/60 valid and advancing
  bimanual RGB frames; logs checked for callback exceptions and application
  shutdown. Runtime code unchanged, so no new unit tests were introduced.
- HUMAN EVIDENCE: none from this investigation. Panel pixels, tracking,
  headset FPS, comfort and real-client latency require a physical run.
- BLOCKERS / REOPEN REASONS: no gate reopened or accepted. Physical
  qualification remains outstanding for an eventual presentation fix.
- NEXT GATE: retain current S2 state; validate a narrow presentation change
  with the physical Quest acceptance procedure before making new claims.
