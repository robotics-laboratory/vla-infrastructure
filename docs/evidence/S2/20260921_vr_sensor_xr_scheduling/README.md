# VR sensor and XR render scheduling audit

Tested runtime: `b076d5ea00bc899ce0dea05ff3ca8c62f354adac` on
`wip/vr-recording`. Its parent runtime remains
`bd288917ac44a873feef04df9a488c4046927d87`: the intervening commit contains only
registered evidence, INDEX and manifest updates. No runtime/config patch is
promoted. No 4D, physics-frequency reduction, alternate camera pipeline or push.

This frozen bundle belongs to `vr.performance`, with bounded [[gate:S1]] /
[[gate:S2]] investigation scope. It does not accept those gates or [[gate:D1]].
[Measurements](summary.json), [provenance](provenance.json) and
[checks](tests.txt) identify exact inputs, commands, failures and retained raw data.

## Evidence preservation

4P2 evidence-only commit: `b076d5ea00bc899ce0dea05ff3ca8c62f354adac`,
`docs(evidence): record VR render-substep experiment`. Before committing, seven
intended paths were verified, new artifact hashes checked, documentation history,
contract/spec references and the selective manifest validated, and 108 governance
checks passed. No runtime source, configuration selection, experiment patch or
`/tmp` material was committed. The worktree was clean before this investigation.

The [4P2 record](../20260921_vr_render_substeps/README.md) remains unchanged.
Its one-render B is rejected on physical headset usability. The operator clarified
in this task: **discomfort was in the headset world during head movement; camera
panels were smoother**. Controls were reported fine. This is a new clarification,
not a measurement or a rewrite of the frozen A/B evidence.

## Upstream audit and ownership

Capability: schedule the existing three sensor render products independently of
Kit/XR while preserving the final P+4 4B capture. The reuse ladder starts with
Lab Camera/IsaacRTXRenderer, Replicator, HydraTexture, ViewportAPI, Kit renderer and
XRCore/OpenXR/CloudXR. Native owners continue to own physics, Fabric, rendering,
extraction, XR and controls. No new production abstraction or dependency is added.
The experiments are temporary import hooks and measurement scripts; production
runtime LOC added: **zero**.

Pins: Isaac Sim 6.1.0.0; Kit 110.3.0 (`00c488ae`); Lab
`0c2e2c64e51922d088b695d72ffe03faa5c6b95d`; Replicator 1.13.36;
HydraTexture 1.6.2; XRCore 109.1.0; CloudXR 6.2.1. Source hashes are in provenance.
In the source references below, `LAB` is
`/data/vla-infrastructure/isaac61_production/IsaacLab`, and `SIM` is
`/data/vla-infrastructure/isaac61_production/env/lib/python3.12/site-packages/isaacsim`.

## Render product inventory

The probe traversed every USD RenderProduct and observed native drawable events.
A USD prim's active flag alone was not accepted as evidence of rendering.
Random `rp_*` identities, all authored attributes and relationships are retained
in the inventory JSON. Inventory is bounded to these sessions, not every possible
client-negotiated configuration.

