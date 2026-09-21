# XR and recording architecture bake-off

Research on 2026-09-21, experiment only. Owner: `vr.performance`. No architecture
is qualified or promoted. Canonical runtime remains `bd288917ac44a873feef04df9a488c4046927d87`;
no RecorderManager, HDF5 episode, converter, D1 or S2 acceptance was implemented.
The operator left the lab; no new physical observations are inferred.

## Preserved evidence commits

4P2: `b076d5ea00bc899ce0dea05ff3ca8c62f354adac`. The staged 4P3 inventory was checked:
only its evidence bundle, registrations, affected gate bindings, INDEX and
selective MANIFEST changed. Preserved as **`8d854b94c91a3a9e051e742fa7dd6b6a0a0939c4`**,
`docs(evidence): record XR sensor scheduling research`. No push. All experiment
launch manifests identify that HEAD and the separately hashed experiment sources.

## Method and interpretation

Single RTX 4090, pinned production Isaac environment and original task scene.
Physics remains 120 Hz; four physics integrations per nominal 1/30 simulated
second. No-client means no physical Quest client; `smoke` also omits the Kit XR
extension, whereas `xr-smoke` activates the XR application/session without a
human. These conditions are reported separately. XR enabled/display flags and
Kit update counts are application proxies, not compositor frame rate or physical
tracking proof. No action replay through physics was used for materialization.

Funnel: pinned source/API inspection; 160-control short trials (30 warmup,
130 measured); long surviving no-client trials (300 warmup, 3000 measured,
three independent processes); active-XR short probes; physical tests deferred.
Every failed setup and interrupted run is retained. No manual outlier removal.
Inverse-mean tick Hz and actual end-to-end wall-period Hz are distinguished;
inter-tick logger overhead is included in the latter. Per-repetition distributions
include mean, population standard deviation, CV,
p50/p90/p95/p99/p99.9/max, Hz and RTF. Raw timing arrays and every sliding
100-/300-control window are retained outside Git. Startup/shader compilation
is excluded from steady-state throughput and never represented as free.

The inherited canonical three-long-run baseline is approximately 11.68 Hz,
RTF 0.390, 85.6 ms/tick. Earlier physical A0 was approximately 6 Hz/RTF 0.20.
Earlier one-render/control physical throughput (~16.5 Hz) came with worse
operator-reported comfort and is rejected. These are historical measurements,
not new physical trials on the experiment checkout.

## Candidate matrix

No-client Hz below uses long **non-XR** repetitions where available; `s` means
one short non-XR run. XR-enabled short Hz is reported separately below. Physical
Hz is historical only for A0. RTF is Hz/30; no comfort field is inferred from Hz.
`Public + private adapter` means supported native primitives reached through
experiment-only Camera/S2/preview internals. No row is QUALIFIED.

| Candidate | Correctness | No-client Hz | Physical Hz | RTF (non-XR) | XR comfort | Camera semantics | D0 compatibility | Recording compatibility | Implementation risk | Public/private API | Status |
|---|---|---:|---:|---:|---|---|---|---|---|---|---|
| A0 current | XR real pixel lag | ~11.68 historical | ~6 historical | ~0.390 | Historical baseline | Live 3×640×480 | Schema yes; XR image phase fails | Existing seam; 4D blocked | Known phase issue | Native + existing adapter | REJECTED |
| B1 offline canonical cameras / older cost probe | Replay bounded; causal adapter open | 17.93 s | — | 0.598 s | Unmeasured | Offline 3×640×480 | Conditional on complete snapshot | State-only prototype; no admission | State closure and causal binding | Public recordables + private adapter | PROMISING |
| B1-FULL-OFFLINE | Three products/readers/panels inactive; full-state closure open | 18.75–18.91 | — | 0.625–0.630 | Unmeasured | No live RGB; offline 3×640×480 | Conditional | State-only; all rows ineligible | Replay parity and transactions | Public recordables + private adapter | PROMISING |
| C1/C2 operator previews | Valid preview shapes; no dataset frame claim | — | — | — | Unmeasured | Optional 1/3 lower-resolution previews | Outside D0 | Inherits B1 conditions | UX value vs added cost | Public tiled product + private panels | PHYSICAL TEST REQUIRED |
| D desktop-off / combined FULL-D | D-alone errors; FULL-D fails XR output probe | — | — | — | Unmeasured | XR capture requests unfulfilled | Unqualified | Unqualified | Removes required render path | Public viewport + experiment adapter | REJECTED |
| E XR scale 0.8/0.6 | Settings verified; image phase unresolved | — | — | — | Unmeasured | Dataset resolution unchanged | Live phase unresolved | 4D blocked | Readability/comfort tradeoff | Public XRSettings | PHYSICAL TEST REQUIRED |
| F RTX Minimal | Working pre-scene mode; changed shadows/material appearance | 20.26–20.37 | — | 0.675–0.679 | Unmeasured | Renderer semantics differ | Must declare renderer and close phase | 4D blocked | Appearance/segmentation parity | Supported setting + adapter | PHYSICAL TEST REQUIRED |
| G TiledCamera | Held-state roles; dynamic 4B proof missing | — | — | — | Unmeasured | One 3-view atlas, separate roles | Conditional on 4B reconstruction | Not an admitted capture product | Shared producer identity | Public tiled API + private integration | PROMISING |
| H CPU physics | Numeric differences measured; contacts unqualified | 11.52 s | — | 0.384 s | Unmeasured | Live phase unresolved | Schema yes; dynamics require qualification | 4D blocked | Dynamics cost exceeds small observed gain | Public SimulationCfg | REJECTED |
| I/J control↔XR cadence | J: four physics/two renders verified; wall-cadence split open | 18.31–18.39 | — | 0.610–0.613 | Unmeasured | J live phase still unqualified | No extra decisions; images unresolved | Could combine with B1 later | Comfort and scheduling | Public step/render + private adapter | PHYSICAL TEST REQUIRED |
| K 90/45/30 | Not investigated beyond classification | — | — | — | Unmeasured | Undetermined | REQUIRES S1 REQUALIFICATION | Blocked | Changed dynamics | Not prototyped | NOT TESTED |

