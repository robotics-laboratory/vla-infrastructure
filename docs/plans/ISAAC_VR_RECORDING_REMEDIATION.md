# Isaac VR recording failure analysis and remediation plan

Owner: `data.collection`. Status: maintained implementation plan. This document
does not constitute D0, S2, or D1 evidence and does not change any gate state.

Reviewed source: branch `recording-fix`, commit
`1d4da7e36ce6ee868111182dfa675ea924eee663`, based on
`origin/wip/vr-recording`. Review date: 2026-09-23.

## Sources of truth

- [Normative model](../NORMATIVE_MODEL.md)
- [Data collection policy](../DATA_COLLECTION_POLICY.md)
- [Dataset materialization policy](../DATASET_MATERIALIZATION.md)
- [Simulation policy](../SIMULATION_POLICY.md)
- [Implementation plan](../IMPLEMENTATION_PLAN.md)
- [VR operations](../project/RUN_VR_OPERATIONS.md)

## Scope and conclusion

The reviewed branch is not capable of producing an admissible Isaac human-VR
dataset. It can create an NVIDIA HDF5 V2 container, but the current control path
does not preserve the action transaction, observation/action temporal pairing,
recorded-scene replay, or qualified pose source required to make that container
dataset evidence.

The immediate defect that makes every recorded action invalid is real, but
removing that condition alone would produce a more dangerous false positive: the
file would contain non-zero actions while still lacking a completed and committed
D0 transaction. Remediation therefore has to repair the whole record boundary,
not only restore one observation read.

The recommended architecture remains the state-first/offline-RGB candidate from
the repository bakeoff:

1. capture native simulation state, action, transition, and provenance online;
2. replay the immutable state snapshots without advancing physics;
3. materialize the three canonical RGB roles offline;
4. join state, action, task, and images through immutable source identities;
5. convert the qualified artifact into the canonical training dataset.

This architecture requires an explicit snapshot-backed Isaac source profile. It
must not claim that a state-only recording satisfies the existing live
three-camera source profile.

## Material reviewed

The review covered:

- the full branch history relative to the selected upstream experiment branch;
- the final record/replay implementation in `tools/isaac_vr_recording.py`,
  `tools/isaac_vr_replay.py`, `tools/isaac_s2_runtime.py`,
  `tools/isaac_vr_runtime.py`, `tools/isaac_vr_decision.py`,
  `tools/d0_causal.py`, `tools/launch_isaac_vr.py`, and
  `tools/run_isaac_s1.py`;
- the current D0/D1, simulation, materialization, acceptance, and VR operations
  documentation and selected contract fields;
- the VR architecture bakeoff and camera-latency results retained in the
  repository;
- the pinned Isaac Sim 6.1 Episode Recorder extension version 0.1.6, including
  recorder, replayer, pose backend, stage snapshot, storage, and recordable
  implementations;
- the focused recording, decision, causal-validator, and launcher tests;
- an operator-provided review of the same branch head.

No public issue tracker could be resolved from the review host and the GitHub CLI
was unavailable. External private issues are therefore not represented here.

## Blocking defects

### R1. RECORD disables the only implemented observation boundary

`tools/isaac_s2_runtime.py` initializes `observation = None` and calls
`latest_observation_capture()` only when recording is not requested. Eligibility
requires a non-null observation. In RECORD mode this makes every decision
ineligible even while the robot can continue to move through the native hold/IK
path.

Consequences:

- every HDF frame has `action_valid = 0`;
- dataset action, native command, residual, and saturation are filled with zeros;
- action source identities remain `-1`;
- a no-client smoke can appear successful despite proving no action recording.

### R2. Prepared causal transactions are never completed or committed

Eligible RUN decisions can call `SolvedControlDecision.prepare()`, but production
code has no call to `CausalTransactionValidator.complete_transition()` or
`commit()`. At the next control loop the pending validator state is unconditionally
aborted.

The recording path nevertheless writes `transition_completed = 1` whenever it is
given an eligible solution. This flag is not evidence of a successful native
transition or D0 commit.

### R3. Stored row semantics are shifted by one observation

The initial frame records `O0` with no action. After each transition the recorder
samples the current measured state `O_n`, but associates it with the previous
action using `from = n - 1` and `to = n`. The physical state Recordables in that
same HDF frame are also sampled after the transition.

This is not the canonical policy row `(O_t, A_t)`. A later converter must either
perform an undocumented shift or silently train on `O_(t+1), A_t`.

### R4. State-only recording conflicts with the selected human-VR D0 profile

At record start the runtime disables live RGB. That also prevents the existing
`ObservationCapture` from producing the three camera identities required by the
current Isaac human-VR source profile. Restoring only a 14-scalar state capture
would make action recording possible, but would not make the resulting source D0
admissible.

The architecture must explicitly choose between:

- continuing the live three-camera profile and retaining its render/latency cost;
  or
- adding a snapshot-backed offline-RGB profile whose camera observations are
  derived from an immutable recorded state and renderer manifest.

The second option is recommended because it matches the selected bakeoff
direction. D1 must remain unresolved until the new profile and its evidence are
accepted.

### R5. Recording samples the wrong pose source

`ExplicitFrameSampler` calls each upstream Recordable's `sample()` directly. It
does not use `EpisodeRecorder`'s shared pose batch or enter an explicit Fabric
backend context. The upstream default is USD.

The retained bakeoff measured a maximum USD/native pose discrepancy of
`0.402835 m`; Fabric matched the assayed native positions. The production path has
not reproduced that assay and does not record or verify its effective backend.

### R6. Replay does not open the recorded scene

`tools/isaac_vr_replay.py` verifies that `stage_snapshot.usd` exists but never
opens it. `run_vr()` first constructs the current scene, imports the current robot,
creates the current cameras, resets physics, and runs current preflight validation.
Only then does it call replay.

The Episode Replayer therefore binds recorded tracks to a newly constructed scene
from the checked-out code rather than to the recorded snapshot. Snapshot existence
is not replay provenance.

### R7. Replay can skip failures and still report success

The replayer uses the upstream default `ReplayPolicy`, whose strictness is
`best_effort`. Failed recordable binding may be logged and skipped. The project
report still publishes the HDF frame count as `frames_applied` and does not prove
that every required state track was applied.

### R8. The extension is not an explicit runtime dependency

Neither the launcher nor the pinned custom Isaac Lab XR experience explicitly
enables `isaacsim.replicator.episode_recorder`. Import success can depend on the
ambient extension graph or cached environment. NVIDIA documents explicit
`--enable` or experience dependency as the supported activation paths.

## Additional integrity and operability findings

### Incomplete source identity

The custom transition track omits information already required by the D0 decision
and validator model, including the complete observation producer identity, camera
role identities, source payload hashes, native command identity, successor
identity, transition identity, processor generation, and full XR receipt/world
transform binding. The episode identifier used by decisions is the literal
`unrecorded`, and the generated recording/run ID is not propagated through the
whole artifact chain.

### Invalid ticks are stored as zero actions

Inactive, tracking-invalid, rebased, or otherwise inadmissible loops are persisted
as ordinary state rows with zero actions. `action_valid` disambiguates them only if
every downstream consumer remembers to filter it. The canonical dataset should
contain committed transitions only; rejection reasons and gap counts belong in a
separate QA stream.

### Weak artifact finalization

- HDF SHA-256 is calculated by loading the entire file into memory.
- Manifest and result updates are not atomic.
- There is no `in_progress` versus `finalized` state.
- Buffered rows can be lost on process failure without an explicit incomplete
  artifact outcome.
- An exception can close an episode as `unclassified` rather than `failed` or
  `aborted`.
- The explicit recording directory is not fully resolved and validated for
  ownership, privacy, available space, and location outside the repository.

### Snapshot and rendering provenance are incomplete

The snapshot hash is written but not checked by replay. HDF integrity is also not
checked. There is no closed and hashed asset dependency set, and a flattened USD
does not by itself prove that referenced textures and assets are portable.

The retained bakeoff also established that the default camera Recordable does not
capture every visually significant camera attribute. Renderer settings, mutable
visual attributes, and removal of transient `/Render` and `/Replicator` graphs are
not bound into the production manifest.

### Replay isolation is incomplete

Replay checks the Isaac Lab physics-step counter but does not explicitly stop the
timeline, disable simulation/capture-on-play, or count physics callbacks. Optional
camera rendering creates and destroys all render products for every selected
frame, and camera prim paths are taken from the current environment rather than
the recording manifest.

### Launcher couples unrelated modes

- no-client RECORD smoke performs CloudXR port setup even though it cannot produce
  a tracked XR action;
- non-smoke replay still launches through the VR/XR composition;
- recording cannot enable the existing performance logger;
- dry-run tests verify command text but not extension availability or HDF
  round-trip behavior.

### Current automated tests do not exercise the failing seam

The focused suite completed with 92 passing tests. It does not start the actual
Episode Recorder extension, open a real SessionStorage session, complete a
production causal transaction, open a recorded stage in a fresh replay process,
or require a positive valid-action count.

A bounded real Kit smoke was attempted after stopping a stale same-UID CloudXR
service. Kit spent more than five minutes compiling the RTX pipeline and did not
reach recorder creation. The test was stopped and produced no HDF5. This is an
inconclusive infrastructure observation, not recorder evidence.

## Remediation design

## Controlled task register

This register is the maintained execution tracker for the recording repair. Do
not copy these statuses into historical XR backlogs or evidence reports. Update a
row in the same commit that changes its implementation status, and attach the
exact test/evidence locator before marking a task complete.