| Product/view | Owner and camera | Resolution | Observed activity / cadence | Consumer and XR role | Removing GPU work |
|---|---|---|---|---|---|
| Left wrist | Lab Camera → IsaacRTXRenderer → Replicator `rp_*`; `/World/LeftPiper/.../gripper_base/S1WristCamera` | 640×480 | Enabled, synchronous; 4 drawables/control, 1 extraction | 4B observation and existing preview feed; not a headset eye | Static disable removes one RTX tile and about 1.98 ms GPU/pass |
| Right wrist | Same owner; `/World/RightPiper/.../gripper_base/S1WristCamera` | 640×480 | Same | Same | About 1.98 ms GPU/pass |
| Scene sensor | Same owner; `/World/RobosynDemo/SceneCamera` | 640×480 | Same | Same; distinct from headset world | About 1.92 ms GPU/pass |
| Desktop viewport | Kit widget viewport `Viewport/Viewport0`; `/Render/OmniverseKit/HydraTextures/omni_kit_widget_viewport_ViewportTexture_0` | 1280×720 | Drawable every Kit frame | Standalone camera `/OmniverseKit_Persp`; XR-enabled camera `/_xr/stage/xrCamera` | No independent desktop-disable cost claim |
| XR eye rendering | Native XRCore/OpenXR and renderer-owned views | CloudXR log reports render dimensions 2048×1792 | XR-enabled GPU assay has two remaining RTX tiles after all three sensors disabled | Headset world rendering/compositing | About 14.21 ms combined RTX cost remains; not isolated eye costs |
| Three preview panels | Lab camera-feed presenter + project fresh-frame publisher + SceneUI textures | Uses the existing 640×480 frames | Hidden in no-client performance samples; no additional USD RenderProduct | Existing last uploaded texture retained between fresh captures; composited into XR when visible | Hidden/visible costs not separately measured in 4P3 |
| Legacy S1 camera / extra diagnostic cameras | No additional camera producer found | — | Absent | — | — |
| Auxiliary renderer work | RTX internal buffers, AOVs, DLSS, SceneDB, compositor | Native intermediates, not independent canonical cameras | GPU scopes observed | Required render processing | Not individually disable-tested |

Replicator products are the three canonical sensor products, not three additional
cameras. Native XR views are not exhaustively enumerated by USD RenderProduct
traversal. Their exact internal IDs and individually labelled GPU receipts are
not exposed by the inspected Python APIs. Two remaining RTX tiles plus CloudXR
render configuration support the XR interpretation; this is explicitly an
inference, not a complete private-renderer inventory.

## XR presentation path and cadence

`SimulationContext.render()` forwards state/Fabric and steps KitVisualizer.
KitVisualizer owns `app.update()` with physics advancement suppressed during that
update. XRCore owns late pose sampling, native view scheduling and compositing;
`omni.kit.xr.system.openxr` hands images to the OpenXR/CloudXR runtime.
The project control session samples controllers once/control. That operation is
not itself a headset-present receipt.

Exact owners: `LAB/source/isaaclab_visualizers/isaaclab_visualizers/kit/kit_visualizer.py`,
`SIM/extscache/omni.kit.xr.core-109.1.0+00c488ae.lx64.r.cp312/docs/README.md`,
and the corresponding OpenXR component headers. XRCore documents deferred frame
scheduling and roughly two frames of pipeline latency; this is architecture
information, not a measured latency for these runs.

The XR experience sets `app.asyncRendering=true`, low-latency async rendering,
`omni.replicator.asyncRendering=false`, and an AR profile. The per-texture rate
setting reads 120 in the baseline; the app rate limiter is disabled. Neither is a
new headset refresh contract. The retained 4P2 Quest client requested
4096×4032 at 90 Hz, while incoming device poses were about 13.9 ms apart. The
physical application's observed Kit boundary rate was about 23.984 Hz for A and
16.520 Hz for B. These values describe different stages and must not be equated.

Available measurement surfaces:

| Surface | What it measures | Limit |
|---|---|---|
| Kit update callback, monotonic timestamp | Application service cadence | Not headset submission or presentation |
| Hydra `DRAWABLE_CHANGED` + `get_frame_info(result_handle)` | Per-texture completion, renderer/SWH frame IDs, resolution | Call inside the event; not an eye-present receipt |
| XRCore pre/post-sync and post-layer events | XR scheduling stages | Not successful `xrEndFrame` or display scanout |
| C++ `IOpenXRComponent_PreEndFrame_v1` | Callback immediately before `xrEndFrame`, with `XrFrameEndInfo` | Public native extension interface; requires a native component, measures submission attempt, not successful display |
| Kit renderer present event streams | Application-window framebuffer events | Not Quest presented FPS |
| CloudXR server timing windows | Pose intervals, prediction/next-prediction, GPU-end and encode intervals | Window aggregates; not per-tick nor complete end-to-end latency |
| CloudXR stream counters/logs | Server streaming activity | Not client display cadence; prior client stats queries reported invalid state |
| Headset presentation/reprojection/drop/latency | No validated current receipt | **Unmeasured**; operator recollections remain separate |

