# RECORD dataset-camera rendering suspension

## Scope and starting point

Three fresh-process baseline runs and three optimized runs establish a no-client
RECORD improvement from **7.626 to 12.200 Hz (+59.97%)**. These are control-loop
measurements with native HDF5 storage, not headset FPS. No physical Quest was
present; no XR-enabled no-client run was performed in this task.

The assigned worktree was clean at `c55f833fe4611fdcca31e15b5a9ad45dd97eee1d`,
branch `review/vr-recording-validation`, path
`/home/ebulochkin/vla_infrastructure/.worktrees/vr-recording-validation`.
History includes `8fbb8e0`. No subagents, push, physics-rate change, renderer-quality
change, physical robot action, dataset conversion or demonstration UX was used.

The original launcher rejected explicit performance flags in RECORD. Before any
production edits, an external argparse shim admitted only that exact two-flag
error. It ran the unchanged launcher/runtime at c55f833 with 30 warmup and 300
window steps. The final launcher admits those flags directly in RECORD. Child
arguments, pins and canonical configuration hashes match across conditions,
apart from fresh output/config paths. Exact commands, source hashes and every
artifact locator/digest are in [results.json](results.json).

```sh
export OMNI_KIT_ACCEPT_EULA=Y ISAACLAB_CXR_ACCEPT_EULA=1
./run-vr record --smoke --max-control-steps 330 \
  --performance-warmup-steps 30 --performance-window-steps 300 \
  --recording-dir "$recording"
```

Machine: RTX 4090; pinned Isaac environment, 120 Hz simulation timestep,
four physics substeps per control. Each process retained performance.jsonl,
stdout.log, result.json, run_manifest.json, generated config, recording manifests,
stage snapshot and HDF5. Steps 31–330 are measured; all 300 samples are retained.
The injected reset at the first measured control contributes to the maximum and
mean. No outliers were removed. GPU/VRAM are unmeasured: existing RECORD telemetry
does not collect the GPU samples enabled in DIAG.

## Pinned upstream audit and minimum adaptation

Capability: suspend only the dataset render cost while retaining native state
recording and replay. Gate scope is bounded S2 software regression; no acceptance
change to D0, S0, S1, S2 or D1.

Pins: Isaac Lab 17.0.2, source `ae37b028ea415c91ea2bc32609efcd759ed2b974`,
materialization `0c2e2c64e51922d088b695d72ffe03faa5c6b95d`, Sim 6.1,
Kit 110.3, Replicator 1.13.36, Hydra texture 1.6.2. Exact installed source digests
are retained in results.json. The earlier
[full-offline experiment](../20260921_vr_architecture_bakeoff/REPORT.md)
and its [adapter](../20260921_vr_architecture_bakeoff/full_offline.py) were inspected.

For every role, the object is `isaaclab.sensors.camera.camera.Camera`; its
`IsaacRtxRenderData` belongs to `IsaacRtxRenderer`. Each owns a distinct Replicator
`HydraTexture` RenderProduct at `/Render/OmniverseKit/HydraTextures/rp_<uuid>`.
The wrapper's `hydra_texture` is Kit's `IHydraTexture`. The `rgba` dictionary entry
is the public `rgb` annotator, attached by the renderer. Exact process-specific
product paths are in the retained before/after reports.

| Role | USD camera prim |
|---|---|
| left_wrist | `/World/LeftPiper/Geometry/world/base_link/link1/link2/link3/link4/link5/link6/flange_link/gripper_base/S1WristCamera` |
| right_wrist | `/World/RightPiper/Geometry/world/base_link/link1/link2/link3/link4/link5/link6/flange_link/gripper_base/S1WristCamera` |
| scene | `/World/RobosynDemo/SceneCamera` |

Upstream owns camera prims, pose/intrinsics, rendering, native Recordables,
HDF5 and replay. `Camera.reset()` resets timestamps, poses and frame bookkeeping;
it does not recreate products or attach annotators. `Camera.__del__()` closes its
view and calls renderer cleanup, which detaches readers and destroys the product.
The implementation keeps those owners and resources intact. CameraRecordable
reads the camera prim and pose wrapper independently of the Camera RGB buffers.