Status vocabulary:

- `not_started`: scoped and ready when dependencies allow;
- `blocked`: cannot start or finish until the named dependency is resolved;
- `in_progress`: implementation exists on the active repair branch but has not
  met its completion check;
- `done`: completion check passed at an identified source revision;
- `deferred`: intentionally outside the current repair milestone, with reason.

| ID | Task | Depends on | Status | Completion check |
|---|---|---|---|---|
| VRR-001 | Accept the snapshot-backed/offline-RGB source-profile decision and exact D0 identity model | none | `done` (`tests/test_isaac_vr_recording_contract.py`) | Selected contract/profile names every online and materialized source identity; D1 remains unresolved |
| VRR-002 | Define the admitted HDF row as one committed `(O_t, A_t, O_(t+1))` transaction | VRR-001 | `done` (`tests/test_isaac_vr_recording_contract.py`) | Schema, units, indexing, invalid-tick policy, and terminal-state handling are explicit and mutation-tested |
| VRR-010 | Explicitly enable `isaacsim.replicator.episode_recorder` and preflight its version/API | none | `done` (real Kit smoke `20260922T225844486820Z`; preflight tests) | Bounded Kit launch proves version 0.1.6 import and required public symbols without ambient extension state |
| VRR-011 | Split RECORD, REPLAY, and no-client smoke launcher dependencies | none | `done` (launcher tests; real no-client smoke `20260922T225844486820Z`) | REPLAY and no-client lifecycle smoke neither reserve CloudXR port nor initialize XR/teleop |
| VRR-012 | Validate private recording/output paths and disk budget | none | `done` (`tests/test_isaac_vr_recording.py`) | Non-absolute, repository-owned, wrong-UID, permissive, existing, and insufficient-space targets fail closed |
| VRR-020 | Implement immutable pre-action native/Fabric `O_t` capture and one-frame buffer | VRR-001, VRR-002 | `done` (real injected run `20260922T233936232911Z`; buffer invariants) | Captured source identity and state remain unchanged through decision and native application |
| VRR-021 | Complete and commit the production causal transaction after native transition | VRR-020 | `done` (real injected run `20260922T233936232911Z`; failure/epoch tests) | Production invokes prepare, complete, and commit; every failure/epoch change aborts without persistence |
| VRR-022 | Append only committed transitions and move rejection data to QA counters | VRR-021 | `done` (3 validator accepts = 3 HDF frames; zero discards in `20260922T233936232911Z`) | `N` validator commits equal `N` HDF frames; no invalid/held zero-action rows are admitted |
| VRR-023 | Propagate run/session/episode/observation/action/native/transition/successor identities | VRR-002 | `done` (strict reader validation and hashed `terminal_successor.npz` in `20260922T233936232911Z`) | A reader can verify every row without process-local state or positional inference |
| VRR-030 | Select Fabric explicitly for record-side pose sampling and forbid silent demotion | VRR-010 | `done` (shared-pose tests; real Fabric lifecycle smoke `20260922T225844486820Z`) | Manifest records requested/effective backend and a missing FSD path fails before episode start |
| VRR-031 | Qualify moving robot/object/camera pose parity against Isaac Lab native tensors | VRR-030 | `done` (5-boundary real Kit assay `20260922T235305834853Z`; 13 pure tests) | Retained moving assay passes fixed position/orientation thresholds for every required prim |
| VRR-040 | Close and hash snapshot asset dependencies | VRR-010 | `done` (asset-closure tests; real snapshot closure `20260922T225844486820Z`) | Snapshot sidecar enumerates every layer/asset with digest; unresolved dependency is fatal |
| VRR-041 | Capture complete renderer, camera, and mutable visual provenance | VRR-001, VRR-040 | `done` (fresh replay `20260922T234647933300Z`; provenance/mutation tests) | Offline renderer inputs are versioned and complete enough to reproduce every canonical camera role |
| VRR-042 | Add atomic lifecycle, periodic flush, streaming hashes, and incomplete-artifact state | VRR-022 | `done` (lifecycle/failure tests; real aborted close `20260922T225844486820Z`) | Crash/failure tests never produce a finalized artifact and do not require whole-HDF memory loading |
| VRR-050 | Start REPLAY by verifying and opening the recorded snapshot before scene binding | VRR-011, VRR-040 | `done` (fresh replay `20260922T234647933300Z`; ordering/corruption tests) | Fresh process replays with no current-scene construction and rejects hash/dependency mismatch |
| VRR-051 | Enforce strict required-track binding and recorded camera paths | VRR-050 | `done` (all 9 recorded groups prepared/applied for 3 frames in `20260922T234647933300Z`) | Missing/mismatched track or prim fails; report lists every prepared and applied group |
| VRR-052 | Prove replay has no physics/timeline advancement | VRR-050 | `done` (`physics_callbacks=0` in fresh replay `20260922T234647933300Z`; guard tests) | Timeline and capture-on-play are disabled and physics callback count remains exactly zero |
| VRR-053 | Materialize three RGB roles with persistent render products | VRR-041, VRR-051, VRR-052 | `done` (9/9 private hashed 640x480 RGB frames in `20260922T234647933300Z`) | First/middle/last and then all admitted states produce complete role sets joined by source identity |
| VRR-060 | Add deterministic temporal, epoch, failure, partial-write, and corruption unit tests | VRR-002 | `done` (marker, mutation, terminal-closure, and coverage suites) | Marker test `O_t=t`, `A_t=1000+t` and all negative mutations pass |
| VRR-061 | Add real Kit SessionStorage/SessionReader record/replay integration | VRR-010, VRR-022, VRR-051 | `done` (record `20260922T233936232911Z`; fresh replay `20260922T234647933300Z`) | Non-mock HDF round-trip passes in a fresh process with retained manifest/report |
| VRR-062 | Add deterministic injected-XR integration with distinct valid actions | VRR-021, VRR-061 | `done` (3 distinct non-zero actions survive public SessionReader validation in `20260922T233936232911Z`) | Multiple committed non-zero actions survive readback with exact source identities |
| VRR-070 | Benchmark production HDF recording against paired no-recording baseline | VRR-031, VRR-042, VRR-062 | `in_progress` (paired harness plus real state/HDF/resource hooks; supported render/XR telemetry and physical pairs pending) | Retained p50/p95/p99, drop/rejection, CPU/GPU/memory/disk metrics meet agreed budget |
| VRR-080 | Execute physical Quest recording acceptance | VRR-062, VRR-070, S2 physical prerequisite | `blocked` | Human run records useful distinct actions without causal loss and retains required evidence |
| VRR-090 | Implement LeRobot v3 materializer and full-read dataset QA | VRR-053, VRR-080 | `in_progress` (converter and full-read QA pass on the headless injected artifact; physical admissible source pending VRR-080) | All rows and video streams load, align, and pass schema/task/action/unit/outcome checks |
| VRR-100 | Add multi-episode operator lifecycle and UX | VRR-090 | `deferred` | Repeated start/stop/reset creates independently finalized qualified episodes without restart |