A0 is rejected as an already-qualified **XR recording** architecture, not removed
as the canonical runtime/reference. H is rejected from primary optimization
selection on current evidence, not claimed unsupported. “Conditional” is not a pass.

Short XR-enabled/no-client results (clean except D, explicitly marked) (160 controls, 30 warmup; retained reset
costs): A0 **6.365 Hz / RTF 0.212**; FULL **8.291 / 0.276**; older B1-cost
**8.180 / 0.273**; J60 **10.890 / 0.363**; E08 **7.186 / 0.240**; E06
**7.985 / 0.266**; F **12.373 / 0.412**; D **6.843 / 0.228 (invalid render-buffer trial)**. FULL-D reached
**23.731 / 0.791**, but failed the subsequent XR-display-output check; this is not a usable
XR throughput result.
C1-640/C1-320: **7.052/7.119 Hz**; C2-320/C2-256: **6.792/6.801 Hz**;
G-tiled640 with visible operator panels: **6.456 Hz**. Short values are screening
results, not replacements for independent long repetitions or physical trials.
Exact timing distributions, render/app costs and failures are in
[short results](short_results.json); all raw samples are retained.

## Long benchmark repetitions

Each row is an independent non-XR/no-client process: 300 warmup + 3000 measured
controls. Units are ms except CV, Hz and RTF. No samples removed. `wall Hz` includes
inter-control logging overhead. Full distributions for render/app and other
stages, count checks and rolling ranges are in [long results](long_results.json).

| Candidate/rep | Mean | Stddev | CV | p50 | p90 | p95 | p99 | p99.9 | Max | Hz | Wall Hz | RTF | Render/app mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| J60/1 | 54.369 | 5.032 | 0.093 | 52.551 | 60.361 | 68.910 | 72.044 | 80.265 | 92.265 | 18.393 | 18.341 | 0.613 | 30.096 |
| J60/2 | 54.624 | 5.097 | 0.093 | 52.866 | 59.713 | 69.261 | 71.995 | 81.637 | 112.498 | 18.307 | 18.255 | 0.610 | 30.227 |
| J60/3 | 54.477 | 4.924 | 0.090 | 52.795 | 58.695 | 68.969 | 72.241 | 79.776 | 83.751 | 18.356 | 18.305 | 0.612 | 30.212 |
| B1-FULL-OFFLINE/1 | 52.880 | 4.911 | 0.093 | 51.255 | 55.932 | 67.365 | 70.669 | 79.211 | 113.786 | 18.911 | 18.855 | 0.630 | 27.993 |
| B1-FULL-OFFLINE/2 | 53.013 | 4.882 | 0.092 | 51.419 | 56.258 | 67.751 | 70.403 | 78.390 | 112.321 | 18.863 | 18.809 | 0.629 | 28.038 |
| B1-FULL-OFFLINE/3 | 53.338 | 5.162 | 0.097 | 51.679 | 56.526 | 68.039 | 71.264 | 82.828 | 125.692 | 18.748 | 18.694 | 0.625 | 28.192 |
| F-minimal/1 | 49.246 | 6.444 | 0.131 | 46.473 | 58.571 | 63.111 | 71.550 | 106.286 | 125.880 | 20.306 | 20.241 | 0.677 | 23.783 |
| F-minimal/2 | 49.347 | 6.616 | 0.134 | 46.409 | 59.356 | 63.722 | 72.459 | 105.506 | 108.300 | 20.265 | 20.200 | 0.675 | 24.045 |
| F-minimal/3 | 49.095 | 6.385 | 0.130 | 46.369 | 59.038 | 63.537 | 70.722 | 78.794 | 152.059 | 20.369 | 20.303 | 0.679 | 23.655 |

