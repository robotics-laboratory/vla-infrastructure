# Physical S2 re-acceptance: preflight audit, 2026-09-21

**No physical run was started. S2 remains unresolved.**

At entry the worktree was clean and HEAD, master, and the local origin/master
reference all equalled `6430dc1a1a4366d87a3f9d1427f5e95dab7153a0`.
No network fetch was performed; this is a local-ref observation.

The installed final stack passed the existing read-only `verify_stack('isaac61')`:
Lab lock materialization `0c2e2c64e51922d088b695d72ffe03faa5c6b95d`,
Sim 6.1.0.0, Lab 17.0.2, isaaclab_teleop 0.9.0, isaacteleop 1.4.98rc1.
The verifier checks clean pinned upstream/model checkouts, exact lock/pyproject,
installed package metadata and ground-asset hashes. It does not start Kit/XR.
CloudXR 6.2.1 is checked by `run_s2` when a future runtime starts.

## Decision before physical launch

**BLOCKED**, for two concrete reasons:

1. The requested independent **sliders** are not in canonical final-master S2.
   `configs/isaac61_s2_runtime.yaml` selects per-hand thumbstick-click **toggle**,
   translation/rotation 2.0 in normal and 0.5 in precise mode.
   Continuous 2/4/6 sliders belong to the experimental Robosyn demo. The demo
   changes presentation/scene configuration and emits `gate: NONE_EXPERIMENTAL`;
   it cannot silently replace the canonical S2 acceptance run. The old worksheet
   also tests toggles. The procedure/config scope must be reconciled before launch.
2. The added observation hooks change runtime source. HEAD remains the requested
   commit, but a run now would be **6430dc1 + instrumentation patch**, not that
   exact unmodified commit. Provenance captures this distinction and refuses an
   exact-master acceptance claim. The instrumentation needs a reviewed final
   revision, or an explicit decision on how instrumented-baseline evidence is
   scoped. Nothing was committed, pushed, or registered as physical evidence.

New hooks have offline checks, including the pinned Teleop graph/ControllerInput
seams. No new Kit application smoke or headset qualification was performed.
The old automated smoke is not proof of the added observation hooks in live Kit.

## Upstream audit

| Required audit item | Finding |
|---|---|
| CAPABILITY / GATE | Physical S2 diagnostic evidence and post-run qualification |
| PINNED UPSTREAM CANDIDATES | Final Lab 0c2e2c64, isaaclab_teleop 0.9.0, Teleop 1.4.98rc1, existing processor v3 |
| WHAT UPSTREAM ALREADY OWNS | One ControllersSource/session, transform, retargeting/smoothing, IK, camera buffers, SceneUI uploads and lifecycle |
| EXACT REMAINING GAP | Correlated source/action/target journal, human answers, per-criterion post-run evaluation and provenance binding |
| PROCESSOR / CONFIG / ADAPTER REQUIRED | Optional outputs on existing graph; passive observations at existing runtime, IK and publication boundaries; bounded checker/runner |
| ENVIRONMENT IMPACT | No installation, dependency, SDK, core/Isaac boundary, or execution-profile changes |
| WHY NO PROJECT FRAMEWORK IS NEEDED | Existing launchers, processor, performance distributions and preview invariants supply the execution path |

The checker crossed 300 LOC during this work. Re-audit: all of its code consumes
JSON evidence, computes metrics, and aggregates independent verdicts. No new
acquisition, motion, FK/IK, recorder, simulator API, RPC, or policy runtime exists.
Processor/config semantics and D0 labels are unchanged; these journals are not a
dataset and do not introduce a training action label.

## Existing inventory and applicability