Execution order for the first repair milestone is:

`VRR-001 -> VRR-002 -> VRR-010/011/012 -> VRR-020/021/022/023 ->
VRR-030/031 -> VRR-040/041/042 -> VRR-050/051/052 -> VRR-060/061/062`.

VRR-070 and later tasks must not be used to compensate for a failed correctness
task. Performance tuning begins only after the recorded transaction and strict
replay are correct.

### Implementation checkpoint: 2026-09-23

The second repair block has implemented and tested the causal recorder boundary,
strict artifact/replay validation, exact Episode Recorder 0.1.6 preflight,
Fabric-only shared pose sampling, asset closure, private/atomic artifact lifecycle,
and launcher isolation. The focused offline suite passes 182 tests. A real Kit
no-client lifecycle run at
`/data/blackfire/vla-runtime/isaac-isaac61/runs/20260922T225844486820Z-record-dual_cube_to_matching_plates-hud-off`
passed scene validation and recorder capture/finalization. Its paired recording
artifact is intentionally `aborted` with zero committed frames and one QA discard;
it proves lifecycle wiring only and makes no D0, D1, action, replay, headset, or
performance claim.

### Implementation checkpoint: committed recording and offline RGB round-trip

The next repair block completed the non-physical single-episode round-trip. The
retained real Kit recording is:

`/data/blackfire/vla-runtime/isaac-isaac61/recordings/20260922T233936232911Z-record-dual_cube_to_matching_plates-hud-off`

It contains three accepted and committed causal transitions, three distinct
non-zero actions, zero discarded observations, a finalized HDF5 artifact, a
hashed full terminal successor Recordable bundle, a sanitized snapshot with no
persisted `/Render`, `/Replicator`, or `/_xr` runtime graph, closed asset
dependencies, and self-hashed renderer/camera/mutable-visual provenance. The
public Episode Recorder `SessionReader` validated all rows and tracks. Key
digests are:

- HDF5: `318878ba779db1f2155e3bdd4f2137d38ea3b0771a5d23d6319ee30afce08d44`;
- snapshot: `8b1e94cecbe419685ac8ec286f3c2e0f29221e1194e298bb674fc538879a4e92`;
- terminal successor: `b770ceb2df7ff06bc673be8a9a5ff8035a3cf48da4d5181ec58f501e95aeb1a6`;
- visual provenance: `7d1825cb48fab0f473faa960596b7edbe7ebee0ac400c63fb8cdcaa01338a557`.

