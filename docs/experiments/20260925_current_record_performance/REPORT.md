# Current live RECORD performance, 2026-09-25

## Scope and verdict

This is a no-client performance experiment on base
`ad4114c8b7a5fb670fe9bd41405922380c6b9152`, branch
`experiment/vr-current-record-performance`. The tested scene is
`dual_cube_to_matching_plates`. No production rate, physics, admission,
clutch, HDF policy, materializer, or controller algorithm was changed.
The small opt-in audit hooks measure existing live recording and lifecycle
APIs. The source identity, exact launcher commands, per-run host readings,
summaries, output hashes, and raw-log digests are in [results.json](results.json).
Raw JSONL, stdout, host samples, manifests, and HDF files remain under
`/data/ebulochkin/p25/`; no bulk traces are committed.

The current **injected** RECORD path with XR ON/no client averaged 26.54 and
26.58 ms start-to-start in two fresh processes (37.68 and 37.63 wall Hz).
It therefore exceeds 30 Hz on average, but misses the 33.333 ms deadline
on 1.07% and 0.93% of intervals. Most misses follow the normal 64-row HDF
flush. Six true tracking-invalid gaps each incurred a roughly 213 ms wall
stall through the first recovered commit. Clutch remained in one technical
episode and did not create a boundary.

Two requested baselines cannot be stated as a clean matched comparison.
The supported S2 RUN path constructs `IsaacTeleopDevice`; XR OFF RUN failed
before its first control without `NV_CXR_RUNTIME_DIR`. A1 RUN with XR ON
renders every physics substep, while current RECORD switches to rendering
only the final substep. Their observed wall-rate difference **does not
measure recorder overhead**. No artificial XR-off RUN or altered render
cadence was introduced. Thus acceptance item 1 (pure matched RUN versus
RECORD overhead) remains unresolved; item 2 is met within RECORD B0/B1.

## Upstream and implementation audit

| Requirement | Pinned owner reused | Remaining gap and local code |
| --- | --- | --- |
| Current control/scene | Isaac Sim 6.1 / Isaac Lab `0c2e2c64`, S2 runtime | Native-target audit input at the existing loop boundary; no new simulator backend |
| Live recording | Isaac episode recorder, `RecordingSession`, V2/V3 causal commit, `SessionReader` | Timed existing append, flush, seal, terminal successor, hash, and publication calls |
| XR and lifecycle | IsaacTeleop 1.4.98rc1, CloudXR 6.2.1, `RecordingLifecycle` | Controlled no-client device context, six real session splits, button-edge lifecycle cycles |
| Host observation | Existing performance logger, NVML and `nvidia-smi` | Start-to-start interval, p99.9, sparse host samples; no added CUDA synchronization |

The existing injected RECORD seam did not provide a RUN native-target loop,
so the audit adds a narrow loop in the same injected-input module. Existing
`RecordingSession` and `RecordingLifecycle` still own all episode and demo
transitions. The recording-smoke module grew past the 300-line re-audit
threshold because it contains C/D/E orchestration; inspection found no
duplicate writer, lifecycle, IK, processor, XR protocol, or generic robotics
abstraction. The core and Isaac environments remain isolated.

## Runtime and conditions

Host: `lab-desktop-1`, Intel Core i7-13700K, 31 GiB RAM, NVIDIA GeForce
RTX 4090 (24 GiB), driver 580.159.03, Linux 6.8.0-124-generic. CPU governor
was `powersave`; affinity, governor, renderer quality, flush policy, and
physics settings were not modified. Kit reports 110.3.0; Isaac Sim 6.1.0.0,
Isaac Lab release/3.0.0 at `0c2e2c64`, isaaclab-teleop 0.9.0,
IsaacTeleop 1.4.98rc1, and CloudXR runtime 6.2.1. All cohorts used the
same scene, 120 Hz physics (`1/120 s`), four substeps per control,
33.333 ms logical control time, solver 8 position/2 velocity iterations,
and the configured three 640×480 cameras. The base config has render
interval one physics step; effective RUN called render on all four
substeps while RECORD called it only on the final substep. RECORD used
the ordinary 64-frame HDF flush policy; inspected V3 row datasets used
1024-row chunks without compression. V2 offline-RGB source and
V3 committed rows were not replaced. B0/B1/C used 3101 controls with
100 warmup controls and 3000 measured start-to-start intervals. D used
1204 committed controls, six gaps and 100 warmup controls. E had four
six-row lifecycle cycles and is excluded from steady comparisons.