The initial unfiltered XR message-bus subscription produced no scheduling events.
Using the pinned tests' `create_subscription_to_pop_by_type(..., order=-1)` form
on the unchanged XR baseline recorded four `pre_sync_update` and four
`post_device_events_update` callbacks per measured control (120 controls).
Post-sync/layer callbacks were not observed. Analysis bounds these callbacks by
the corresponding timed control end, so subsequent marker-only diagnostic calls
are not counted as controls. This is XR servicing telemetry, not successful frame
submission. The last `/xr/status/fps` proxy was 26.627; its update semantics are
not sufficient to label it headset-presented FPS.

No 72/90/120 Hz headset contract is introduced. Preserving the current headset
experience requires physical comparison and actual client-side presentation
telemetry where exposed.

## Sensor path and coupling point

Each Lab Camera creates its existing Replicator product through
`IsaacRtxRenderer.create_render_data()`. Every normal Kit frame services enabled
products in the same USD context/RTX engine. Camera `update_period` and the 4B
barrier determine buffer extraction, not whether RTX rendered that product on
preceding Kit frames. The final barrier invokes the existing renderer utility's
pump deduplication and annotator extraction.

The coupling is therefore at **Kit's render scheduling of active Hydra products
in the shared scene/RTX context**, before the once/control extraction. XR and
sensor products have distinct consumers but share renderer work and scheduling.

## Supported API audit

| API | Visibility / exact source | Semantics, lifecycle and risk |
|---|---|---|
| `SimulationContext.step(render=...)` | Public; `LAB/source/isaaclab/isaaclab/sim/simulation_context.py` | Whole Kit render suppression. B already failed physical comfort; not sensor-specific. |
| `IHydraTexture.updates_enabled` / `set_updates_enabled()` | Public property; deprecated method; `SIM/extscache/omni.kit.hydra_texture-1.6.2+00c488ae.lx64.r.cp312/omni/hydratexture/_hydra_texture.pyi` | Stops requests to associated HydraEngine while paused. Existing per-substep pause experiment remains rejected. Static use here is only cost attribution after the control run. |
| `create_hydra_texture(..., hydra_tick_rate=30)` | Public native factory parameter, same stub; creation test in `omni/kit/hydra_texture/tests/test_hydra_texture.py` | Engine-rate hint/setting at texture creation; no documented P+4 phase or shared sensor completion guarantee. Setting reached 30; four sensor drawables/control remained in bounded probes. |
| `create_hydra_texture(..., is_async=True)` / `set_async()` | Public, same stub | Desires rendering on another thread. Does not promise fewer render requests or image/state phase alignment. |
| `HydraTexture(..., hydra_texture_factory=...)` | Replicator implementation class; `.../omni.replicator.core-1.13.36+110.3.0.lx64.r.cp312/omni/replicator/core/scripts/utils/viewport_manager.py` | Temporary probe injects the native factory option through existing ownership. Replicator wrapper itself has no cadence parameter. Private integration seam; unsuitable for promotion without qualification. |
| `render_product_tiled(cameras, tile_resolution, ...)` | Public Replicator `scripts/create.py` | Creates the existing render product; no cadence/phase request parameter. One tiled resolution per session constraint. No new tiling/pipeline was introduced. |
| Camera `update_period` | Public Lab sensor configuration | Controls when buffers update; full product rendering continues. Already extracts once/control. |
| `rep.create.camera(tick_rate=..., frame_rate=...)` | Public `scripts/create.py` | Sensor metadata; deprecated tick_rate explicitly does not drive sensor ticking. No proof it phase-schedules this Hydra path. |
| Annotator/IsaacSimulationGate/`rep.trigger.on_frame(interval=...)` | Public graph/trigger APIs | Downstream data/randomization execution gates, not proven suppression of full RGB RTX work. Attach/detach changes graph lifecycle. |
| `rep.orchestrator.step[_async]()` | Public `scripts/orchestrator.py` | Owns timeline, render waits and Kit updates; can add updates/subframes. Not a drop-in per-product request before the unchanged 4B barrier. |
| `ViewportAPI.updates_enabled` | Public; `.../omni.kit.widget.viewport-110.0.0+00c488ae/omni/kit/widget/viewport/api.py` | Delegates to Hydra pause. Renaming it does not create another mechanism. `freeze_frame` concerns presentation. |
| `SyntheticData.disable_rendervar()` | Public `omni.syntheticdata` | Alters AOV production/graph references; no promise to suppress an entire RGB view or preserve a final same-generation boundary. |
| Renderer `force_render_frame()` / `wait_idle()` | Public `omni.kit.renderer.bind` stub | Global/app-window operations; no sensor-product argument or phase receipt. Another full render is disallowed. |
| `is_async_low_latency`, engine-creation flags/device masks | Explicitly private/internal factory options | No supported sensor-boundary contract; not used. |