Rolling mean ranges (all overlapping windows; raw window arrays retained):

| Candidate/rep | 100-tick mean ms min–max | 300-tick mean ms min–max |
|---|---:|---:|
| J60/1 | 53.305–56.910 | 53.896–55.195 |
| J60/2 | 53.547–56.701 | 53.995–55.412 |
| J60/3 | 53.660–55.689 | 54.070–55.044 |
| B1-FULL-OFFLINE/1 | 51.982–54.300 | 52.393–53.476 |
| B1-FULL-OFFLINE/2 | 52.200–54.861 | 52.583–53.762 |
| B1-FULL-OFFLINE/3 | 52.400–54.917 | 52.728–54.194 |
| F-minimal/1 | 47.823–51.492 | 48.624–49.999 |
| F-minimal/2 | 47.763–51.178 | 48.608–50.204 |
| F-minimal/3 | 47.729–51.936 | 48.310–50.156 |

FULL keeps four physics/four presentation pumps per control; J keeps four/two.
The inherited A0 repetitions remain independently reported in the immutable
[4P3 summary](../../evidence/S2/20260921_vr_sensor_xr_scheduling/summary.json).

## Best live-runtime candidate

F-minimal has the highest measured throughput among the variants with ordinary
viewport updates still enabled, but
it changes task appearance and has no physical usability result. B1-FULL-OFFLINE
is the preferred **recording architecture to qualify next**: live state/provenance,
offline canonical cameras, optional previews. Neither throughput nor replay
completion establishes a qualified human demonstration pipeline.

## Camera phase verdict

**REAL CAMERA LAG.** See [phase findings](phase_findings.md). XR probes showed
P−1 in all three USD marker views and in the actual PhysX cube at 19/19 measured
boundaries. The cube matched previous-state projected position within 2.534 px;
current-state mismatch was roughly 64 px. Actual gripper visual silhouettes
matched native P−1 reference states with IoU 0.937–0.960; current P IoU was zero.
Reference renders advanced no physics. The no-XR control matched P/P.

This is a one-physics-substep discrepancy in the bounded stimulus, not proof of
one whole control tick or a measured wall-time headset latency. Native PhysX
state is ahead of the rendered camera content under XR. The exact internal Kit
handoff causing the phase difference is not identified. Initial invisible-sphere
and occluded-centroid attempts are retained and not treated as robot lag proof.
The 4B producer/extraction identity checks can pass while actual pixels lag;
passing them alone does not qualify a live-camera architecture. This new evidence
does not rewrite historical non-XR qualification scope.

## B1-FULL-OFFLINE — distinct maximal live candidate

The explicit strongest live variant disables **left_wrist, right_wrist and scene**
render products before XR device context entry, detaches all their RGB annotators,
and skips preview-panel binding entirely. Native camera extraction and RGB freeze
calls fail immediately after this boundary; frame counters must stay fixed and
all product-update flags must remain false. No low-resolution preview or held
camera panel is conflated with this candidate. The measured/live interval has
no canonical camera rendering, extraction, copying, upload or display. Initial
canonical scene/reset validation still produces bootstrap camera images **before**
that boundary; whole-process zero-image startup is not claimed.

The 160-control XR test completed with all three counters unchanged at 1, no
image-activity violations, no bound/visible previews, and no render-buffer errors.
The active viewport camera was `/_xr/stage/xrCamera`; it remains enabled because
the later combined viewport-off probe failed the native XR-display-output check.
No separately created preview or spectator product is added. This is the minimum
live camera-work configuration tested, not a mathematical lower bound on all
possible runtime overhead.

