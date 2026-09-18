# Production Isaac runtime migration

## Scope and exact baselines

Home production checkout baseline: `404d859cbc189e7dc661f2125d59e838ceee69fd`.
Deployed integration/source baseline: `60eb2605909557dbefd1e5c02db18bfa80c1217d`.
The new migration is staged in an isolated worktree. Runtime tests use the declared
Isaac launchers; executable SDKs and all bulk outputs are under `/data`.

The two baselines differ: the older home checkout has processor v1, while the
already prepared/deployed integration has v3. REP-02 does not introduce processor
behavior; it reconciles stale v2 config/contract metadata with that existing v3.
Publishing that integration into home also publishes its prior S2 remediation.
Historical physical S2 FAIL/PARTIAL evidence is preserved, and no physical PASS is
inferred from no-client tests. A/B/C/D0, authoritative model, core pins, policy/data
contract, MuJoCo and EnvHub/process-boundary decisions remain unchanged.

## REP-01

Upstream source `ae37b028ea415c91ea2bc32609efcd759ed2b974` declared editable package
versions17.0.2 and0.16.3, while its lock listed17.0.1 and0.16.2. The lock-only amendment
`0c2e2c64e51922d088b695d72ffe03faa5c6b95d` changes exactly those two fields. No upstream
runtime source or dependencies are modified. `materialization.json` and
`upstream-lock.patch` reproduce this exact commit from its upstream parent.

A new environment was created from frozen spec at
`/data/vla-infrastructure/isaac61_production/env`. All287 installed packages match
the lock. Repeated `uv sync --frozen --extra teleop --offline --dry-run` with the
pinned base interpreter and `--no-managed-python` reports `Would make no changes`.
No hidden pip install. Six inherited upstream metadata override conflicts remain
explicit; exercised S1/S2 paths must pass, not merely package resolution.

## REP-02

Canonical processor: `piper_x_isaac_s2_bimanual_relative_v3`.
Code SHA-256: `b75f86884e0b2a80886425229aae901ba3aad5fa6d4de2ec86bff8cd41fc053c`.
The code is unchanged relative to integration60eb260. Both SDK configurations and
the live contract must use this revision. Startup rejects config/code mismatch.
Historical config bytes/hash are preserved in `legacy_s2_config.yaml`; old evidence
is not re-hashed to pretend it exercised v3 on this new SDK.

## Exact pins

| Component | Legacy accepted runtime | Final candidate |
|---|---|---|
| Isaac Sim |6.0.1.0|6.1.0.0|
| Kit |110.1.2+production.326809.f9bf0dda.gl|110.3.0+feature.371399.00c488ae.gl|
| Isaac Lab source |913ac53f51b2f8d02c9e121caa4cbdd06262948e|ae37b028ea415c91ea2bc32609efcd759ed2b974|
| Reproducible source+lock revision |913ac53f51b2f8d02c9e121caa4cbdd06262948e|0c2e2c64e51922d088b695d72ffe03faa5c6b95d|
| isaaclab package |16.4.0|17.0.2|
| isaaclab-rl |0.16.0|0.16.3|
| isaaclab_teleop |0.8.0|0.9.0|
| IsaacTeleop |1.4.98rc1|1.4.98rc1|
| CloudXR |6.2.1|6.2.1|
| Python |3.12.13|3.12.13|
| torch / CUDA |2.11.0+cu128 /12.8|2.11.0+cu128 /12.8|
| NVIDIA driver |580.159.03|580.159.03|

Final lock SHA-256: `f633120f145944672d9ba3d6a7bda9a145a01b6295e9fc08f0997e60dc6a40e7`.
`final-inventory.json` records all package versions and provenance. Actual initialized
runtime reports record `module.__file__`; critical modules must all resolve under
the final SDK/source, with LeRobot absent. Gate B/core keeps its distinct pin.

## Combined validation design and topology

The actual canonical S1 robot asset is used (SHA-256
`103af50b99b17e4ff962b7f563459672ad89556661de79cbd30c1792fea92a6f`).
Two policy wrist views use the unchanged upstream batched Camera. The existing
upstream camera feed manager/SceneUI presenter consumes those buffers and a third,
presentation-only scene feed. A thin presentation adapter selects left/right batch
indices. No policy camera role or sensor semantics are changed.