The API audit does not equate schema metadata, extraction gates, async execution,
and render suppression. Native engine scheduling implementation is not available
in these Python sources.

## Rejected mechanisms and bounded probes

The prior first-three-substep Hydra pause experiment remains rejected: roughly
40% slower and no qualified canonical drawable events. It was **not rerun**.
The public source explains why a paused texture does not emit normal render
receipts; it does not establish the root cause of the historical slowdown.
No invented explanation is substituted for a trace of that failed experiment.

C1 requests `hydra_tick_rate=30` while preserving synchronous sensor textures.
C2 additionally requests asynchronous sensor textures. Both preserve four physics
steps and four Kit updates. They are bounded API probes, not long-run performance
qualifications: both must first demonstrate one final sensor generation/control.
Exact results and setup failures are retained in summary/provenance.

| Probe | Environment | Measured controls after 60 warmup | Physics / Kit per control | Sensor drawables per role/control | P+4 content | Schedule |
|---|---|---:|---|---|---|---|
| C1 | Standalone sync | 120 | 4 / 4 | 4/4/4 | PASS (15 boundaries) | FAIL |
| C2 | Standalone async | 120 | 4 / 4 | 4/4/4 | PASS (15 boundaries) | FAIL |
| C2-XR | XR-enabled async | 120 | 4 / 4 | 4/4/4 | FAIL / not qualified | FAIL |

The first factory-import hook was bypassed by Kit's import handling and left rate
120; it is recorded as an ineffective setup, not as a test of rate 30. The corrected
hook logs native factory arguments and observed settings. The first inventory
attempt passed a USD viewport index to a native pointer lookup and crashed; the
corrected probe uses already-owned texture objects. No invalid native lookup remains.

## Cost decomposition and GPU profiling

The static XR-enabled no-client assay ran after the bounded control test. Physics
was stationary during this assay. Each configuration settled for 50 render calls,
then retained 100 calls; order was all-on, individual sensor-off cases, all sensors
off, restored. This is marginal cost attribution with profiling enabled, not a
candidate, frame-cadence test, or matched physical Quest benchmark.

| Static configuration | Host render mean ms | RTX GPU scope mean ms | RTX render tiles |
|---|---:|---:|---:|
| All on | 22.064 | 20.204 | 5 |
| Left off | 20.211 | 18.222 | 4 |
| Right off | 20.185 | 18.221 | 4 |
| Scene off | 20.220 | 18.284 | 4 |
| All three sensors off | 16.895 | 14.208 | 2 |
| Restored | 22.292 | 20.251 | 5 |

The sensor contribution is about 6 ms GPU/pass in this fixed-state assay. It is
not the whole previously measured ~60 ms/control render/app interval. Remaining
RTX work includes XR views and common synchronization/scene processing. Costs are
not strictly additive, and static no-client deltas do not predict Quest throughput.