This distinct state stream records native articulation joint coordinates and
velocities/root poses, both rigid-object visual poses and velocities, D0 state,
post-IK/preclip labels, native commands, processor intent/provenance, available
resolved XR identities, tick/reset/run identities, camera poses/intrinsics and
full static camera attributes, stage digest, scene/task profile and backdrop
visibility. The USD dependency traversal resolved and hashed its stage, two ground
textures and OmniPBR module, with no unresolved USD asset reference. This does not
prove every transitive renderer/shader setting or dynamic visual attribute is closed.
Task outcome is explicitly not evaluated, and the snapshot-to-D0 causal adapter
remains unqualified; every row is marked **dataset_admissible=false**. Required
information capture is therefore a bounded prototype, not a complete accepted
recording artifact. Optional C previews are a separate UX cost and never a
requirement for offline image materialization.

The first attempted launch with `--profile-passes` was rejected by automatic
approval review because those extra render-only passes were considered inconsistent
with the requested restriction. It was replaced by ordinary control-loop telemetry;
the launcher now rejects that option for B1-FULL-OFFLINE. No extra profiling renders
were executed for this candidate. The older B1-cost long queue was intentionally
interrupted at startup to prioritize the separately named maximal candidate.

The completed maximal-candidate long runs achieved 18.91, 18.86 and 18.75 Hz
without XR (wall-period rates 18.86, 18.81 and 18.69 Hz), versus the inherited
11.68 Hz baseline. The short XR-enabled/no-client result was 8.29 Hz versus
A0 6.36 Hz. These are different workloads and are not physical Quest results.

The restarted maximal-candidate materialization read all 160 live state records
and wrote 480 canonical RGB images (160 three-view NPZ files, 53.91 MB). All
three roles were 640×480 RGB at every tick; no physics callbacks occurred.
Including compression and output writes, 140 states after 20 warmup achieved
7.916 states/s / 23.749 camera frames/s: **3.790 wall minutes per simulated minute**.
Peak process RSS was 6,324,736 KiB; end-of-run GPU allocation was 2,918 MiB
(end allocation, not a measured peak). Maximum position readback error was
2.17e−7 m. There were deliberately no live RGB references in this maximal run;
its images do not establish live/offline pixel parity. The earlier moving-state
validation below remains the bounded pixel comparison. See
[full replay summary](full_replay_summary.json).

The enriched live XR record averaged **8,973.8 bytes/tick**: 16.153 MB/min,
80.764 MB/5 min and 484.585 MB/30 min, before materialized images and immutable
assets. Raw live RGB alone would be 4.977 GB/min, 24.883 GB/5 min and 149.299 GB/30 min.
The smaller 5,680.6-byte diagnostic record below omits some of this enriched context.

## Offline materialization

The minimal B1 assay captured 120 deterministic controls with native robot target
motion, both grippers and both cubes; six live validation ticks × three cameras.
These are diagnostic snapshots and predecessor native targets, **not admitted
O_N/A_N training rows or a human demonstration**.

State captured: two articulations' individual rigid-link world transforms,
measured joint configurations, both cube poses, canonical measured state,
camera world poses/focal length/apertures/clipping/resolution, physics tick,
target/native command, and a flattened USD stage snapshot containing static
geometry/materials/lights/table/plates. Camera roles are explicitly ordered
left_wrist, right_wrist, scene. Static resources are not assumed immutable merely
because the stage was exported.

Replay method: public Episode Recorder recordable sample/apply primitives and
stage export; JSON diagnostic storage. A separate restarted process removes
transient `/Render` and `/Replicator` graphs from a derived stage, restores rigid
links parents first, keeps the timeline stopped, and uses native Replicator
`step(delta_time=0.0, rt_subframes=4, wait_for_render=True)`. A physics callback
observed **zero physics steps**. No native actions drive replay. The original
snapshot is preserved alongside the derived replay stage and exact code.

Three-camera correctness: 120 states materialized, 18 live/offline comparisons,
**0 exact RGB matches**, PSNR **32.01–35.82 dB**, mean absolute intensity errors
about 3.38–4.15. Read-back restored positions differ by at most
**2.50e−7 m**. Pose agreement is not a complete pixel-level geometry proof.
Color-component marker comparison had a **13.53 px maximum discrepancy** and
one component-count mismatch near a wrist-view occlusion; most matches were
within ~1.1 px. Threshold/occlusion effects and renderer configuration parity
remain unresolved; do not attribute all differences to renderer nondeterminism.
Representative images show broadly aligned task geometry with shading/edge
changes. No SSIM threshold or pixel-determinism claim is invented.

Render throughput: **10.689 states/s, 32.068 camera frames/s** with three
640×480 cameras and four render subframes. One simulated minute takes
**2.807 wall minutes**: slower than real time. This includes restore/read-back,
render and CPU image extraction, excludes process startup, and saves only six
validation image bundles; it is not full-production image encoding/storage
throughput. Measured peak RSS: **6,286,596 KiB (~6.00 GiB)**; GPU memory at end:
**2918 MiB**, not a GPU peak. Raw output sizes are in retained manifests.

