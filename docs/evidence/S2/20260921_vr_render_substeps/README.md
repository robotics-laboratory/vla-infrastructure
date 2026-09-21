# VR physics-substep render experiment

**REJECTED — XR REQUIRES CURRENT RENDER CADENCE.** The three-physics-only/one-render
candidate improves control throughput, but the physical operator found the headset
scene less comfortable and preferred baseline streaming. Preserve the canonical
runtime. No implementation commit, push, physics-frequency change, or 4D work.

Tested checkout: `wip/vr-recording`, clean runtime source at
`bd288917ac44a873feef04df9a488c4046927d87`. The experiment was an explicit temporary
import hook under `/tmp/vr4p2-probe`; it changed only `sim.step(render=...)` inside
four-step advances. Reset/startup repeats were unchanged. This report registers
bounded results, not acceptance of [[gate:S2]] or [[gate:D1]].

[Machine results](summary.json), [provenance and exact commands](provenance.json),
and [test output](tests.txt) retain the scope. The provenance registers a
SHA-256-verified 7.25 MB archive in the operator's durable `/data` evidence storage;
it contains original manifests, configs, logs, timings, visible-target images,
probe scripts and failure attempts. The small repository records are frozen evidence.

## Upstream audit and environment

Capability: render scheduling at the existing three-camera observation boundary,
affecting the bounded [[gate:S1]] / [[gate:S2]] runtime, with [[gate:D0]] parity.
Pinned upstream candidates: Lab SimulationContext/PhysxManager, KitVisualizer,
Isaac RTX renderer utilities, Isaac Sim SimulationManager, Kit application/XR
callbacks, and Replicator/Hydra render products. Exact inspected file hashes are
in provenance. Lab commit is `0c2e2c64e51922d088b695d72ffe03faa5c6b95d`, Lab 17.0.2,
Sim 6.1.0.0, Kit 110.3, isaacteleop 1.4.98rc1, Lab teleop 0.9.0, CloudXR 6.2.1.

Upstream already owns physics integration, Fabric synchronization, rendering,
Camera extraction and XR lifecycle. The project gap is choosing which native
step renders while retaining an exact observation boundary and usable XR.
The experiment composes existing public `step(render=...)`; it adds no runtime
framework, alternate IK, protocol, dependency or environment. Timing/content
observers are temporary qualification code. Existing isolated Isaac and declared
core environments were reused; no SDK source changed. The reuse/size re-audit
therefore adds zero production runtime LOC.

## API semantics

The exact pinned `SimulationContext.step(render: bool = True)` supports the flag.
These facts apply to normal playing operation with canonical non-headless Kit:

| Operation | `step(render=False)` | `step(render=True)` |
|---|---|---|
| PhysX | One `simulate(dt, 0)` and `fetch_results()` | Same one integration/fetch |
| Physics state | PhysX state updated; project subsequently refreshes articulation buffers | Same |
| Fabric / render transforms | No `forward()` from this step path | Kit visualizer requires `forward()` before its update; articulation kinematics/Fabric synchronized |
| Kit application | No app update in the normal-play path | One observed Kit app update; `playSimulations=False` prevents another physics integration |
| USD/render processing | No Kit render processing; no claim that callbacks cannot author USD | Kit processes scene updates; Fabric supplies simulated poses, not a required full USD pose writeback |
| Hydra/RTX | No normal render request from this path | Kit drives enabled render products; one drawable event per canonical camera observed |
| Camera render product / extraction | No drawable/extraction on first three candidate steps | Drawable produced at final step; one extraction per camera at the following 4B barrier |
| XR / CloudXR | No Kit XR frame servicing caused by this step; background transport is separate | Kit XR hooks serviced through the app/frame path; actual headset presentation is not measured by this call |
| UI | No normal Kit/UI pump | Kit/UI serviced with app update |

Exception: `wait_for_playing()` pumps `app.update()` while the timeline is paused,
even if `render=False`; the flag does not promise physics-only behavior in every
lifecycle state. Physics callbacks also still execute. Play/pause/stop have their
own Kit updates. The observed steady-state counts exclude reset ticks.

`render()` itself performs no explicit new physics integration. It forwards
render state, updates visualizers, invokes render callbacks and increments render
generation. `render(skip_app_pumping=True)` can still forward state, call callbacks
and increment generation; it is not a completed Kit/camera render receipt.
`SimulationApp.update()` delegates to Kit's app update; calling it separately is
not a proven RTX-free XR-service operation.

Isaac Sim `SimulationManager.step(steps=..., update_fabric=False)` directly calls
its physics interface and optionally updates Fabric. It does not call the Kit app
in its inspected Python body. It is a distinct owner from the Lab PhysxManager,
with different counter/initialization paths; there is no reason to bypass Lab for
this candidate. `PhysxManager.forward()` synchronizes state, not XR/UI.

