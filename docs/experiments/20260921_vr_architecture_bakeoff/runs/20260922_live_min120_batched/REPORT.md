# LIVE-MIN120-BATCHED qualification

Frozen failed diagnostic record. Owner: `vr.performance`. This run created no
dataset observations, changed no canonical runtime or D0 semantics, and does not
qualify a physical candidate.

## HEAD

- Tested SHA: `5316ec03da08a4f09e5764d838fefa6136d081bf`
- Branch: `wip/vr-recording`
- Worktree: `/home/ebulochkin/vla_infrastructure/.worktrees/vr-recording`
- Candidate source was copied into the isolated launch output; its hashes and
  exact command are retained in `launch.json`.

The worktree was clean at the expected SHA before implementation. Host inspection
found no Isaac, Kit, CloudXR, OpenXR, or `run-vr` process, no relevant listener,
and no GPU compute client before the first launch.

## Pinned Camera API

`TiledCamera` deprecated: **YES**. In the exact installed pin it is a compatibility
subclass of `Camera`; its constructor emits a deprecation warning and delegates to
`Camera`. `TiledCameraCfg` likewise subclasses `CameraCfg`. No deprecated class was
instantiated or modified.

One `Camera` supports multiple prims: **YES**. It resolves every prim matched by
one full-path regex into one `FrameView` and one `CameraRenderSpec`. Isaac RTX then
calls `render_product_tiled` once with that camera-path list. Public output has an
explicit view dimension `(N,H,W,C)`.

The three cameras can retain heterogeneous transforms: the wrist USD camera prims
remain children of their moving gripper links and the scene USD camera remains
world-fixed. Pose buffers refresh from the `FrameView`; the Isaac RTX backend's
camera update is deliberately a no-op because Replicator reads the USD camera
prims directly. A single config shares resolution, requested AOVs, renderer,
depth policy, and ISP. The canonical cameras already share 640 x 480, RGB,
clipping `[0.02,10.0]`, and renderer settings, so the experiment used one RGBA
batch and projected owned RGB role arrays.

The complete path, digest, line, and source finding record is in
`pinned-camera-audit.json`.

### Implementation discipline / size re-audit

- Capability/gates: bounded three-view acquisition experiment affecting D0/S1/S2/D1
  scope, with no gate-state or canonical-runtime change.
- Pinned upstream candidates: `Camera`, `CameraCfg`, `CameraData`, `SensorBase`,
  `FrameView`, `IsaacRtxRenderer`, `CameraRenderSpec`, `TiledCamera`, and
  `TiledCameraCfg` from the declared Isaac environment.
- Upstream ownership: camera prim matching, batched view storage, tiled render
  product, annotator extraction, atlas-to-batch projection, USD camera transforms,
  and frame/data generations.
- Exact remaining gap: compose three already-authored canonical prims under one
  regex-backed owner, project the public batch to explicit roles, freeze RGB, and
  prove depicted state from pixels because upstream counters lack source-state
  identity.
- Narrow adapter: one experiment-only constructor/capture adapter plus extensions
  to the existing content probe. It creates no renderer, scheduler, recorder,
  camera framework, or production abstraction.
- Environment impact: none; the frozen Isaac installation and canonical scene,
  physics, control, and render loop were reused through the process-local hook.
- Framework decision: the one known three-role batch and its failed qualification
  require no reusable asynchronous or simulator abstraction. The larger probe
  remains diagnostic code because it retains per-boundary witness evidence.

## Current vs batched ownership

Before:

- Camera instances: 3
- render products: 3 independently owned tiled products, each with one view
- output buffers: 3 independent one-view buffers

After:

- Camera instances: 1 genuine upstream `Camera`; role adapters are not sensors
- render products: 1
- output buffers: one `uint8` RGBA buffer with shape `[3,480,640,4]`
- final owned payload: three RGB `[480,640,3]` arrays, 2,764,800 bytes total

The renderer enumerated scene, left wrist, right wrist. The experiment did not
assign role meaning to that incidental order: it checked the render-spec paths
against the initialized sensor prims and resolved the explicit path-to-role map
`scene=0`, `left_wrist=1`, `right_wrist=2`. Missing, duplicate, or reordered paths
fail closed. See `batched-ownership.json`.

## Dynamic role support

The render-only viewpoint assay advanced physics from 149 to 149. It exercised
left-only motion, right-only motion, and both arms, using two renders per pose.

- Left-only: left camera moved 0.042993 m; right and scene camera poses moved 0.
- Right-only: right camera moved 0.042993 m; left and scene camera poses moved 0.
- Both: both wrist cameras moved 0.042993 m; scene camera pose moved 0.
- Every role's visible RGB changed in every phase; mean absolute changes ranged
  from 6.684 to 45.476 intensity units.