Native bytes/tick: the reduced single-backend diagnostic snapshot averages
**5680.6 bytes/tick**, excluding complete XR transaction/mutable-world closure.
It projects to 10.23 MB/minute, 51.13 MB/5 minutes, 306.75 MB/30 minutes. The
original three-backend audit payload is 19,609.38 bytes/tick; sampling all three
backends averaged 11.80 ms and is not selected-backend overhead. Live RGB alone
is 2,764,800 bytes/tick: 82.944 MB/s, 4.97664 GB/minute, 24.8832 GB/5 minutes,
149.2992 GB/30 minutes, before compression and other fields. The control-loop
state-cost prototype measures its own larger actual payload separately.

### Pinned EpisodeRecorder / EpisodeReplayer audit

The installed extension is 0.1.6 in Isaac Sim 6.1. Exact sources and SHA-256s are
in [source audit](source_audit.json). The upstream abstraction is reused, not
reimplemented as a recorder framework. Its native HDF5 orchestrators were
inspected but not invoked, because HDF5 episode recording is explicitly out of
scope. The public [6.1 extension reference](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/py/source/extensions/isaacsim.replicator.episode_recorder/docs/index.html)
is contextual; pinned source and observed behavior resolve API details.

- ArticulationRecordable samples rigid-link transforms, including the root; it
  does not automatically preserve joint coordinates, velocities or actuator
  targets. RigidBodyRecordable is pose-only in the pinned implementation.
- CameraRecordable covers pose and selected intrinsic numeric channels. Lens
  distortion, aperture offsets/projection attributes and all other pixel-affecting
  settings require explicit immutable identity or additional attributes.
- AttributeRecordable supports numeric USD attributes; it does not discover and
  record every material, texture, light, visibility, topology or shader change.
  Missing values may become zero defaults, so the caller must fail closed.
- **Default USD pose sampling is unsafe here.** Fabric-driven live articulation
  poses differed from USD by up to 0.402835 m. Fabric pose sampling matched native
  positions exactly in the assay, with quaternion representation differences up
  to ~3.1e−7. USD-RT positions were within ~1.9e−9 m. Bit-exact transforms across
  every representation are not established.
- Recorder callbacks/decimation are not automatically the D0 decision boundary.
  Group writes and fallback sampling are not a causal-transaction commit protocol.
  The default replay policy is best effort, and absent camera fields can be skipped.
  The pinned pose-backend helper itself warns that Fabric/USD-RT can lag on nested
  articulations; the measured non-XR agreement is not a universal guarantee of
  exact moving-articulation snapshots under XR.
  Native strict binding is insufficient for the requested incomplete-record rule.
- The offline prototype checks required keys, finite values and shapes, rejecting
  all **26 deliberately removed channel cases**. That is a bounded negative test,
  not full corruption, truncation, asset mismatch or task-state closure validation.

Qualification checklist: restart, held-time replay, intended role selection and
bounded missing-channel rejection demonstrated. Complete exact world-state
closure, renderer/source parity, geometric discrepancy resolution, complete
O_N/A_N transaction binding and human use remain open. B1 is promising, not qualified.

### D0 semantics and real/Isaac provenance

A row `(state_N, left_N, right_N, scene_N, task, action_N)` can preserve D0 v4
when the immutable visual snapshot belongs to observation N, all three images
are materialized from that same snapshot, and action N is the post-IK,
pre-native-clipping decision made from N. Rendering later does not require
advancing physics or shifting the action. Simulated tick time remains 1/30 s;
wall-clock materialization time is separate. No interpolation or repeated image
is substituted for an intended dataset camera acquisition.

This reproduces **visual world state**, not what the human literally saw through
CloudXR, including compositor reprojection, head pose, transport delay and
controller latency. Those remain D1 QA/provenance. For real data, physical camera
acquisition and its actual timing remain authoritative. A common policy schema
can still be identical. D2 must distinguish physical acquisition from offline
state rendering; validate source kind, snapshot/tick/epoch identity, camera
calibration/config/role, renderer/version/settings/seed/subframes, stage and asset
digests, lighting/material/visibility state, preprocessing, logical timestamps,
materialization time and image/state/action alignment. Real exposure/rolling
shutter cannot be invented for synthetic snapshots. Check domain/task coverage
and temporal artifacts without requiring identical pixel distributions.

## XR optimization findings