Topology: world geometry remains unpartitioned/shared. Every concrete sensor Camera
has `omni:scenePartition=vla_sensor_world`; every SceneUI draw system and its Gprim
descendants inherits `primvars:omni:scenePartition=vla_xr_preview`. XR camera is an
unassigned spectator with `showAllPartitionsByDefault=true`. Both renderer partition
settings are enabled before startup; assertions check concrete paths/descendants
before rendering and after preview creation. The padded second scene-camera view is
also tagged as sensor. A one-view scene camera was rejected by upstream RenderContext
(`num_envs2 vs1`), so its batch has two views; only the first is presented.

The diagnostic adds a presentation-only magenta marker, positions real panels in
front of moving cameras, and independently observes the panel from witness views.
Raw renderer RGB(A), native Camera RGBA, actual preview input, camera transforms,
panel transforms, head/controller raw pose records, timestamps, frame counters and
partition topology are captured on every test tick, including reset settling.
Witnesses prevent declaring success merely because a panel was absent. Normal
frames require >95% witness visibility per view, all sensor frames valid, live
upload changes, an active XR session, and **zero** detected sensor marker pixels.

A first3000-frame run had zero leakage but only2565/3000 left-witness detections;
it is explicitly FAIL. A top-only marker was vulnerable to partial occlusion.
The diagnostic was strengthened to a dense grid over live RGB, with unchanged
acceptance thresholds. The runtime/partition implementation was not changed for
that repeat, which also FAILED witness coverage (2706/3000 in each view). Bulk captures remain outside git; only representative evidence is copied.

## Lifecycle and limits

The long diagnostic resets the canonical environment five times and recreates
preview managers12 times. Repeated raw UiContainer destruction is explicitly
unsupported by the installed NVIDIA source; final composition retains three
containers and uses show/hide while recreating feed managers. Both failed trials
are retained as evidence of this lifecycle blocker. Camera recreation is a full process restart. The pinned
Camera has no public deterministic close/hot-delete API; no private invalidation
call is used to claim in-process camera replacement. The robot/policy cameras are
never replaced by witness cameras. The standalone XR test profile is automated
only; physical launch continues to use cloudxrjs.

Logs contain upstream GLFW headless warnings and RTX CUDA-copy diagnostics around
reset. Successful image checks and exit codes do not mean those diagnostics were
absent. The diagnostic includes additional witness views and synchronous CPU image
copies, so its frame time is **not** production teleop FPS. Physical Quest latency,
controller movement and sustained headset FPS remain a human acceptance boundary.

## Results and acceptance

Final run registrations and cutover status are recorded below after the final gates.
Do not infer acceptance from this Markdown alone; use the live evidence registry.

## Migration and rollback

See [OPERATIONS.md](OPERATIONS.md). Home project launchers select the new frozen
SDK; SDK/assets/cache/CloudXR/results stay in `/data/<...>`. Every colleague uses
his/her own Linux account, project checkout and private runtime state. Shared SDK
paths are readable; no another-user HOME/IPC fallback is allowed. Cross-account
permissions and offline isolation tests do not substitute for a physical Quest test.

The old SDK/spec remains available to the same launchers through `--stack legacy`.
A failed post-cutover smoke must select this rollback; never repair the production
SDK with manual pip. Runtime rollback retains existing processor v3 and restores
old SDK selection, not historical v1 behavior. The old recursion limitation remains.

## Final combined machine result

Retained-UI production composition: PASS.3000 normal frames per camera,3155 captured
frames per camera including warmup/reset,9465 camera-frame checks total. Zero marker
pixels in all raw/native sensor captures; witness3000/3000 in each of three views;
upload changes3155 per feed. Five canonical resets,12 manager recreations, exactly
three retained SceneView roots. Process exits0. Physical Quest=false.

Raw mean diagnostic frame time: 0.0942327353206583 s, with extra witness cameras and synchronous evidence copies.

Final canonical S2 cloudxrjs no-client smoke:60/60 valid and advancing bimanual
frames, clean exit, processorv3. Session inactive without Quest; no tracking or
physical controller behavior is claimed. Measured control7.93Hz / physics31.70Hz,
end VRAM7016MiB and GPU42% in this bounded no-client run. Standalone smoke starts
one upstream session and produces60 action frames (tracking invalid), control12.24Hz.
These are diagnostics, not physical teleop performance acceptance.