The RTX extraction helper deduplicates Kit pumps and defers to a visualizer that
owns pumping. Camera extraction after the fourth step required **zero additional
Kit updates or renders**. The pre-existing unsupported `HEADLESS=1` case remains
excluded. An initial missing-DISPLAY startup stalled and needed termination; it
is retained as a setup failure, not a qualified baseline. A port-conflict retry
is also retained. Successful runs used `DISPLAY=:0`, without HEADLESS.

## Candidate cadence

Every ordinary control applies the existing native command, advances four
1/120-second physics steps with render flags `False, False, False, True`, then
runs the existing 4B barrier. Baseline uses four `True` steps.

| Per ordinary control | Baseline | Candidate |
|---|---:|---:|
| Physics integrations | 4 | 4 |
| Simulation render calls | 4 | 1 |
| Completed Kit updates | 4 | 1 |
| Drawable events per canonical camera | 4 | 1 |
| Extractions per camera | 1 | 1 |
| Successful 4B barriers | 1 | 1 |

The physical runs also retained this cadence. Reset ticks have additional existing
25-step settling/completion work and two captures; they are not steady-state samples.

## Camera content qualification

For each of left wrist, right wrist and scene, the test placed six visible
black/white emissive targets in view. Before every physics integration it encoded
the upcoming physics step modulo 64. Each view's pixel samples decoded the exact
final step P+4, distinguishing P through P+3 and previous-control content.
The test did not accept frame counters or image-hash changes alone.

Baseline and candidate each passed all 15 checked boundaries after five target
warmup controls. All three decoded values matched the same final step, refreshed
measured state matched the barrier state, and candidate render generation advanced
once. Saved PPM images and the probe are in the archive. Marker insertion is
separate from performance sampling. This is a bounded rendered-target test, not
proof of every possible future scene or sensor configuration.

## No-client performance

Same display, GPU, scene, hidden panels, configuration and observer for both runs.
360 control ticks, first 60 excluded: 300 samples each. Resets occur in warmup.
Hz is reciprocal mean tick time; timing percentiles are per-control milliseconds.
Host timing includes synchronization waits; nested intervals are not all additive.
No-client IK exercises inactive/hold input, not the physical tracking workload.

| Metric (ms) | A mean | A p50 | A p95 | A p99 | B mean | B p50 | B p95 | B p99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Total tick | 85.141 | 83.192 | 99.368 | 101.091 | 39.282 | 37.500 | 53.504 | 57.192 |
| Four PhysX steps, excluding render | 13.022 | 12.957 | 13.989 | 15.396 | 12.216 | 12.107 | 13.240 | 14.623 |
| Render/app | 59.798 | 58.907 | 68.326 | 70.137 | 15.426 | 15.113 | 17.081 | 18.853 |
| Camera barrier | 2.761 | 2.734 | 2.968 | 3.674 | 2.702 | 2.615 | 3.460 | 4.314 |
| IK/apply | 2.536 | 2.514 | 2.786 | 3.566 | 2.480 | 2.399 | 2.981 | 4.161 |

Baseline: **11.745 Hz, RTF 0.392**. Candidate: **25.457 Hz, RTF 0.849**.
Mean tick improved 53.86%, but candidate still misses the 33.333 ms / 30 Hz wall-time
budget. Renders/Kit updates per control are exactly 4/4 versus 1/1.

## Physical Quest A/B

Operator ran A then B with the explicit temporary selector. Both exited cleanly
on Ctrl-C (130). Their automatic result is intentionally `passed=false`, status
`failed` after interruption; this is not silently changed into an automated PASS.

A logged 2,250 complete controls; B logged 3,100. Below, both controllers must be
tracking-valid, reset ticks and the first 60 controls are excluded. A has 1,369
such samples and B 2,085. Motions, resets and panel-visible durations differ;
these are observed sessions, not a deterministic replay comparison.

| Tracked, nonreset metric | A baseline | B candidate |
|---|---:|---:|
| Control / canonical camera Hz | 5.996 | 16.520 |
| RTF | 0.200 | 0.551 |
| Tick mean / p50 / p95 / p99 ms | 166.776 / 165.125 / 181.910 / 209.362 | 60.532 / 58.828 / 73.933 / 82.762 |
| Kit/render boundary Hz | 23.984 | 16.520 |
| Controls/s with panels hidden | 6.388 | 17.467 |
| Controls/s with panels visible | 5.928 | 15.345 |

Whole post-warmup runs, including inactive and reset work: A 6.354 Hz / RTF 0.212;
B 16.980 Hz / RTF 0.566. Full distributions and component timings are in summary.
Both have zero failed 4B captures and zero camera-validity failures. B has no
logged tracking-lost/invalid transitions; A has one tracking-lost transition and
37 invalid ticks per arm across its longer, reconnecting session. These counts do
not establish a tracking improvement under matched movement.

Logs show clutch engagement/hold/release-rebase, changing sensitivity, recenter,
X and B toggles in both runs. R3 scheduled/request counts are 3/3 for A and 8/8 for
B. Operator reports controls were fine. Trigger/gripper feel, hand response and
comfort are human observations; no physical controller-to-actuator latency was
instrumented. Operator saw delayed camera response when hiding the backdrop in B.
The bounded offline target test does not dismiss that physical presentation delay.