| Surface | Existing evidence | Final Kit1103 applicability |
|---|---|---|
| `tools/launch_isaac_s2.py`, `launch_isaac_s1.py` | launch_manifest.json, source hashes, generated S1 config, stdout.log, runtime result and process status | Canonical entrypoint; reused |
| `tools/isaac_s2_runtime.py` | Final result: versions, processor revision, valid tracking totals, transitions, min/max scale, maximum clutch/rebase TCP translation, camera totals, wall Hz, saturation | Valid summary smoke checks; insufficient for post-run per-step diagnosis |
| `tools/isaac_s2_performance.py` | Optional performance JSONL (canonical launcher enables it): step, monotonic_ns, stage/nested durations, session/tracking/camera flags, deadline misses, percentiles | Valid host performance schema v1; excludes configured warmup, not physical acquisition timing |
| `tests/test_isaac_s2_processor.py` | Pure v3 axes/scale/clutch/gripper/tracking behavior | Reusable offline semantics; cannot substitute for physical observations |
| `tests/test_isaac_s2_upstream.py` | Pinned relative-reference clearing, mapping/layout, navigation and demo seams | Runs against installed 1.4.98rc1/0.9.0; old “Candidate B” name does not itself prove compatibility |
| `tests/test_isaac_s2_performance.py`, `test_isaac_demo_launch.py` | Distribution/logger and frozen/per-user launch behavior | Reused; no headset evidence |
| `tools/quest_xr_diagnostics.py`, its tests | Controller identity/tracking/pose and host receipt diagnostics on separate core Gate B runtime; stdout JSON | Not a checker of final S2 action/IK path; do not run a second owner to instrument S2 |
| `tools/isaac_preview_partitions.py` | Live assert_valid checks setting/root/descendant/camera partition invariants | Canonical production S2 invokes this during rendering; does not inspect headset pixels |
| `tools/check_isaac_s1_preview.py` | Desktop combined topology/pixel marker leakage, raw/cache/upload comparisons, preview-frames.jsonl and bounded representative frames | Explicit `physical_quest: false`; cannot replace headset acceptance |
| `tools/check_isaac_preview_partitions.py` | Partition qualification and positive-control/lifecycle probes | Useful topology regression, not a physical Quest runner |
| `GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md` | Manual worksheet with axes, grippers, clutch, tracking, reconnect/reset | Extended by new structured procedure; historical toggle assumptions retained, not rewritten |
| `GATE_S2_PHYSICAL_RUN_1_FAILED.md`, `GATE_S2_RUNTIME_EVIDENCE.txt`, `GATE_S2_UPSTREAM_AUDIT.md` | Immutable failure/partial history and prior source/runtime audits | Historical scope retained |
| `ISAAC_XR_*20260915/16.md`, `xr_fixes/`, `performance/` | Demo follow-ups, stdout parsing, camera probes, tuning and representative image artifacts | Evidence for their own source/SDK/demo configuration; cannot establish merged canonical physical PASS |
| `migrations/20260918_isaac1103/`, reconciliation archives, contract `isaac1103_s2_*` | Final-SDK smoke and historical source manifests | Referenced S2 smoke has zero tracked frames; combined preview has physical_quest=false |

No existing bounded physical-S2 post-run checker or structured human-answer
runner was found. Existing schemas are Python-produced result dictionaries and
performance JSONL v1; `resolved_contract.schema.json` validates the registry,
not arbitrary per-step runtime evidence.

Before these changes, source poses, raw/processed action pairs, desired/native
targets, reset epochs and first recovery windows could not be reconstructed
from final JSON. `s2_status` prints only every 30 steps. Sensitivity, navigation
and stop events appear in stdout; upstream warnings/errors also require stdout.

## Coverage matrix

“Added” means implemented and checked offline, **not observed in a physical run**.
Log PASS is limited to the stated invariant or presence of diagnostic metrics.
It never means that the human observation passed.