## Shutdown qualification amendment

An otherwise successful smoke left an owned CloudXR daemon because Kit fast
shutdown bypassed Python cleanup after SimulationApp.close. Those initial runs
are not the final clean-shutdown evidence. Final composition stops the XR profile
through public XRCore, then calls CloudXRLauncher.stop before Kit close. Final
S1/S2/combined gates are rerun on that exact source and checked for owned leftovers.

## Scope classification

- EXPECTED REPIN: only Isaac environment SDK/source/lock pins and their evidence.
- BENIGN: per-Linux-account /data state and explicit legacy selection.
- REQUIRES NEW RUNTIME EVIDENCE: every S1 result on the final exact SDK; supplied
  by new results, never by renaming old acceptance.
- REGRESSION found and addressed: unsupported repeated SceneView destruction and
  owned runtime cleanup after Kit fast exit. Both required bounded lifecycle fixes.
- Historical integration changes published from the older home checkout: processor
  v1->v3 and prior XR/demo fixes already present in60eb260; not new REP-02 behavior.
- UNKNOWN: physical Quest tracking/latency/comfort and true second-user physical
  session. They remain S2 human acceptance; machine logs do not close them.
- No new A/B/C/D0/M0 invalidation reason found. No model, policy/data, core runtime,
  MuJoCo/evaluation ownership, or generic backend/protocol changes are introduced.

The automated standalone XR fixture still emits `XR_ERROR_VALIDATION_FAILURE:
xrWaitFrame(frameState->type == 0)` during profile disable, plus a form-factor probe
message. Canonical cloudxrjs no-client and standalone S2 smokes do not emit this
error. The fixture's successful image checks/process exit do not establish a
warning-free physical XR teardown. This remains an explicit S2 limitation; the
owned-daemon cleanup defect is separately fixed and tested.

## Registered final results before cutover

REP-01: CLOSED (287 locked installed versions; frozen re-materialization no changes).
REP-02: CLOSED (existing v3 processor code, matching config/contract/runtime evidence).
Final S1: PASS on exact0c2e2c64 SDK, full canonical contract and clean process exit.
Combined: PASS,3000 normal frames x3 cameras;3155 captured ticks per camera including
reset;9465 camera-frame checks, zero leakage; witness3000/3000 for each feed.
Canonical S2 cloudxrjs and standalone smokes: PASS, automated only.
Legacy SDK rollback through the same launcher: full S1 PASS.
Existing demo smoke: PASS, no gate acceptance implied.
Declared offline tests:82 PASS,23 skips; exact-SDK affected tests:37 PASS.
Resolved-contract validator: structurally and semantically valid; spec-reference
linter:PASS. Final RC remains not ready with its existing downstream gates unresolved.
Owned Isaac/CloudXR process inventory after final gates:empty.

New machine objects are registered under `isaac1103_*`; exact runtime paths and input
hashes are in `registered_runs.json` and each launch manifest. Old S1 evidence stays
registered and remains bound to the legacy SDK. Earlier failed combined trials are
registered as FAIL separately and are not used to accept the final integration.

GATE:S0 scoped Isaac repin and newly evidenced S1; S2 automated only/unresolved.
REUSED:NVIDIA Camera/RTX/SceneUI/CloudXR/ControllersSource/DifferentialIKController.
PINNED / VERIFIED:see exact pins and final module provenance above.
EXECUTION PROFILE / ENVIRONMENT:isaac_env and isaac_vr_record / isolated isaac;
legacy SDK retained separately. offline_tests remains core.
CONTRACT CHANGES:only Isaac facts/evidence, processor metadata reconciliation.
EVIDENCE / ARTIFACTS ADDED:registered final runtime, parity, frozen inventory,
source/lock, combined raw-frame record, tests, rollback and owned-process cleanup.
PROCESSORS / ADAPTERS:existing v3 unchanged; thin batched feed and retained UI lifetime.
TESTS:full canonical S1, combined stress, S2/demo/rollback smokes,82+37 regression tests.
HUMAN EVIDENCE:none added; physical Quest remains mandatory.
BLOCKERS / REOPEN REASONS:no remaining machine cutover blocker; physical S2 and
standalone-fixture teardown diagnostic remain disclosed. No A/B/C/D0 reopen.
NEXT GATE:physical Quest S2 acceptance with rollback available.