Fresh-process replay evidence is retained at
`/data/blackfire/vla-runtime/isaac-isaac61/runs/20260922T234647933300Z-replay-dual_cube_to_matching_plates-hud-off/result.json`.
Strict replay prepared and applied every one of the nine recorded groups for all
three frames, opened the verified recorded snapshot rather than a current task
scene, matched visual provenance, and observed exactly zero physics callbacks.
Offline materialization produced the complete 3 frames x 3 canonical roles at
`/data/blackfire/vla-runtime/isaac-isaac61/renders/20260922T233936232911Z-offline-rgb-private`.
All nine files are 640x480 `uint8` RGB, every file hash matches the replay report,
all nine content hashes are distinct, the directory is mode 0700, and image files
are mode 0600. Persistent render products use direct
stopped-timeline Kit render updates with the Replicator reference-time gate
disabled; this avoids depending on a live Fabric simulation-time producer and
does not advance physics.

The focused recording/replay suite passes 154 tests. The full repository suite
on the lab host passes 524 tests with 26 skips; its four failures are the known
environmental contract-validator dependency on an inaccessible artifact under
`/data/ebulochkin`, not recording code failures. Documentation governance,
spec-reference lint, Ruff on every changed Python file, and the 110-file
selective manifest verification pass.

This evidence completes VRR-020 through VRR-023, VRR-041, VRR-050 through
VRR-053, and VRR-060 through VRR-062. It does not make the artifact dataset
admissible: a paired performance benchmark (VRR-070), physical Quest acceptance
(VRR-080), and downstream D1/LeRobot materialization (VRR-090) remain mandatory.

### Implementation checkpoint: moving Fabric/native pose parity

VRR-031 is qualified by a bounded five-boundary real Kit assay retained at
`/data/blackfire/vla-runtime/isaac-isaac61/runs/20260922T235305834853Z-record-dual_cube_to_matching_plates-hud-off/pose_parity.json`
(SHA-256
`bc33f9b613bffd76333e806127245d63743c34f46541b6883c31365fdda00b87`).
It compares the same Fabric-backed Episode Recorder Recordables used by the
production recorder against Isaac Lab native tensors for the physical
`base_link` and every link of both robots, both task cubes, both wrist cameras,
and the scene camera. The assay excludes non-physical articulation container
Xforms and uses the native OpenGL camera quaternion matching USD Camera axes.

All required groups moved beyond a fixed `5e-4 m` or `1e-3 rad` threshold. The
maximum Fabric/native position error was `0.0 m` and orientation error was
`2.995096332168847e-7 rad`, within the fixed `1e-5 m` and `2e-5 rad` parity
thresholds. Backend requested/effective was Fabric and Episode Recorder was
version 0.1.6. This closes moving pose parity only; it is not headset,
performance, dataset-materialization, or D1 acceptance evidence.

### Implementation checkpoint: paired recording benchmark contract

VRR-070 now has a fail-closed, simulator-independent raw JSONL and derived
report contract in `tools/isaac_vr_recording_benchmark.py`. It requires paired
baseline/recording runs with matching source, stage, visual, environment,
measurement, Git, and Quest-session identities; complementary AB/BA order; and
complete measurements for control/state/HDF append/HDF flush/render/XR latency,
process CPU/RSS, GPU utilization/VRAM, disk I/O, committed/rejected/dropped
boundaries, deadlines, and artifact bytes. Reports bind raw logs and finalized
HDF bytes by SHA-256 and self-hash all derived statistics. Missing reviewed
thresholds remain explicitly `threshold_pending`, and a headless pair is
analyzable but cannot qualify the task.

The production recorder now exposes optional nanosecond observers around the
actual Episode Recorder append and periodic flush calls. The injected no-client
path can measure both state captures, control-loop duration, append, flush,
process CPU/RSS, persistent-NVML GPU utilization/VRAM, disk I/O, causal counters,
and deadline misses without importing XR or spawning `nvidia-smi` in the loop.
Unsupported render/XR timings are explicitly `not_measured`; a raw run carrying
that marker is structurally unable to qualify or evaluate thresholds. Sixty-nine
focused tests cover the hook integration, launcher contract, pairing,
percentiles, threshold completeness, mutations, partial logs, artifact binding,
ordering, measurement availability, and the physical-Quest guard.