There is no public Camera render-resource accessor at this pin. The only private
dependency added is `Camera._render_data`, isolated in the 130-line
`tools/isaac_vr_camera_rendering.py` adapter. It uses public spec/product fields,
`hydra_texture.updates_enabled = False`, `Annotator.detach([product.path])`,
`get_node()` and texture-filtered drawable events. No SDK patch, dependency,
shared-renderer cleanup, viewport enumeration or new renderer architecture is
needed. Existing large runtime owners receive only lifecycle calls; no framework
or copied implementation is introduced.

Two pin-specific diagnostics were resolved through actual runtime checks:

- Replicator leaves `is_attached` true after detachment because its cached node
  path is not cleared. `get_node()` raises `AnnotatorRegistryError` after the
  graph binding is removed; the guard uses that public binding check and reports
  the stale property separately.
- `get_frame_info(0)` outside a drawable event was not a valid per-product
  counter and eventually crashed Kit after suspension. That call was removed.
  The final guard uses each texture's event filter and reads frame metadata only
  with the event's live result handle. No native crash workaround or renderer
  setting was introduced.

## Actual camera state and lifecycle

A separate unchanged-code 60-control baseline probe observed, for all three
roles: camera prim/product present, updates true, RGB annotator bound, Camera
frame 0 throughout, and **290 texture-filtered drawable events**. Event frame
numbers reached 450 (the initial renderer snapshot was 160). This directly shows
that the previously frozen Camera counters did not establish stopped rendering.
The probe is separate from the six performance measurements.

Final owner: `VRRuntime.suspend_dataset_camera_rendering(stage)` constructs the
small `DatasetCameraSuspension` guard once; repeat calls validate the existing
suspension. Ordering is canonical scene/image preflight, disable live extraction,
state-only reset, export snapshot/open native Recordables, suspend products/detach
readers, then enter the device/control loop. Every control boundary checks the
same resources. RUN/DIAG do not call suspension. XR/operator products and settings
are never passed to the helper.

All three finalized optimized runs report the following for each role after 330
controls, across reset epochs 2 through 4:

| Property | At suspension | After 330 controls |
|---|---|---|
| Camera USD prim / RenderProduct | Present / present | Present / present |
| RenderProduct updates | False | False |
| Annotator graph binding | Inactive | Inactive |
| Camera.frame | 0 | 0 |
| Texture-filtered drawable event counter | 0 | 0 |
| Live RGB extraction / preview / capture boundary | Inactive | Inactive |

The shared renderer can continue producing operator/viewport output; no global
renderer frame count is treated as a dataset-camera update count. Reset retains
the disabled products, performs ordinary upstream camera bookkeeping, and creates
state-only O0 without camera capture. No readback is used by the guard.

## Matched performance results

All values below are milliseconds except effective Hz. Each row has 300 samples
and a deadline miss fraction of 1.0 against 33.333 ms.

| Condition/run | Effective Hz | Mean | p50 | p90 | p95 | p99 | Max |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline 1 | 7.6423 | 130.851 | 126.645 | 137.052 | 139.852 | 187.754 | 873.412 |
| Baseline 2 | 7.6630 | 130.497 | 126.950 | 136.340 | 139.085 | 143.931 | 857.237 |
| Baseline 3 | 7.5736 | 132.038 | 127.773 | 137.159 | 139.038 | 185.232 | 870.494 |
| Optimized 1 | 12.1926 | 82.017 | 80.000 | 84.378 | 87.277 | 94.540 | 503.624 |
| Optimized 2 | 12.2037 | 81.942 | 80.090 | 83.624 | 85.435 | 91.358 | 516.071 |
| Optimized 3 | 12.2036 | 81.943 | 80.458 | 83.926 | 85.761 | 92.771 | 521.298 |

Aggregate effective Hz is the arithmetic mean of three per-run rates; control
percentiles pool all 900 samples per condition.