- Exact USD paths remained bound to their declared roles; there was no role swap.

Verdict: dynamic role semantics **PASS**.

## Temporal qualification

Runtime stayed fixed at 120 Hz physics, 30 Hz control target, four physics steps,
one render, RTX Minimal mode 2, XR scale 0.4, three 640 x 480 views, hidden preview
panels, and owned RGB copies. The classifier used visible kinematic PhysX cubes in
both wrist views and the scene view, with robot articulation retained as a
secondary witness. It distinguished N, N-1, N-2, and N-3 from content; counters
were retained only as extraction identities.

Two render-only primes preceded 300 consecutive changing boundaries. The result:

| role | 0 | -1 | -2 | -3 | unresolved |
|---|---:|---:|---:|---:|---:|
| left wrist | 1 | 298 | 0 | 0 | 1 |
| right wrist | 0 | 293 | 0 | 4 | 3 |
| scene | 0 | 299 | 0 | 0 | 1 |

Nine boundaries had cross-view disagreement: 29, 104, 106, 122, 146, 204, 206,
214, and 242. The decisive strong right-wrist N-3 classifications occurred at
106 and 206 with reference-feature separation margins of 26.401 and 26.549;
left and scene were N-1 at both boundaries. At every failure the batch still had
one render delta, one Kit update, and identical frame/data-generation/extraction
IDs across all three roles. Those common IDs therefore do not prove content
cotemporality even inside one tiled product.

- Short 300: **FAIL**
- Long 3000: not run by stop condition
- Classification: **CROSS-VIEW DISAGREEMENT / TIME-VARYING**

`classifications.jsonl` retains all 300 raw boundary classifications and witness
errors. `short-summary.json` retains the full histogram, role assay, priming,
ownership, and timing summary.

## Startup priming

Two batched frame bundles were discarded and physics did not advance (149 before
and after). The recorded 186.866 ms interval also includes the preceding eight
render-only dynamic-role frames, so it is not claimed as an isolated two-prime
cost. Instability persisted through boundary 242 and is not a startup transient.
No fake or duplicate observation was accepted.

## Deferred binding

Required in the dominant case: a common N-1 delay would require one tick. It is
not safe here because the common-offset invariant failed. No observation was
published, and canonical `state_N + left_N + right_N + scene_N + action_N`
semantics remain unchanged.

## Terminal drain

The successful 8-boundary rehearsal reached the final state after two render-only
drains with zero physics advancement: the first batch remained N-1 and the second
was N for all views. This is diagnostic only. The required 300-boundary temporal
gate failed first, so terminal drain is not qualified for this candidate.

## Epoch/failure tests

Reset, recenter, session recreation, injected missing extraction, wrong batch
size, ordering corruption, duplicate/stale batch, mutable alias, generation slip,
and epoch crossing were not run after the mandatory temporal stop. The adapter
does fail construction/capture on wrong path sets, duplicate role indices, wrong
batch shape/dtype, non-atomic frame/generation advance, replaced storage, and
producer-boundary change, but these checks cannot repair the observed pixel-source
instability.

## Performance

Not run. The 300-boundary content loop's diagnostic mean was 42.418 ms (about
23.575 boundaries/s), p50 42.294 ms, p90 45.088 ms, p95 46.137 ms, p99 49.334 ms,
p99.9 54.102 ms, and max 54.554 ms. These are not accepted dataset throughput or
a performance classification because no semantically valid observations exist.

## Comparison with three independent Camera instances

Ownership improved from three render products to one, but temporal semantics did
not: the prior independent-camera run had right-wrist N-3 slips and this unified
product still produced four right-wrist N-3 classifications plus unresolved and
left/scene exceptions. Render cost and qualified throughput were not compared
after the correctness stop.

## Physics regression

The diagnostic retained 120 Hz physics and exactly four steps per tested control.
The camera-only dynamic assay advanced zero physics. Focused native-target,
trajectory, contact, and reset regressions were not run after temporal failure;
no 60-vs-120 study was repeated.

## Physical candidate

- saved: **NO**
- candidate ID: none
- command: none

The correctness prerequisite failed, so `LIVE-MIN120-BATCHED` is not queued for
physical use.

## D0 and gates

- D0: unchanged; no contract change required
- S0: unchanged
- S1: unchanged
- S2: unresolved; no acceptance claim
- D1: unresolved; no dataset observation published

No 4D work, canonical promotion, deprecated `TiledCamera` experiment, performance
tuning, or push was performed.

## Verdict

**BATCHED CAMERA TEMPORAL SEMANTICS UNSTABLE**