Every cohort had a fresh Isaac process and private state root. The first
XR RECORD versus XR OFF RECORD order was B1→B0; the later repeat was
B0→B1. CPU package temperatures and frequencies, GPU samples, process
RSS, disk free, output bytes, exact runtime config, and all file hashes are
stored per run in `results.json`. CPU load differed between starts, so the
repeat is used to check robustness, not to infer a universal XR cost.
At 3000 intervals p99.9 is informed by only about three upper-tail samples.
The 10-second GPU samples cover startup/shutdown as well as controls;
their means are not control-only utilization estimates.

### What XR ON/no client means here

The XR ON launch uses `--xr-smoke --no-client-audit`, child `--xr`,
`--viz kit`, the `isaaclab.python.xr.openxr.kit` experience, enabled XR
scene-view extensions and Kit XR bridge, and the `cloudxrjs` CloudXR profile.
Kit logged `XR enabled changed to: True`; OpenXR instance creation succeeded.
IsaacTeleop logged that OpenXR handles and session creation were deferred
waiting for an XR session. `session_running_at_end=false` and
`xr_input_available_at_end=false`. No established client or stream was
observed. A Kit warning states that the XR camera had not appeared after
300 frames. The device input pump ran 3101 times in A1/B1/C; this does not
imply XR callbacks from a client. Submitted/returned physical frame counters,
presentation timestamps, display state beyond that warning, and motion-to-
photon timing were unavailable without a session. XR OFF B0 uses
`record --smoke`, no child `--xr`, no CloudXR initialization, no teleop
device, and no XR presentation experience; Kit still renders the ordinary
simulation cameras.

This is XR stack overhead without a physical client. It is not a Quest
workload, physical XR verification, human acceptance, or a streaming result.

### Input-path identity and caveat

| Cohort | Processor | Bimanual IK | XR receipt | Quest | Writer | Input |
| --- | --- | --- | --- | --- | --- | --- |
| A0 | unavailable | unavailable | unavailable | no | no | RUN could not start XR OFF |
| A1 | no | no | none | no | no | Fixed native target sweep; real device pump, no client receipt |
| B0/B0 repeat | no | no | synthetic | no | yes | Same fixed native target sweep |
| B1/B1 repeat | no | no | synthetic | no | yes | Same fixed native target sweep; real device pump |
| C | no | no | synthetic | no | yes | Sweep plus held left-arm targets on clutch rows |
| D | no | no | synthetic | no | yes | Sweep with six tracking-invalid rejections |
| E | no | no | synthetic | no | yes | Short controlled button-edge lifecycle cycles |

A1, B0, and B1 and their repeats have the same SHA-256 of the native
target sequence, `e84980063820927b1e02b510d1784085efc2e144231ce7655a3f1ae001659802`.
The injected receipt uses the existing test architecture; it does not
exercise the production processor, `_BimanualDifferentialIk.solve`, its
CPU↔GPU path, real controller receipt, or XR validation of tracked hands.
Those costs remain a physical Quest matched-run question.

## Start-to-start wall results

All durations are milliseconds. Misses are intervals greater than 33.333 ms.
`RTF = effective wall Hz / 30`; logical simulation time per control is
4 × 1/120 s = 33.333 ms. `D` includes its six gap intervals. `E` includes
Start/Stop/reset boundaries and is intentionally not a steady estimate.

