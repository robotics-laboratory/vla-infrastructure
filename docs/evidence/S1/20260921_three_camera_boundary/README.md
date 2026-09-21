# Three-camera boundary qualification

Scope: development source over `b3577b4613d0669efcee72493b66e4148de745c3`,
with exact source hashes and launch manifests in [provenance](provenance.json).
This is bounded non-human camera/runtime evidence, not S2 or D1 acceptance.
D0 v4 semantics, its fingerprint, and real recording code are unchanged.

## S1 consistency and upstream reuse audit

Capability: exact VR state/three-camera observation boundary, with S1 regression.
Plain S1 qualifies embodiment, native control/reset, and the two wrist mappings;
its compatibility observation is not a complete D0 v4 training source. Current
contract/processor descriptions now state that scope. The Isaac recording profiles
own the full three-camera source view; runtime recording admission remains pending.
Historical accepted S1 evidence and historical D0 evidence retain their bytes/scope.

Pinned upstream: IsaacLab `0c2e2c64e51922d088b695d72ffe03faa5c6b95d`, Sim 6.1,
Kit 110.3, SDK environment and all package pins in the retained launch manifests.
Upstream already owns Camera, SensorBase, Articulation, physics, RenderContext,
KitVisualizer and the shared RTX app pump. The remaining gap is boundary ownership,
all-or-none publication and non-acquiring current-capture access. A thin composition
adapter supplies these; no renderer, sensor framework, recorder or environment is
added. Core tests use the existing reconciled core environment; runtime checks use
the existing isolated Isaac SDK. No dependency or environment changes were made.
The existing integration module is already above the repository's size threshold;
this repeated audit keeps the new barrier in a 153-line module and small integrations.

## Exact production order and reset

For each physics substep, environment target writes precede `before_render()` and
preview isolation checks. `sim.step()` increments the physics counter, simulates
and fetches results, then calls `render()`. Rendering refreshes physics/Fabric,
updates visualizers, runs callbacks, and increments render generation. Kit app
pumping disables Kit-owned physics. Articulations then receive `update(dt)`;
the VR rig accumulates elapsed simulation time without extracting cameras. Probe,
preview and VR scene updates finish. At the end of the requested advance, measured
state is read from refreshed articulation buffers; the barrier updates each of
left wrist, right wrist and scene exactly once at that unchanged boundary.

Upstream Camera increments its frame before extraction. SensorBase marks its
completed data generation only after extraction returns. Both are checked, as are
buffer shape/dtype and the producer before/after extraction and consumption.
The producer includes reset epoch, physics step and render generation. Publication
adds a successful capture cycle, per-camera frame/generation and immutable state.
Failed bundles publish nothing; successful cycle does not advance. Reset invalidates
old identities even when camera counters restart. A missing/failed startup or reset
capture fails; ordinary RUN retains its existing health-guard policy while consumers
cannot obtain a rejected capture. Future RECORD admission/abort policy is separate.

Reset remains 24 non-evidence settling steps plus completion, not 25-to-24 arithmetic.
Tests execute the actual environment methods: old state/image steps 25/24, 29/28,
33/32 become 25/25, 29/29, 33/33. The canonical launcher preflight reaches 120;
the existing S2 reset reaches 145 before the first control observation. Live DIAG
records both, with preflight explicitly ineligible. Subsequent reset events remain
in the existing loop; the final boundary is physics/render step 339, epoch 4.
Steady state remains action at P, four physics steps, one capture at P+4. Consumers
reuse this capture. There is no hidden fifth physics step or per-camera render.

## Render-pump failure found and rejected

An initial counter-only headless DIAG run reported PASS, retained as
[counter-only result](counter_only_headless_result.json), but it is **disqualified**.
The [headless S1 result](headless_s1_failure_result.json) showed unchanged RGB despite
changed wrist poses: camera identity/reset-image tests failed, while model parity
passed. Pinned KitVisualizer returns early in headless mode yet advertises
`pumps_app_update() == True`; the shared RTX helper consequently skips pumping.
Counters and SensorBase completion alone do not prove current pixels.

The final barrier additionally requires the pinned Kit visualizer's completed
app-pump receipt. `HEADLESS=1` is explicitly unsupported and rejected before any
successful capture. The final negative launch and exact error are retained in
provenance. No SDK patch, extra repair render, or physics step was introduced.
Canonical non-headless Kit rendering works without a Quest client; its
[S1 regression](s1_result.json), [RUN](run_result.json) and [DIAG](diag_result.json)
all pass with clean shutdown. This does not qualify a headless renderer or physical
XR. Initial cold startup was interrupted before evidence while compiling/loading;
a fixture NameError was corrected before the focused test pass.

## Tests, performance and limits

[Capture tests](capture_tests.txt) include partial failures in each role, scene-first
failure ordering, frozen scene, stale completed generation, missing/wrong buffers,
producer/reset changes, new-epoch frame collisions, repeated valid pixels, state
mismatch/read-time advancement, repeated consumption, owned freeze without render
or acquisition, plain S1 scheduling and actual reset/startup methods. Existing
RUN/DIAG control parity tests cover native targets, clutch, sensitivity, gripper and
tracking recovery; the same rig and barrier have no mode-dependent scheduler.
[Offline output](offline_tests.txt) covers the wider practical suite. The
[first offline attempt](first_offline_attempt.txt) preserves registry hash failures
before configuration artifact registration; no test semantics were weakened.

Synthetic before/after uses the exact base scheduler and final production methods:
300 controls each perform 1,200 physics/render steps and 900 camera updates.
Mean synthetic control time was 19.49 us before and 48.69 us after; this measures
Python adapter overhead with fake cameras, not GPU throughput. No mandatory RGB
CPU copies were added; only small measured state/counter transfers are required.
The optional `freeze()` performs three owned CPU RGB copies, never acquisition.

Canonical DIAG measured mean control 119.59 ms (including reset events), camera
update/capture 2.88 ms; RUN achieved about 8.47 controls/s in this bounded no-client
run. Nominal simulation timing remains 120 Hz physics / 30 Hz control. These are
not 30 Hz wall-time or D1 performance qualifications. No valid before-change GPU
baseline was retained, so a GPU performance regression comparison is not claimed.
Render-generation delta equals physics-step delta (194 including resets); no
second scene render is requested for capture consumption. Existing diagnostics
and visible previews retain their own copy costs.

## Registration and remaining work

The previous selected VR configuration is preserved byte-for-byte as
[previous VR config](previous_vr_config.yaml), SHA-256
`148baa3da2fdb37d56ef6fb3e310ec3497df4ed3736bf7e8125358c5cea4ec41`.
Only its old artifact locator moves; its identity remains unchanged. The new
configuration and evidence have new IDs. Final verification is in
[validation](validation.json). S1's new canonical regression supplements its
historical acceptance; D0/S0 stay accepted and S2/D1 unresolved.

Remaining: resolved XR identity and preclip action extraction; RecorderManager/HDF5;
converter; performance and physical D1. No recorder, actual dataset source, action
recording, episode buffers, converter or physical human evidence was added.