The real no-headset instrumentation checkpoint for commit
`e8ef945cd117d49d13323c740fdcc0215158a4f5` is retained at
`/data/blackfire/vla-runtime/isaac-isaac61/state/benchmark-no-headset-e8ef945/runs/20260923T003643236043Z-record-dual_cube_to_matching_plates-hud-off/recording-benchmark.jsonl`
(SHA-256
`3ff52bdc71eff2abbfa609c0b07f0760922af1a2460dbb70d8aecf65de442a3f`).
The strict reader accepted all three contiguous samples. Both post-warmup
samples measured the actual append and periodic-flush boundaries: append was
`0.441765 ms` and `0.231647 ms`, while flush was `7.801146 ms` and
`7.223841 ms`. Persistent NVML reported the RTX GPU metrics in both samples,
and the final counters were three committed, zero rejected, and zero dropped.
The completed log binds the 8,016,912-byte finalized HDF5 artifact at
`/data/blackfire/vla-runtime/isaac-isaac61/recordings/20260923T-benchmark-no-headset-e8ef945/session.hdf5`
by SHA-256
`7d6e98d03798fbce2a7e00c55685cb734d2d6e04a082878f20863d8bda604c57`.
Its identity records `headset_connected=false`, and render/XR remain
`not_measured`, so this checkpoint validates instrumentation only and cannot be
used as physical performance evidence.

Final branch validation at
`e675666552db905cedb85bca6b0c1c0fc9ca4646` also exercises the ordinary
non-benchmark lifecycle adapter: benchmark-only recorder options are not passed
when instrumentation is disabled. The focused lifecycle/recorder/benchmark/
launcher selection passes 73 tests. The full lab suite passes 568 tests with 26
skips; its remaining four failures all stop on `PermissionError` while reading
the pre-existing external artifact
`/data/ebulochkin/vla-runtime/evidence/20260921_vr_architecture_bakeoff/architecture-bakeoff.tar.gz`
and are not recording-code failures. Documentation governance, spec-reference
lint, Ruff, and the 110-file selective manifest verification pass.

The no-headset mode is instrumentation QA only. Supported render/CloudXR timing
telemetry, a reviewed complete threshold policy, and alternating paired physical
Quest runs remain required before VRR-070 may move to `done`.

### Implementation checkpoint: identity-bound LeRobot v3 materialization

VRR-090 now has an executable two-environment converter in
`tools/isaac_vr_lerobot_materialize.py`. The pinned Isaac/h5py phase verifies
the finalized native artifact, every complete D0 row, inter-row successor
continuity, terminal successor, asset closure, and visual provenance before it
emits a self-hashed projection bundle. The core/LeRobot 0.6.1 phase joins all
three RGB roles by exact observation and snapshot identities, checks every
camera/renderer/stage/asset/materialization/RGB digest, writes the canonical
three-video LeRobot v3 schema, and performs a full frame/stream read plus
DataLoader traversal. It uses the controlled task mapping revision
`piper_x_task_labels_v1` and retains a per-frame state/action/image join ledger.

Final post-hardening evidence uses the recording at
`/data/blackfire/vla-runtime/isaac-isaac61/recordings/20260923T000506310931Z-record-dual_cube_to_matching_plates-hud-off`
(HDF SHA-256
`81918171c7d558340170846001525a266c472bce0bb3f3b12afa94197c44f4fd`)
and strict replay report at
`/data/blackfire/vla-runtime/isaac-isaac61/runs/20260923T001113338317Z-replay-dual_cube_to_matching_plates-hud-off/result.json`
(SHA-256
`35a864fa92a648041cf8e6eba6b7983694c3ae9f3bd9e34c4ec1beb01762ab07`).
The replay applied all nine groups for all three frames, observed zero physics
callbacks, and emitted nine private, unique, identity-bound RGB files.

The resulting dataset is retained at
`/data/blackfire/vla-runtime/isaac-isaac61/materialized/20260923T000506310931Z-lerobot-v3-final`.
Its materialization manifest self-hash is
`cff79321c9ebf7064038d10f2654fa3ee282a2ebbd9148b21e5913128c0e335c`
(manifest file SHA-256
`fbb9a81464b5c26476780012fc4f638eed13a8ab8f88818f6ea8599e9f688bd3`).
All three rows and nine decoded streams have shape `3x480x640`, and two
DataLoader batches cover all rows. Fourteen focused tests cover video write/read,
shuffled non-positional joins, task substitution, incomplete/duplicate/corrupt
inputs, visual identity substitution, report/image TOCTOU, atomic failure, and
direct CLI execution across the two isolated environments.

This proves converter implementation and full-read QA, not physical-source D1
admission. The manifest correctly records `dataset_admissible=false` because the
source is a no-client injected smoke with `operator_stopped`; VRR-080 and formal
source/gate admission remain open.

### Implementation checkpoint: RECORD rendering reconciliation (validation deferred)

On `recording-fix`, the implementation based on `95f48a7` now suspends the
existing dataset RenderProducts for exactly `left_wrist`, `right_wrist`, and
`scene`, after stage snapshot, visual provenance, Recordable session and episode
initialization. [The narrow adapter](../../tools/isaac_vr_camera_rendering.py)
sets each owned Hydra texture's `updates_enabled = False`, detaches its live
annotators (RGB is exposed as `rgba` at this pin), and checks suspension once.
Camera objects, USD Camera prims, transforms/intrinsics, and CameraRecordables
remain intact. No RenderProduct is destroyed; shared renderer and XR/operator
products are untouched. No drawable observers, frame-info queries, or per-control
resource/graph checks enter the production loop.