Operator assessment: B had less scene FPS and was less comfortable; its cameras
looked smoother than its headset scene. Tracking seemed usable but not very smooth.
A was generally more pleasing for streaming. This is a failed usability comparison
for promotion, despite better control throughput.

## XR presentation cadence and latency limits

Operator recalled panel readings of 70+ render/physics FPS for both, A streaming
about 25 FPS with a temporary drop to 10 after X, B 16–18 streaming FPS, and A
pose-to-render around 80 ms. The operator explicitly warned these were observations,
not measured truth. They are retained as such, not substituted for runtime counters.

The instrumented Kit update cadence supports a lower application-render cadence
in B. CloudXR periodic reports have median window-mean `PredictEndToNextPredict`
41.188 ms in A versus 57.529 ms in B. `DevicePoseInterval` remains about 13.9 ms in
both. These are unweighted summaries of periodic server reports, not per-frame
percentiles. `PredictEndToGpuEnd` is a different phase metric, not a validation of
the recalled 80 ms pose-to-render value. Client stats calls also log invalid-state
errors, so they do not provide qualified presentation telemetry.

Headset-presented frames, compositor/reprojection and end-to-end latency are
**not independently measured**. The candidate limits new normal Kit render
opportunities to one per control: nominally 30/s if real time were reached, actually
about 16.5/s during tracked B. It does not establish that the physical display
refreshes at that rate. The physical operator's discomfort is sufficient to reject
promotion; no exact presented-FPS claim is needed.

## Bottleneck and supported separation research

No-client B still spends about 15.43 ms in render/app and 12.22 ms in PhysX.
During physical B, tracked/visible panels spend about 37.28 ms in render/app;
tracked/hidden panels spend about 12.45 ms there and 19.29 ms in the barrier.
These host intervals can include GPU waits and shift with synchronization. They
do not prove that image copying or the Python barrier suddenly became the root
cause. Rendering/XR presentation and sensor scheduling remain the next focus;
physics-frequency reduction is not justified by this experiment.

Pinned-source investigation found:

- Lab Camera's update period schedules extraction; Isaac RTX `render()` reads
  annotators after ensuring the shared Kit pump. It does not independently throttle
  the active Hydra product's RTX work during other Kit updates.
- Hydra texture factory exposes `is_async` and `hydra_tick_rate`; the pinned test
  `test_tick_rate_creation` verifies creation with rate 30 and its setting. The
  current Replicator `HydraTexture` wrapper defaults to synchronous creation and
  does not expose a tick-rate parameter; `render_product_tiled` likewise exposes
  no per-control scheduling argument. This is an investigation avenue, not a
  proven independent XR/sensor schedule. Engine ownership and P+4 completion must
  be established before any adapter experiment.
- Hydra frame-info/drawable receipts provide an observation surface for such work,
  but asynchronous rendering alone does not guarantee state/image causality or
  lower GPU cost. Separate context/engine ownership would require a demonstrated
  supported composition and continued Scene Partition isolation.
- Replicator orchestrator `step`/`step_async` drives app updates and may pause or
  advance the timeline. It is not a drop-in extra render at the 4B boundary.
- Per-product `updates_enabled`/`set_updates_enabled` is the already-rejected
  naive Hydra pause mechanism. Its prior roughly 40% slowdown and unqualified
  drawable events remain rejected evidence. It was not rerun here.

No qualified separation implementation was found or promoted in this bounded
source investigation. Preserve Kit/XR servicing until a new supported schedule
passes content, throughput and physical presentation tests.

## Parity, recording and registration

Two reset episodes and 32 commanded sinusoidal transitions each yielded bitwise
identical baseline/candidate native commands, state, joint positions, TCP poses,
object poses and scoped contact forces; saturation flags match. This covers normal
arm contacts, not a new grasp/contact qualification. Core D0/4B/4C/control/mapping
and RUN/DIAG tests: 171 passed. Pinned upstream tests: 26 passed. Governance baseline:
108 passed. Live candidate RUN and DIAG smoke, plus plain S1 regression, passed.
Source/config/processor semantics and label/native separation are unchanged.

Physics remains **120 simulated Hz**, repeat **4**, dataset transitions and each of
left wrist/right wrist/scene remain **30 per simulated second**. Future recording
freezes only at a successful 4B boundary: **30 FPS, not 120 FPS**. Neither physical
run achieved 30 wall-time captures/s; there is no recording implementation or
claimed 30 FPS wall-time recording qualification.

The registry adds a bounded offline PASS and physical usability FAIL with their
artifacts, linked to unresolved S2. Existing accepted S1 and D0 evidence is not
reinterpreted; no gate status changes. The root manifest refresh covers only its
existing selected files; membership is unchanged. All implementation remains
experimental outside canonical runtime. **Commit: NONE.** No 4D work.