Desktop/mirror: ViewportAPI exposes `updates_enabled`; the active viewport can
refer to `/_xr/stage/xrCamera`. It is not proven to be expendable spectator work.
A final log audit found **839 corrupted/LdrColor render-buffer events** in the
standalone D trial, despite exit zero; its 6.84 Hz is invalid as a correctness
result and that standalone selector is rejected for physical progression.
The specifically requested combined **B1-FULL-OFFLINE-D** completed 160 controls
without those errors, with all three canonical counters fixed, no panels,
viewport updates false and XR enabled/display flags true. It reached 23.73 Hz,
RTF 0.791; these flags do not prove that new headset images were rendered.
A matched functional follow-up requested two native `XRCore.schedule_capture_display_frame`
images during ordinary control pumps, with a backdrop change between them.
Viewport-on produced both images (the inspected output contains the scene and
robot); viewport-off produced neither. Both still reported XR display enabled.
No extra physics or render pumps were introduced, and no canonical images were
accessed. **Reject this viewport-off method:** it fails the required XR-output
precondition, and its high control rate cannot represent a viable XR optimization.
See [display proof](display_proof.json). The failed selector is retained for
reproduction, not queued as a surviving physical candidate.

Pinned desktop settings offer eye-image mirroring (`left`, `right`, `both`)
or leaving the viewport independent (`viewport`); no supported `off` choice
appears in that UI. `app/guiMode=minimized` hides most Kit windows but explicitly
retains Viewport and XR Settings; it is not full mirror-render removal. The
controller forces the active viewport onto the XR camera while XR viewport is
active. These sources are hashed in the audit. Consequently a visible desktop
window alone is not evidence of another full scene render.

The initial desktop-off short test inherited XR scale 0.6 and is confounded;
a controlled repeat explicitly restores 1.0. Headset rendering, SceneUI,
controls and reconnect require physical inspection even if XR flags stay true.

Resolution scale: public XRSettings
`profile/persistent/render/resolutionMultiplier` supports 1.0/0.8/0.6. Observed
per-eye application resolutions: 2048×1792, 1638×1433, 1228×1075. Canonical cameras
remain 640×480. This is an XR quality/performance tradeoff. Readability,
manipulation and discomfort are unmeasured. The explicit baseline assignment
prevents persistence in Kit's portable root from contaminating subsequent trials.

RTX mode: MinimalRendering is present. The experiment selects textured diffuse
mode 2 before camera products attach. The clean long runs achieved 20.26–20.37 Hz without XR and the short XR run
12.37 Hz. Validation images retained cube/plate colors but showed harsh black
shadows and a darker robot; manipulation readability remains unmeasured.
Switching it hot inside the first assay
caused CUDA error 700; that failure is preserved and this switching method is
rejected. Lower-cost images may change task-relevant material/shadow appearance;
segmentation/privacy output is not qualified here. Offline higher-quality rendering
needs declared renderer semantics and parity tests, never silent substitution.
See the [official render-mode reference](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/reference_material/rendering_modes.html).

CPU physics: supported through SimulationCfg `device='cpu'`; this changes the
PhysX execution/broadphase path. The 120-control identical-target GPU/CPU comparison had maximum joint-state
difference 0.04491 degrees, gripper difference 0.00938 mm, cube position distance
1.11e−6 m and link position distance 2.12 mm. See [CPU comparison](cpu_comparison.json).
This is numerical difference, not equivalence acceptance. Static-hold throughput cannot establish contact,
saturation, reset and manipulation equivalence. No physics-mode promotion or
claim of unchanged dynamics is made.

## Tiled camera and operator previews

The pinned ordinary Camera already uses a tiled render product for each camera;
TiledCamera is a deprecated alias. The meaningful comparison merges three
one-view products into one three-view product. Public
`rep.create.render_product_tiled(cameras=[...], tile_resolution=(640,480))`
accepts the two independent moving wrist-camera prims and world-fixed scene prim.
Three views occupy a 1280×960 atlas with an unused tile; role extraction and
producer ownership must be explicit. A shared producer plus tile index could
represent 4B identities, but this is not implemented/qualified as canonical capture.

Initial static active-XR costs were 20.25 ms RTX/pass with sensors versus
14.15 ms without. One 320×240 preview: 15.77 ms; three 320×240: 16.03 ms;
three 256×192: 15.94 ms; three 640×480 tiled: 17.34 ms. These later figures are
**exploratory only**: product creation/destruction produced corrupted renderVar
warnings and the first 640×480 one-camera product was empty. API default reuse
had returned an existing disabled product. Independent process previews use
`force_new=True` and preserve those failures. The API docstring warns about mixed
resolutions; the pinned modern-Kit implementation has per-product auto sizing,
so neither support nor incompatibility is inferred from that older blanket note.