| Metric | Baseline | Optimized | Change |
|---|---:|---:|---:|
| Mean effective Hz | 7.6263 | 12.2000 | +4.5737 (+59.97%) |
| Min/max effective Hz | 7.5736 / 7.6630 | 12.1926 / 12.2037 | — |
| Mean control ms | 131.128 | 81.967 | −49.161 |
| p50 ms | 127.179 | 80.262 | −46.917 |
| p95 ms | 139.390 | 86.063 | −53.327 |
| p99 ms | 184.883 | 92.931 | −91.952 |
| Deadline miss fraction | 1.0 | 1.0 | 0 |
| GPU utilization / VRAM | Unmeasured | Unmeasured | Unmeasured |

Stage distributions (mean / p95 ms; complete p50/p90/p99/max in results.json):

| Stage | Baseline | Optimized |
|---|---:|---:|
| teleop_advance | 1.578 / 2.293 | 1.540 / 2.195 |
| command_processing | 2.545 / 0.151 | 1.530 / 0.148 |
| ik_apply | 5.018 / 7.112 | 4.973 / 6.638 |
| simulation_advance including sample/storage | 121.957 / 132.564 | 73.698 / 78.618 |
| camera_observation / suspension checks | 0.0008 / 0.0011 | 0.1958 / 0.3013 |
| nested sim_step | 110.025 / 118.619 | 60.676 / 63.620 |
| nested camera_update | 0.0067 / 0.0075 | 0.0065 / 0.0074 |
| unattributed | 0.0193 / 0.0230 | 0.0196 / 0.0238 |

Nested stages are not additive. Existing telemetry combines ordinary state
sampling/HDF5 appends with simulation_advance, and reset/O0/episode segmentation
with command_processing; no separate baseline storage distribution exists.
The new suspension guard costs about 0.196 ms per control boundary. The dominant
reduction is the native sim-step/render interval. These runs remain below 30 Hz.

## Correctness and verification

Native HDF5 checks pass for all three optimized runs: three episodes with
30, 2 and 301 state frames, coherent lengths, finite camera poses/intrinsics,
all three roles, valid reset O0 and continued four-step state observations.
No-client recording has no eligible physical tracking actions; the focused
injected-input regressions exercise valid preclip labels and causal commits.

Unmodified SessionReader and EpisodeReplayer applied all 301 frames of optimized
run 1's post-reset episode 2. Stage snapshot/hash validation passed. Physics counts
are 0 before and after, native_action_replay is false, and first/middle/last frames
0/150/300 produced nine RGB PNG images at 640×480. The retained native-validation
script asserts every HDF5 camera channel and decodes all nine images.

Focused tests: 156 passed. Full core: 500 passed, 26 skipped, four subtests passed.
The core environment requires this worktree's local package on PYTHONPATH;
Unix-socket tests require host permissions and test caches were redirected to /tmp.
Initial sandbox/collection failures are retained. No dependencies were installed.
Ruff, scoped mypy, contract, spec references, trusted-base docs lint, manifest
verification and diff checks are recorded in [checks.txt](checks.txt).

Failed development runs are retained: stale-attachment guard rejection,
default-frame-counter guard rejection, and the Kit diagnostic-call crash.
A successful preliminary functional run measured 12.1996 Hz and is also retained.
The reported three optimized repetitions share identical final runtime source
hashes, after two type-narrowing assertions; no poor completed final-source run
was excluded. Runtime source hashes, rather than the earlier HEAD alone, identify
the tested uncommitted implementation.

## Retention and gates

Raw supplementary launch/test logs, shim/probe/validation scripts and extracted
results are retained under
`/data/ebulochkin/vla-runtime/isaac-isaac61/evidence/20260923_record_camera_suspension`.
Native run bundles and recording/image directories retain their original locators
in results.json. This frozen report, results and checks are indexed and registered
as bounded S2 software/performance evidence. Existing historical bytes are unchanged.

D0/S0/S1 retain their previously accepted scopes. S2 and D1 remain unresolved.
No gate is promoted. Physical Quest FPS, comfort and usability are unmeasured;
static/unit XR isolation is not physical qualification.

Verdict: **LIVE DATASET CAMERA RENDERING SUSPENDED — PERFORMANCE IMPROVED**.