| Cohort | XR | RECORD | Gaps | n | mean | p50 | p90 | p95 | p99 | p99.9 | max | Hz | miss % | RTF |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A0 | OFF | no | 0 | — | — | — | — | — | — | — | — | — | — | — |
| A1 | ON/no client | no | 0 | 3000 | 85.94 | 85.40 | 89.81 | 91.32 | 94.89 | 101.09 | 124.43 | 11.64 | 100.00 | 0.388 |
| B0 | OFF | yes | 0 | 3000 | 23.76 | 23.43 | 24.69 | 25.74 | 30.60 | 34.72 | 36.64 | 42.09 | 0.20 | 1.403 |
| B1 | ON/no client | yes | 0 | 3000 | 26.54 | 25.93 | 28.44 | 29.27 | 33.38 | 39.12 | 43.97 | 37.68 | 1.07 | 1.256 |
| C | ON/no client | yes | 0 | 3000 | 26.65 | 25.99 | 28.48 | 29.26 | 34.18 | 39.57 | 84.74 | 37.53 | 1.37 | 1.251 |
| D | ON/no client | yes | 6 | 1103 | 27.61 | 25.98 | 28.53 | 29.39 | 37.28 | 211.75 | 217.39 | 36.23 | 1.63 | 1.208 |
| E | ON/no client | yes | lifecycle | 23 | 112.44 | 26.82 | 512.19 | 581.62 | 589.15 | 590.79 | 590.97 | 8.89 | 34.78 | 0.296 |
| B0 repeat | OFF | yes | 0 | 3000 | 23.81 | 23.50 | 24.72 | 25.88 | 30.52 | 31.51 | 37.87 | 42.00 | 0.10 | 1.400 |
| B1 repeat | ON/no client | yes | 0 | 3000 | 26.58 | 25.95 | 28.47 | 29.38 | 33.29 | 38.39 | 43.95 | 37.63 | 0.93 | 1.254 |

The XR ON/no-client RECORD minus XR OFF RECORD mean interval was 2.781 ms
in the first pair and 2.766 ms in the reversed pair. The first B1 had
`simulation_advance` 22.49 ms versus B0 20.11 ms; device pump was only
0.036 ms. XR/Kit rendering and related host activity are plausible
contributors; the measurement cannot isolate individual XR internals.
By contrast A1's `simulation_advance` was 85.14 ms and median interval
85.40 ms. That distribution is **stable slow** under its four-render
RUN cadence, not irregular desynchronization. Current B1 RECORD is
**tail dominated relative to the 30 Hz deadline**: non-flush intervals
average 26.41 ms, with periodic flush intervals and a few other outliers.

The live recorder's B1 stage means were: teleop/input advance 0.036 ms,
native decision/apply 0.815 ms, observation promotion 0.001 ms,
simulation advance 22.487 ms, successor capture 1.420 ms, causal commit
and recording 1.729 ms, runtime bookkeeping 0.006 ms. Within the latter,
HDF append averaged 0.250 ms and flush amortized to 0.131 ms/control.
Within simulation, `sim_step` was 21.091 ms. These nested scopes must
not be added to their parents. RUN A1 observed capture 0.190 ms,
native apply 0.530 ms, and simulation 85.142 ms; no processor or IK stage
ran in any cohort.

The HDF flush happens every 64 committed rows. The next wall interval
after a flush was 34.96 ms versus 26.41 ms otherwise in B1, and
34.30 versus 26.45 ms in B1 repeat. It accounted for 29/32 and 20/28
30 Hz misses, respectively. Across XR OFF repeats it accounted for
7/9 misses. This is temporal association with the previous control's
measured flush scope, not an independent randomized flush experiment.
Normal body timers alone would miss the boundary-to-next-start delay.

## Clutch, true gaps, and lifecycle

C contained 3040 motion, 11 `clutch_engaged`, 40 `clutch_held`, and 10
`clutch_release_rebased` committed left-arm rows, confirmed directly in
the V3 HDF dataset. The last engage falls at the end of the bounded
sequence. The left native target is held on clutch rows while the right
target still advances. It remained one technical episode with zero
discards and no technical close/open event. Clutch-step wall mean was
26.75 ms (61 rows), compared with 26.64 ms for other steps; the largest
84.74 ms outlier occurred on a non-clutch step. At this sample size,
there is no demonstrated clutch-specific boundary or material overhead.
All 61 clutch rows also had a changed right-arm dataset action compared
with the preceding row, so the other arm continued through native
actuation while the left arm was held.