The public HydraEngineStats API, enabled via the same `/profiler/enabled` setting
used by the Kit profiler UI, exposes RTX tiles, SceneDB/acceleration updates,
compositing, synthetic image data, OmniGraph and resample/unwarp scopes. The flat
API preserves repeated scope names; the nested dictionary collapses duplicate
names and must not be summed as a complete per-view breakdown. Product labels are
absent. The all-on/all-off assay also reports GPU OmniGraph post-processing means
1.734/0.001 ms, resample/unwarp 0.094/0.092 ms, SceneDB acceleration update
0.137/0.137 ms and compositing 0.192/0.136 ms; these nested/overlapping scopes
are not additive. Fabric forwarding is timed separately on the host. UI/extension time is
not fully attributed.

Nsight Systems 2025.6.3 captured only controls 61–80 of standalone A and rejected B,
with CUDA/Vulkan/NVTX/OS-runtime tracing. Combined traced GPU interval unions were
764.328 ms for A and 264.688 ms for B across that bounded range. Vulkan-only unions
were 589.057 and 104.184 ms. Main-thread `poll` totals were 767.431 and 263.156 ms;
`futex` totals were 259.438 and 200.847 ms. These are overlapping host/GPU intervals,
not additive utilization percentages or proof that all waits are GPU stalls.
No per-product Vulkan labels or headset-present events were recorded. B remains
rejected; these traces do not qualify it. Profiling is disabled for long runs.

## Long no-client benchmark

Three independent standalone canonical A processes each use 300 warmup controls
and 3,000 measured controls. Same scene, hidden panels, display, machine and probe;
no-client means inactive/hold controls. Every measured tick is retained, including
slow outliers and existing diagnostic GPU-probe overhead. No profiler, inventory
walk, marker targets or product suppression is active in these samples.

The summary contains each repetition separately: count, mean, sample standard
deviation, CV, p50/p90/p95/p99/p99.9/max; all component timings, cadence counts and
100/300-control rolling windows. p99.9 is diagnostic only. Tick reciprocal rate and
elapsed-wall rate are reported separately; observer writes outside the timed tick
are not silently removed from the latter. These standalone samples do not replace
an XR-enabled/physical benchmark.

| A repetition | Samples | Mean ms | Stddev ms | CV | Control Hz | RTF | Wall Hz |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3000 | 85.703 | 5.944 | 0.0694 | 11.668 | 0.389 | 11.633 |
| 2 | 3000 | 85.483 | 6.175 | 0.0722 | 11.698 | 0.390 | 11.663 |
| 3 | 3000 | 85.570 | 5.768 | 0.0674 | 11.686 | 0.390 | 11.651 |

| A repetition | p50 ms | p90 ms | p95 ms | p99 ms | p99.9 ms | Max ms |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 83.488 | 93.924 | 100.338 | 106.605 | 120.075 | 153.948 |
| 2 | 83.316 | 93.320 | 99.836 | 106.865 | 143.620 | 170.043 |
| 3 | 83.396 | 93.808 | 99.657 | 104.938 | 119.985 | 148.496 |

| A repetition | Window ticks | Min rolling Hz | Max rolling mean latency ms | RTF range | Last−first RTF |
|---|---:|---:|---:|---|---:|
| 1 | 100 | 11.355 | 88.068 | 0.3785–0.3950 | -0.00134 |
| 1 | 300 | 11.524 | 86.774 | 0.3841–0.3926 | -0.00044 |
| 2 | 100 | 11.377 | 87.895 | 0.3792–0.3955 | -0.00510 |
| 2 | 300 | 11.570 | 86.428 | 0.3857–0.3937 | -0.00073 |
| 3 | 100 | 11.474 | 87.156 | 0.3825–0.3957 | +0.00031 |
| 3 | 300 | 11.587 | 86.304 | 0.3862–0.3927 | -0.00052 |

| A repetition | Physics mean ms | Render/app mean ms | 4B barrier mean ms | IK/apply mean ms |
|---|---:|---:|---:|---:|
| 1 | 12.983 | 60.268 | 2.784 | 2.577 |
| 2 | 13.021 | 60.101 | 2.781 | 2.517 |
| 3 | 13.016 | 60.087 | 2.794 | 2.578 |