The existing environment execution policy defaults to rendering every substep
for RUN/DIAG and startup preflight. Successful RECORD setup selects only the
final render in each `_advance` call. Ordinary four-step controls therefore use
`False, False, False, True` through public `SimulationContext.step(render=...)`.
Physics remains 120 Hz with four integrations per control; logical control,
dataset FPS and action rate remain 30 Hz. XR/operator presentation retains the
final pump. RECORD reset settling also retains a final pump; it does not clear
the execution policy or re-enable live RGB. The pinned Camera reset refreshes
pose/timestamps without recreating or enabling its render resources.

Upstream audit: Isaac Lab 17.0.2 (`ae37b028`, materialization `0c2e2c64`),
Isaac Sim 6.1 / Kit 110.3 and Replicator 1.13.36 already own physics stepping,
Camera resources, Hydra update control, annotator detach and Recordable sampling.
Installed source inspection shows that `step(render=False)` still calls the
physics manager and increments its step identity. CameraRecordable uses prim
intrinsics and the existing shared pose batch, independently of RGB readers.
The remaining gap is RECORD lifecycle composition: one isolated private
`Camera._render_data` accessor and one explicit render-policy flag. No dependency,
environment, configuration or framework change is needed. Replicator's stale
`is_attached` property is not used as proof; graph binding is inspected only once
after detach. This is a source audit, not runtime evidence.

Historical evidence belongs exclusively to
`review/vr-recording-validation@e2e08e3`: `Camera.frame == 0` did not stop Hydra
work. Suspension yielded `updates_enabled == false`, inactive RGB graph bindings
and zero dataset drawable events. Its matched review benchmark improved from
7.6263 to 12.2000 Hz (+59.97%). These are **not** performance measurements for
`recording-fix`; no review recorder architecture or commits were imported.

Current status: implementation pending validation. Runtime performance is
**NOT YET MEASURED**, the one-pump RECORD cadence is **NOT YET QUALIFIED**, and
physical Quest behavior is **NOT YET QUALIFIED**. No 30 Hz wall-time claim is made.
The committed `O_t / A_t / O_(t+1)` ordering, Fabric capture, HDF schema, terminal
successor, strict replay, asset closure, visual provenance and offline RGB /
LeRobot materialization remain unchanged. The source profile remains
`isaac_human_vr_offline_rgb_v1`. Prior completed evidence above retains its tested
scope; VRR-070 stays `in_progress`, VRR-080 stays `blocked`, and no gate is promoted.

Tests were added/updated for later use but **none were executed** because another
validation workload occupies the machine. Deferred work: focused regression and
governance checks; native RECORD/reset/strict-replay regression including camera
prim/Recordable survival and persistent suspension; matched no-client benchmark
with scoped Hydra/Kit-pump measurements; paired recorder benchmark; and physical
Quest acceptance including controls, presentation, reset/reconnect and shutdown.

### Phase 0: select and declare the source profile

The contract selects the additive Isaac snapshot/offline-RGB source profile
`isaac_human_vr_offline_rgb_v1`, with these semantics:

- the online observation source is an immutable native/Fabric simulation-state
  snapshot;
- the action source is the accepted XR decision bound to that snapshot;
- an offline materialization revision maps the snapshot to the three camera roles;
- camera identity includes snapshot ID, camera role, camera configuration hash,
  renderer/runtime identity, and materialization revision;
- the profile preserves the normative order
  `observation -> decision -> action -> native transition -> successor`;
- profile declaration alone does not resolve D1 and does not reuse the accepted
  evidence scoped to `isaac_human_vr_v4`.

Until materialization and D1 evidence pass, repaired native recording artifacts
must state `dataset_admissible = false`.

### Phase 1: implement a transaction-owned recording boundary

For each potential policy step:

1. capture and buffer `O_t` before native application;
2. acquire and validate XR identity;
3. compute `A_t` and the exact preclip/clipped native command;
4. prepare the causal transaction;
5. apply the native command;
6. advance the required four physics steps;
7. capture `O_(t+1)` and the actual native result;
8. complete the transition with native and successor identities;
9. commit the original observation/action payloads;
10. append all state, action, and provenance groups only after commit.

One admitted HDF frame must represent one completed `(O_t, A_t, O_(t+1))`
transaction. The buffered `O_t` world snapshot is written with `A_t`; invalid
loops do not consume dataset frame IDs.

### Phase 2: qualify state acquisition

- Enter the public Fabric backend context for all pose Recordable samples.
- Fail rather than silently demote when Fabric Scene Delegate is unavailable.
- Record requested and effective backend identities.
- Compare recorded articulation links, rigid bodies, roots, and camera transforms
  with Isaac Lab native tensors during a moving integration run.