D injected six `tracking_invalid` discarded observations at preselected
ticks after the last committed ticks 172, 345, 518, 691, 864, 1037.
The next committed ticks were 174, 347, 520, 693, 866, 1039. The seven
technical episodes each contain 172 committed transitions. These gaps
used `RecordingSession.end_episode/start_episode`, not environment reset.
`results.json` retains, for each gap, the last committed row's body and
start-to-start interval, each end/open scope, the first recovered row's
body and interval, and the complete gap-to-first-commit wall stall.

| Boundary scope | samples | mean ms | p95 ms | max ms |
| --- | ---: | ---: | ---: | ---: |
| D technical episode end (inclusive seal) | 6 | 87.48 | 91.96 | 93.57 |
| D HDF close | 7 | 9.82 | 10.88 | 11.34 |
| D terminal successor write | 7 | 8.94 | 9.16 | 9.18 |
| D terminal successor verification | 7 | 1.96 | 2.53 | 2.79 |
| D HDF SHA-256 | 7 | 4.28 | 4.69 | 4.81 |
| D manifest publication | 7 | 53.96 | 57.64 | 59.03 |
| D result publication | 7 | 5.26 | 5.43 | 5.44 |
| D next technical episode open | 6 | 72.35 | 74.22 | 74.70 |
| D gap to first recovered commit | 6 | 213.35 | 220.00 | 222.42 |
| E Start to recording-ready | 4 | 379.99 | 409.48 | 415.88 |
| E Stop/seal (inclusive) | 4 | 86.88 | 90.92 | 91.58 |
| E Save selection | 3 | <0.01 | <0.01 | <0.01 |
| E classification publication | 3 | 2.89 | 3.14 | 3.16 |
| E Discard publication | 1 | 0.15 | 0.15 | 0.15 |
| E state-only Reset | 4 | 96.93 | 99.00 | 99.00 |
| E next Start button after reset | 3 | 0.02 | 0.03 | 0.03 |

`technical_episode_end` includes terminal write/verification, HDF close,
hashing, and publications; `gap_to_first_recovered_commit` includes end,
inadmissible physics step, open, and first recovered control. Their
subscopes overlap and are **not additive**. `E` used success, failure,
incomplete and Discard cycles; all returned to WAITING. Its `Start`
timing includes the real new recording/session preparation. Save
selection is a state edge; classification publication is separately
timed. Reset measured `env.reset` plus device reset without creating a
technical tracking gap.

## Host resources and correctness

| Run | peak process RSS GiB | max sampled VRAM MiB | max sampled GPU util % | CPU package °C before→after | HDF MiB |
| --- | ---: | ---: | ---: | --- | ---: |
| A1 | 15.24 | 6620 | 67 | 49→58 | 0 |
| B0 / repeat | 15.21 / 15.10 | 5239 / 5192 | 59 / 51 | 53→51 / 40→53 | 31.8 each |
| B1 / repeat | 15.99 / 15.82 | 6446 / 6446 | 44 / 45 | 57→50 / 46→49 | 31.8 each |
| C | 15.68 | 6426 | 43 | 46→58 | 31.8 |
| D | 15.69 | 6426 | 44 | 47→52 | 57.1 total |
| E | 16.07 | 6426 | 4 | 49→53 | 32.6 total |

Whole-process CPU busy fraction across all cores was 19–24%; this and
10-second GPU utilization include Kit startup and shutdown and cannot
attribute per-control work. Before/after CPU frequencies, load, GPU
temperature/clock and disk free are in `results.json`. Disk free fell
across successive fresh state roots, with 20.0 GB still free after the
final B1 repeat; that delta includes Kit cache and logs, not just HDF.

Every RECORD cohort passed strict artifact verification and exact
`SessionReader` readback. The manifests identify
`isaac_human_vr_offline_rgb_v2` and
`piper_x_committed_transition_v3`, finalized artifacts, verified terminal
successor digest, and exact committed counts. B0/B1/C each have 3101
rows; D has seven × 172; E has four × 6. C has no discarded rows;
D has exactly six known discards, one per gap. No missing committed
transition or unexpected discarded row was observed. Offline replay,
RGB materialization, LeRobot encoding, and QA were excluded from control
Hz. The earlier three-row feasibility smoke was not used as performance
baseline because source changed during that setup.