| Criterion | Human needed? | Log check possible? | Previously logged? | Existing checker | Gap / added coverage |
|---|---|---|---|---|---|
| 1. Left/right identity | Yes | Routing/channel consistency | Aggregate valid counts | Processor/upstream unit tests | Added same-result raw/world poses + named action channels; human identifies physical hand |
| 2. Translation axes/signs | Each hand, both signs of 3 axes | Retargeted input/output sign; approximate source-to-target gain | No action pairs | Synthetic processor tests | Added per-axis signs and both-sign coverage; physical coordinate interpretation remains human |
| 3. Rotation axes/signs | Each hand pitch/yaw/roll | Rotvec input/output, source/target quaternion deltas | No | Synthetic processor tests | Added same axes statistics; world XYZW explicitly labelled |
| 4. Translation scale | Yes, usability | Config vs processed gain; source-to-target gain | Min/max setting only | Processor tests | Added mean/p50/dispersion per hand/axis; smoothing/deadband not mistaken for constant raw-pose gain |
| 5. Rotation scale | Yes | Same for rotation | Min/max only | Processor tests | Added rotation gain statistics; not executed-TCP gain |
| 6. Clutch/rebase | Yes | Zero Cartesian intent; transition coverage | Counts and maximum TCP translation | Processor/upstream tests | Added squeeze/raw command and first-release/recovery windows; no invented physical jump threshold |
| 7. Per-hand sliders | Yes | Per-input configured mapping/range | Mode totals/min/max | Demo slider tests | **BLOCKER:** canonical S2 is toggle, not slider; no config rewritten |
| 8. Gripper polarity/range | Each hand | Linear input->aperture, endpoints, invalid-tracking hold | Config prose, no samples | Processor tests | Added trigger/mapped/native command and mapping violations; visual range still human |
| 9. Cross-talk | Yes | Per-hand algebra and zero own input during opposite-hand scenario | No correlated data | Processor isolation tests | Added isolated-window violation counts; jitter/physical motion has no declared threshold |
| 10. Valid tracking -> motion | Yes through motion scenarios | Tracked source/processed frames and exercised motion axes | Valid counts | Runtime smoke | Added per-step source and processed validity |
| 11. Tracking lost | Yes | Zero intent, held gripper; measured residual TCP motion | Transition count | Processor/upstream tests | Added last valid pose, loss boundary, commands and TCP motion; inertia is not automatically a command violation |
| 12. Reacquisition | Yes | First zero/rebased command; target/TCP delta metric | Aggregate maximum | Processor/upstream tests | Added first-target delta, rebase and last-valid pose; METRIC RECORDED, HUMAN ACCEPTANCE REQUIRED for physical jump magnitude |
| 13. Startup/session | Yes | Started session, source/command samples | started_ever, stdout | Runtime smoke | Added transitions and session epoch |
| 14. Reconnect | Yes; already in worksheet | New session epoch; subsequent rebases | Mostly stdout | Gate B/seam tests | Added session start/stop/reconnect annotations; must exercise actual Stop/Start AR |
| 15. Headset presentation | Yes, mandatory | Upload publication advances only | Not canonical per-step | Desktop preview checker | Added publication count/time/frame; physical visibility cannot be inferred |
| 16. Wrist identity/orientation | Yes, mandatory | Role/frame validity/freshness | Aggregate cameras; sampled hashes transient | Runtime/desktop preview | Added role/frame/hash to journal; pixels/orientation require human |
| 17. No headset recursion | Yes, mandatory | Partition invariants, warnings/errors | Runtime exceptions, desktop leakage result | Both preview checkers | Added topology/publication observation; no new physical pixel-leak detector claimed |
| 18. Reset | Yes | Epoch/count and post-reset motion | Camera counts/transition summary | Smoke host reset | Added reset_completed, reset epoch, both-hand motion recovery |
| 19. Shutdown | Yes | Loop teardown + process exit; SIGINT | stdout and final process result | Launcher/runtime | Added shutdown_requested/loop_closed + runner process.json; missing result never PASS |
| 20. Stale/duplicate | Physical oddities only | Retargeting IDs, dropped submissions, returned age | Mostly absent | Separate temporal/Gate B tests | Added pipeline duplicate/late counts; source acquisition duplicate/age remain null and are not claimed |
| 21. Cadence | Human comfort | Duration and start-to-start intervals | Performance JSONL | Performance tests | Reused distribution; mean/p50/p95/p99/max, host deadline misses; no physical latency acceptance threshold invented |
| 22. Runtime errors/warnings | Comments if observed | Structured error plus full stdout/stderr summary | stdout only | Exceptions | Added counts, bounded examples with log lines; errors block, unreviewed warnings insufficient |

## Added artifacts and boundaries

- `tools/isaac_s2_acceptance_log.py`: optional strict-JSON per-step/event writer,
  enabled only by `VLA_S2_ACCEPTANCE_DIR`. Exclusive journal creation preserves
  earlier runs. Nonfinite values become null, never plausible zeros.
- `tools/check_physical_s2.py`: bounded 100,000-record analysis, per-criterion
  PASS/FAIL/INSUFFICIENT, independent HUMAN/LOGS/S2 aggregation, failure windows,
  cadence/gain/recovery/diagnostics and report output. At most 20 failure windows
  per criterion and 30 diagnostic examples; complete raw journal/stdout retained.
- `tools/physical_s2_acceptance.py`: prepare/run/check around canonical launcher,
  exact refs/source/config/archive provenance, scenario markers, explicit answers,
  process shutdown, result/report and artifact hashes. `prepare` never runs XR.