- If upstream Recordables cannot meet parity, add the smallest source adapter that
  reads native tensors while retaining the upstream manifest, HDF V2, lifecycle,
  and replay machinery. Do not create a parallel recorder format.

### Phase 3: make artifacts self-contained and fail closed

- explicitly enable the recorder extension for record and replay;
- propagate immutable run, session, episode, observation, transition, native
  command, and successor IDs;
- preserve required XR receipt, epoch, payload-hash, processor, task, unit, and
  ordering metadata;
- hash the snapshot, HDF, source/config files, renderer configuration, and every
  resolved asset dependency;
- reject unresolved dependencies;
- record all camera and mutable visual attributes required for deterministic
  offline images;
- use private resolved output paths, disk-space preflight, atomic metadata files,
  streaming hashes, periodic flushes, and explicit incomplete/finalized markers;
- classify termination as success, operator stop, abort, or failure with a reason.

### Phase 4: isolate and harden replay

Replay must take a separate launcher path before current scene construction:

1. read and verify manifest and HDF root metadata;
2. verify HDF, snapshot, config, and asset hashes;
3. open the recorded snapshot before preparing recordables;
4. stop the timeline and disable simulation, capture-on-play, and automatic
   physics advancement;
5. use `ReplayPolicy(strictness="strict")`;
6. require every mandatory recorded group to bind;
7. use camera paths and parameters from the recording manifest;
8. apply state through the USD replay backend appropriate for nested transforms;
9. verify applied pose readback;
10. render all three roles with persistent render products and zero simulation
    delta time;
11. count physics callbacks and fail unless the count is zero.

Replay must not initialize teleoperation, reserve a CloudXR port, require a
headset, or reconstruct the current task scene.

### Phase 5: test the real seam

Required automated coverage:

- deterministic marker test with `O_t = t` and `A_t = 1000 + t`;
- off-by-one, duplicate, reset/reference/session epoch, and source-payload
  mutation tests;
- native-application failure and missing-successor tests;
- partial-append and crash-finalization tests;
- real Kit SessionStorage/SessionReader round-trip;
- moving Fabric/native pose parity;
- fresh-process replay from the snapshot with no current-scene dependency;
- strict binding failure, corrupted HDF, corrupted snapshot, missing asset, and
  renderer-config mismatch tests;
- deterministic injected-XR run with multiple distinct valid actions;
- separate no-client lifecycle smoke that is forbidden from claiming action or D1
  qualification;
- phase-specific startup timeouts and a warmed shader cache for integration CI.

### Phase 6: physical and performance qualification

Measure the same scene and Quest session with recording disabled and enabled.
Retain p50/p95/p99 control-loop, state sampling, HDF append/flush, render, XR, CPU,
GPU, memory, disk throughput, and rejected/dropped-boundary metrics.

The retained 18.75--18.91 Hz prototype and the bakeoff size/render rates are
planning inputs only. Acceptance requires a production HDF run with no causal
frame loss and an agreed maximum overhead relative to the paired no-recording
baseline. Physical S2 acceptance remains a prerequisite for a human-VR D1 claim.

### Phase 7: materialize and validate the training dataset

After the native artifact and replay pass:

- materialize all three RGB roles for every admitted transition;
- join by immutable snapshot/observation identity, never list position alone;
- convert state, action, task, images, episode outcome, and provenance to the
  selected LeRobot v3 schema;
- verify units, action ordering, task labels, timestamps, video lengths, and every
  episode boundary;
- perform full read and DataLoader iteration over every state row and video stream;
- retain representative visual and temporal QA before resolving D1.

Multi-episode operator UX follows successful single-episode qualification; it is
not part of the first correctness repair.

## Acceptance gates for the first repair series

The single-episode recording implementation is ready for human validation only
when all of the following are true:

- `N` committed causal transactions produce exactly `N` admitted HDF frames;
- the validator accepted count, transition count, and all required group frame
  counts are equal;
- multiple distinct non-zero dataset actions are present;
- every row independently proves `O_t`, `A_t`, native application, transition, and
  `O_(t+1)` identities;
- no invalid or held tick appears as an admitted zero action;
- reset, recenter, reference, tracking, and session changes fail closed;
- recorded poses pass fixed native parity tolerances under motion;
- replay opens the verified recorded snapshot in a fresh process;
- strict replay binds and applies every mandatory group;
- no physics callback occurs during replay;
- first, middle, and last states produce all three declared camera roles;
- hash, dependency, schema, and partial-artifact mutations all fail validation;
- measured recording overhead and disk growth meet the agreed operational budget.

Only after these conditions and the required physical Quest run should work move
to D1 dataset acceptance and multi-episode workflow improvements.