Full distributions for every component are in summary.json. The rolling latency
column is the largest window mean; no individual slow tick was dropped.

No C advances to a long benchmark without first proving the required sensor
schedule and content. Short probe timings are not presented as qualification.

## Camera qualification and recording

The existing visible-target probe encodes the upcoming physics step modulo 64 in
six emissive black/white targets in each camera before every integration. Pixel
samples must decode the final P+4 in all three views, and the captured measured
state must agree. It distinguishes stale P through P+3 content; counters alone
are insufficient. Existing 4B extraction must cause zero extra Kit renders.

Standalone C1/C2 each passed 15 post-warmup target boundaries, but still rendered
four times/control. In the XR-enabled experience, both asynchronous C2 **and the
unchanged synchronous-sensor baseline** decoded **P+3 in all three views at all
15 checked boundaries**, while the captured state matched P+4. Thus no XR-enabled
P+4 content qualification is claimed. The original 4P2 standalone qualification
remains true within its scope; it does not establish this XR-enabled condition.

This probe changes USD marker/material attributes before each integration. The
result establishes a lag in that rendered content path, not that every PhysX/Fabric
object pose is late. Whether the asynchronous USD/material handoff and physical
transform rendering share the same delay needs a state-driven target qualification.
The lag is not attributed to C2 because it also appears in the unchanged baseline.
No extra render was inserted to conceal the failure. The ordinary runtime smoke
result remains PASS because its existing counter/state checks passed; the separate
content probe is explicitly FAIL and controls the qualification decision.

Correct pixels with four sensor renders do not satisfy the requested decoupling.
No extra sensor render is added to make a failed boundary appear successful.

Physics remains 120 simulated Hz and four integrations/control. Control and future
dataset transitions remain 30 simulated Hz. Left wrist, right wrist and scene
recording each remain **30 FPS, not 120 FPS**, frozen only at a successful 4B
boundary. Wall-time throughput below 30 Hz is reported explicitly. No fabricated,
interpolated or duplicated sensor frames are introduced.

## Physical comparison and recommendation

No physical C comparison is justified until a C passes source semantics, final
pixel/state alignment and three long benchmark repetitions. The future comparison
must use A/C/C/A or A/C/A/C, at least five minutes each where practical, with raw
per-tick control/render/capture metrics, actual exposed XR/server metrics and clean
shutdown observations. Ask separately about headset-world/head-motion smoothness,
camera panels and control response. Require the same scene/operator/machine state.

The clarified 4P2 world-motion failure is not fixed by smoothing preview panels.
The existing publisher already holds the last sensor texture between fresh
once/control updates and composites that texture in subsequent XR frames. It
creates no dataset interpolation. No independent reprojection API was qualified.

**BLOCKED ON XR-enabled P+4 camera content alignment and a supported phase-locked sensor-product scheduling API**.

Best candidate: **none qualified**. The native rate/async options tested do not
provide the required one-generation-per-control schedule. The missing capability
is a supported product-specific request with a P+4 completion receipt while XR
continues on intervening frames. The inspected public surface does not establish
that contract; binary scheduling internals prevent a universal impossibility
claim. Complete native XR view attribution and headset-present telemetry also
remain unmeasured. No physical benefit is projected from the static cost deltas.

Rendering, shared scene processing and host synchronization remain the measured
focus. The three sensors account for only part of that work. Full UI/extension and
per-eye attribution remains incomplete. Physics frequency is unchanged. No candidate
is canonical and no runtime commit was created. The only commit in this task is
the explicitly requested 4P2 evidence-preservation commit.

## Validation and retained scope

242 core/topic/governance tests passed in the first run; three Unix-socket tests
were blocked by sandbox bind permissions and passed on a permission-corrected
retry. Both attempts are retained. No source/test implementation was changed.
Post-registration governance tests also passed (130 tests).
Final documentation, contract/spec references and selective-manifest checks use
trusted base `b076d5ea00bc899ce0dea05ff3ca8c62f354adac`. New registrations do not
change runtime selection or gate acceptance.