A clean, single-resolution matched-state repeat resolved the initial API-reuse
confound: three independent products cost **20.282 ms RTX/pass**, versus
**17.357 ms** for the three-view atlas (14.4% lower); host render time was
22.197 versus 19.931 ms. Physics stayed at the same step. Each intended role
matched its own tile best; left/right/scene PSNR against independent products was
45.31/44.92/29.39 dB, with no exact image matches. Visible scene shading and edges
differed. This is useful cost evidence, not dynamic-camera or 4B identity
qualification. See [clean tiled summary](tiled_summary.json).

Clean separate-process XR preview trials cost 16.56 ms/pass for C1-640,
16.35 for C1-320, 16.86 for C2-320, 16.80 for C2-256 and 18.15 for G-tiled640.
C2-256 provided only 0.01 Hz over C2-320 in this short trial; further resolution
sweeping was stopped. Panels were visible in these runs, whereas baseline panels
were mostly hidden: this is a complete operator-UX cost comparison, not an
identical-panel-visibility camera-only comparison.

C0 has no panels. C1 uses one scene-only operator preview; C2 uses all three
lower-resolution views. Their product buffers and CPU panel uploads are not
training observations. C3's held texture already follows the existing ON_DEMAND
panel behavior between uploads; holding a panel texture alone does not disable
active sensor rendering. The small 320-to-256 cost difference does not establish
a worthwhile readability tradeoff. Preview panel latency/usefulness need a human;
application upload timestamps are only proxies.

## Control/XR split

Pinned SimulationContext supports physics steps with `render=False`, and a
separate `render()` pumps Kit with physics simulation disabled during the pump.
This supports sequential presentation of a committed state without another
physics step or decision. No supported independently scheduled 45/60 wall-Hz XR
thread has been demonstrated; no custom multithreading was built.

J60 keeps four physics integrations and two renders per control, rendering after
substeps 2 and 4. This is **60 simulated Hz nominal presentation**, not guaranteed
60 Hz on the headset. Reset's 25-substep settling path explicitly renders its
final boundary. Per-control instrumentation checks actual physics/render/Kit
counts. It halves shared pumps; it does not establish that the live camera lag is
fixed. The future B1 combination can remove dataset products from these pumps.
K (90/45/30) and 30 Hz physics were not implemented because less invasive options
remain unqualified; K would require renewed S1 dynamics qualification.

## Physical results

No new physical runs. All comfort, head-motion latency, controller response,
panel usefulness, manipulation difficulty and nausea fields are **NOT MEASURED**.
Earlier comfort observations retain their original measured/operator-reported
classification. Follow the [physical queue](README.md) for interleaved A–C–A–C
trials, at least five minutes per measured run after equal warmup. Do not compare
short no-client timing with a headset trial as if they were the same workload.

## Recommended architecture and what changes in 4D

Prioritize **B1-FULL-OFFLINE: state/action live plus offline three-camera materialization** for the
next architecture qualification, with J60 as a separate presentation candidate.
This attacks measured sensor cost, avoids the observed live camera phase gap,
and reduces the live buffer size substantially. It has not yet won the full
multi-objective comparison: comfort and task usability are unknown, pixel/asset
closure and D0 snapshot transaction binding are incomplete, and offline rendering
is 2.81 times slower than real time before full output encoding, or 3.79 times
slower when all three compressed images are written for each maximal-run state.

Do not start 4D. If B1 subsequently qualifies, the recommended native artifact is
an immutable stage/asset manifest plus a tick-indexed native visual-state stream
and the existing canonical state/post-IK-preclip action/native-command/XR/epoch/
transaction provenance. Evaluate native Episode Recorder V2 HDF5 visual channels
with explicitly declared additional numeric fields and strict validation, or the
existing Isaac Lab RecorderManager state/provenance terms, at that later step.
Do not introduce an opaque second robotics/recording framework. This experiment's
JSONL is diagnostic evidence, not the selected production artifact or final LeRobot
row format. Buffer complete state/provenance rather than RGB if qualified; join
offline materialized images by immutable tick identities, fail closed on incomplete
state or a mismatched renderer/asset/camera manifest, and admit only completed
O_N/A_N transactions. Preserve task/outcome and successor links explicitly.

## What no longer needs to exist

Conditional on a later B1 selection: live canonical training RGB render products,
the ~0.83 GB/10 s image ring, large RGB tensor stacking peaks, and coupling operator
preview resolution to dataset resolution. None has been removed from canonical
runtime in this step. Final data still contains all three 640×480 canonical views
at 30 logical FPS and D0 v4 state/task/action.