## Reproduction, failed attempts, and limits

`results.json` has each exact top-level invocation and child command,
source/config hashes, per-cohort flags, raw-file digests, output hashes,
system snapshots, valid-run registry, and invalid-attempt registry. To
rerun an XR ON invocation, use the recorded command with
`OMNI_KIT_ACCEPT_EULA=Y ISAACLAB_CXR_ACCEPT_EULA=1`; XR OFF uses
`OMNI_KIT_ACCEPT_EULA=Y`. Each command specifies its own private
`--state-root`, `--run-dir`, and `--recordings-root`, the fixed input count,
100-step warmup, and 500-step logging window. The exact command is
retained rather than replacing supported options with a hypothetical CLI.

A0 failed before control because the S2 RUN constructor requires the
OpenXR runtime even when `--xr` was absent. Initial A1 attempts failed
before control due to an omitted CloudXR EULA variable and an overlong
Unix IPC path; short `/data/ebulochkin/p25/` roots resolved both. The
first B0 attempt was rejected by an overly broad new CLI guard and was
rerun after narrowing that guard for supported XR OFF RECORD smoke.
All are INVALID numerical runs and remain in the registry. The narrow
guard correction changed `tools/run_isaac_s1.py` between initial A1/B1
and B0; `run_manifest.json` records each source hash. The correction
only affects the pre-start audit CLI validation and does not alter
the A1/B1 control loop. No claims are made for a common committed
revision until a later replay of the final commit.

Historical performance reports are context only: admission, technical
episode lifecycle, static session reuse, clutch semantics, source
schemas, and boundaries have changed, so no percent improvement is
inferred from old values. No S2/D1 gate state was changed or accepted;
this experiment is not registered as physical qualification evidence.

## Checks and execution limits

`compileall` and `git diff --check` passed for the edited source/tests.
Direct CPU assertions passed for start-to-start warmup exclusion, p99.9,
boundary retention including terminal verification, injected causal rows,
clutch held-target semantics, and accepted/rejected launcher options.
The summarizer read the completed B1 repeat JSONL and reported wall Hz,
p99.9 and miss fraction. All seven RECORD runs passed strict HDF readback.
The root MANIFEST verifier passed after canonical refresh.

The repository's declared `.venv` lacked PyYAML and pytest, so its
documentation/contract checks and pytest suite could not run there
without installing dependencies. No dependency was installed. The same
read-only docs lint with trusted base, spec-reference lint, and contract
validator passed under the pinned Isaac production Python, which has
PyYAML; this is a fallback check, not a claim that the declared core
test environment is healthy. Docs lint also reports pre-existing
historical integrity debt outside this bundle. Physical verification
and Quest acceptance were not attempted.

## Decision and later physical Quest run

The next **measurement** should obtain a genuine matched RUN/RECORD
render-cadence baseline under separately approved production-equivalent
conditions; the present production RUN/RECORD defaults cannot supply it.
For the measured injected RECORD path, do not lower control rate on this
evidence: the no-flush majority is ~26.4 ms and the misses are mostly
periodic HDF flush tails. The justified optimization workstream is a
separate F11 tail study of flush timing and technical episode
publication/open costs, including whether those boundaries block the
control loop. Production flush/chunk settings and async finalization
remain unchanged in this branch. Mean simulation/renderer work is still
the largest stage; further F03–F06 profiling should be separate and
include true IK before changing dynamics. A 120 Hz / five-substep =
24 Hz control variant would require its own dynamics qualification and
was not implemented here. Wall RTF below one in A1 is time warp relative
to logical simulation time, not proof of a broken causal modality chain.

For a later physical Quest run: use the same scene/config and logger,
connect and record a real client/session ID, verify established stream
and presentation callbacks/counters, run matching RUN and RECORD
controller-pose sequences with processor, real XR receipt and
`_BimanualDifferentialIk.solve` enabled, collect at least 3000 measured
controls after 100 warmup (prefer 9000), reverse run order, then exercise
clutch, sparse true tracking loss, and explicit lifecycle. Keep each
cohort in a fresh process; retain HDF readback, host samples, frame
timings and human physical authorization/evidence separately. This plan
is not physical acceptance.