- Existing graph: four extra diagnostic outputs from the **same** ControllersSource,
  bound to the returned action result even with pipelined execution. No second
  session and no action-width change. Missing/deferred action never reuses old source.
- Existing IK: log upstream desired world pose and the native values submitted
  to S1 `_apply`; measured base TCP before/after is separate from the submitted target.
- Existing preview: count completed upstream `_publish_feed` calls and associated
  camera frames; no image arrays serialized or continuous screenshot collection.

Each completed physical attempt retains:
`run_manifest.json`, `structured_runtime.jsonl`, `human_acceptance.json`,
`automated_checks.json`, `metrics.json`, `result.json`, `stdout.log`,
`environment/provenance.json`, plus original runtime result/performance/launch
files, source snapshot/patch, scenario markers, process.json, report.md and hashes.
No fake runtime journal is created by prepare; absence is explicitly insufficient.

`source_timestamp`, `source_sequence` and `source_age_ms` remain null because the
pinned ControllerInput exposes no source-owned acquisition identity/time.
`host_receipt_timestamp_ns` is recorded after `advance`; RetargetingStepInfo's
frame IDs/age are **pipeline result metadata**, never XR acquisition timestamps.
Physical D0/R2 temporal qualification remains separate and unresolved.

## Physical procedure, after the blockers are reconciled

From the core environment, prepare a **new** directory, then review preflight:

```bash
python tools/physical_s2_acceptance.py prepare /tmp/physical-s2-<unique-run-id>
```

The default expected master is 6430dc1. A later reconciled final revision must be
explicitly selected with `--expected-master <full-sha>`; the runner requires HEAD,
master and origin/master to agree and refuses tracked runtime changes.

Only after the user's next explicit physical-launch instruction, with the existing
NVIDIA/CloudXR EULA environment settings already accepted:

```bash
python tools/physical_s2_acceptance.py run /tmp/physical-s2-<unique-run-id>
```

The runner currently refuses launch on the documented blockers. There is no
automatic “diagnostic acceptance” override and no automatic config promotion.

The guided sequence is:

1. Start AR using the usual client; wait for both controllers and visible previews.
2. NEUTRAL: both controllers still for 10 seconds.
3. LEFT then RIGHT: three slow positive/negative excursions on each translation
   axis separately; other controller still. Then each roll/pitch/yaw separately.
4. Each gripper: three open/intermediate/close cycles at approximately 0/.25/.5/.75/1.
5. Each speed control independently, with scale/rotation usability checks;
   precise instructions depend on resolving the slider/toggle discrepancy.
6. Each clutch: squeeze, move controller, release, repeat three times.
7. Each tracking loss/recovery: brief controlled loss only if convenient and safe,
   otherwise UNCERTAIN. No real robot is involved or opened by this profile.
8. Existing worksheet reconnect: Stop AR / Start AR; check identities and rebase.
9. Client reset; wait for recovery, move each hand again.
10. In Quest: both wrist feeds, optical orientation, visible preview, no nested
    panels and no artifacts obstructing control.
11. Stop AR, then runner sends SIGINT to its launcher, which forwards to its owned
    runtime. Wait for process exit; answer shutdown explicitly.

Every scenario is marked immediately before execution and receives
PASS/FAIL/UNCERTAIN plus COMMENT. On scenario FAIL, the attempt is retained and
stopped. A repair requires another directory/attempt; the original failure stays.
The full checklist then asks identity for each hand, both signs of every
translation/rotation axis, translation/rotation scale, clutch/rebase, independent
speed, gripper polarity and range, cross-talk, tracking loss/reacquisition,
startup/reconnect/reset, wrist cameras, preview visibility/recursion and shutdown.
Answers are never supplied from logs. EOF/interruption leaves items uncertain.

## Acceptance and contract

No score. All mandatory human items must be PASS, every mandatory log criterion
must be PASS for its explicitly stated invariant, exact runtime provenance must
match, and contradictions must be absent. Human FAIL or log FAIL blocks the run;
missing/uncertain evidence is incomplete. A complete physical run is required
before registering new human_gate/log artifacts and changing the S2 gate.

Warnings currently remain INSUFFICIENT pending explicit evidence review; the
checker does not infer a vendor-warning allowlist. Numeric physical recovery,
comfort or latency thresholds are not invented to produce PASS.

Contract, processor v3, final configs and historical acceptance/failure artifacts
were not changed. The next gate remains **physical S2 re-acceptance**, not D1.