## Gates

D0: schema/action semantics unchanged; new B1 adapter unqualified.
S0: no environment acceptance change.
S1: historical tested dynamics scope retained; CPU mode and any 90 Hz proposal
need separate qualification; live XR pixel lag is recorded as additional scope.
S2: unresolved; no physical architecture qualification.
D1: blocked; no episode, converter, admission or acceptance.

Final verdict: **NO ARCHITECTURE QUALIFIED — physical comfort/task trials, B1
complete visual-state/asset closure and causal snapshot binding, and live-camera
XR phase correctness remain unresolved.**

## Implementation discipline and artifact scope

Reused: pinned Episode Recorder recordables/stage export, Replicator held-time
orchestration and tiled products, native SimulationContext scheduling, original
S2 device/processor/IK/control loop, SceneUI panels and canonical preview isolation.
The experiments add bounded probes, launch selectors, timing analysis and explicit
process-only adaptations. They add no solver, protocol, simulator abstraction,
recorder replacement, converter or dataset format. JSON snapshots/JSONL are
non-admissible prototype evidence only. Private integration points are explicitly
identified: existing Camera render-product handles for update suppression,
S2 method/import interception, and native feed-manager/panel handles for previews.
Public support for a lower-level feature does not make these adapters public APIs.

A size re-audit was performed across the experiment scripts: separate focused
probes cover phase, state replay, cost, selectors and analysis; each integration
probe remains bounded and separately scoped. The aggregate research harness exceeds the project's
1000-line re-audit threshold, so it is retained only as this bounded experiment,
not promoted as a new runtime subsystem. A subsequent implementation must replace
this import-hook/source-substitution harness with the selected minimal integration.

The precise provisional B1 native artifact recommendation is an episode directory
containing **`stage_snapshot.usd`, `manifest.json`, and `episode_state.hdf5`**:
use upstream native state/provenance channels, with an explicit closed list of
visual attributes/assets, canonical state, post-IK/preclip action, native command,
XR receipt, tick/epoch and causal completion/outcome fields. The 4D follow-up must
choose the audited native writer and atomic commit binding after B1 qualification;
this is an artifact contract recommendation, not a claim that today's default
EpisodeRecorder or RecorderManager already writes those complete semantics.
Do not buffer live RGB tensors for that design. No such HDF5 artifact was created
in this experiment; the prototype JSON cannot be admitted in its place.

## Retention, registrations and checks

Raw timing arrays, every 100-/300-tick window, exact configs and commands,
executed source versions, failed attempts, CPU/GPU traces, phase images and
bounded replay outputs are retained in:
`/data/ebulochkin/vla-runtime/evidence/20260921_vr_architecture_bakeoff/architecture-bakeoff.tar.gz`.
Verified SHA-256: `e1a7d41052e2116e81476c2f344372bdb40ccf6be9d1fe847ed90270938b50ea`.
The archive contains 2,102 inventoried files, 936,092,860 uncompressed bytes,
376,218,141 compressed bytes; member bytes were rechecked against their hashes.
The sibling `files/locator-map.json` maps original paths to retained members.
Kit caches are excluded; directly resolved USD assets and pinned audited source
files are included. Only small summaries, documentation and experiment scripts
are in Git. See [provenance](provenance.json).

Core/topic regression: **218 tests passed**; an existing read-only NumPy/PyTorch
warning remains. Intermediate governance attempts caught new files not yet
staged/indexed; those inventories were completed and the suite rerun successfully.
Python compilation and Ruff F/E9 checks pass. Documentation governance is checked
against trusted preservation base `8d854b94c91a3a9e051e742fa7dd6b6a0a0939c4`;
contract/spec-reference/selective-MANIFEST checks are recorded in [checks](checks.txt).
No runtime tool, entrypoint or runtime config differs from the canonical commit.
All gate states remain unchanged; new evidence is bound to unresolved S2 only.

Long FULL runs sampled peak device allocation (including startup) at 6,738–6,802
MiB; process maximum RSS was 7,629,276–7,643,948 KiB and measured CPU use averaged
232–234% where one busy core is 100%. F sampled 6,460 MiB GPU and 279–281% CPU.
J's older instrumentation did not record per-process CPU/RSS; its sampled GPU
peak was 6,849–7,105 MiB. These are allocation/utilization observations, not
per-camera GPU attribution. FULL has no extra profiling render passes.
State-only summaries' native `camera_failures` counter means no live valid image
was supplied by design; all such rows remain dataset-ineligible. Actual product
reenable/extraction violations fail immediately and are reported separately.
