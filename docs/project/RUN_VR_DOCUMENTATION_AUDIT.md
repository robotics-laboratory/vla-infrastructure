# HISTORICAL PRE-CANONICAL AUDIT

Scope: baseline `6430dc1` / documentation commit `2e80d23`.
Superseded for current operation by:

- [Resolved contract](../../configs/resolved_contract.yaml)
- [Shared S2 config](../../configs/isaac61_s2_runtime.yaml)
- [Canonical VR config](../../configs/isaac61_vr_runtime.yaml)
- [Current operations](RUN_VR_OPERATIONS.md)

As of `93d3497`, the generic S2 launcher is removed, `isaac_vr` is the canonical
execution profile, and `./run-vr` is canonical. The asset lab is the only remaining
experimental RoboSyn profile. The forensic body below is preserved unchanged;
its current/supported/dual-model statements describe the pre-canonical scope only.

---

# Run-vr documentation launch-reference audit — 2026-09-21

## Scope and terminology

Audited all 396 tracked paths at master/origin/master `6430dc1a1a4366d87a3f9d1427f5e95dab7153a0` before
editing. The case-insensitive search found 318 matching lines in
112 files. Runtime/code/config references were inspected only; no runtime
or configuration semantics were changed. The dirty original working tree was
excluded by preparing documentation in an isolated worktree from this commit.

Reproduce the baseline inventory from any checkout containing the commit:

```sh
git grep -n -i -E 'run-vr|launch_isaac_s2\.py|launch_isaac_robosyn_vr_demo\.py|robosyn_vr_demo|physical Quest|Gate S2|S2 acceptance|XR launch|Quest launch' 6430dc1a1a4366d87a3f9d1427f5e95dab7153a0 --
```

- **A / CURRENT_OPERATOR_DOC:** routes current physical operation to `./run-vr`.
- **B / GENERIC_BASE_S2_DOC:** may describe `tools/launch_isaac_s2.py`, explicitly
  as base/generic S2, not the primary operator workflow. The launcher is supported.
- **C / HISTORICAL_EVIDENCE:** dated audits, reports, design snapshots and recorded
  commands/logs retain their original meaning and bytes; classification is not a
  claim that a design proposal or failed run is PASS gate evidence.
- **D / STALE_CURRENT_DOC:** a current-facing instruction or missing current
  routing that needed repair; the table records its destination classification.

**PRIMARY OPERATOR ENTRYPOINT:** `./run-vr`.
**BASE / GENERIC S2 LAUNCHER:** `tools/launch_isaac_s2.py`.
**CURRENT OPERATOR COMPOSITION:** run-vr + RoboSyn demo overlay + final Isaac61 stack.
See [the authoritative operator guide](RUN_VR_OPERATIONS.md) for the source-backed
chain, controls, config precedence and outputs. Generic/base sensitivity is toggle
normal 2x / precise 0.5x; the operator overlay selects independent `thumbstick_x`
sliders at 2x / 4x / 6x with continuous interpolation. These are selections of the
same processor, not contradictory descriptions of one active selection.

## Every matching document and retained evidence file

Paths are repository-relative. Counts are baseline matching lines, not occurrences.
For mixed documents classification is scoped to the stated section.

| Path | Lines | Classification / disposition |
|---|---:|---|
| `README.md` | 1 | STALE_CURRENT_DOC -> CURRENT_OPERATOR_DOC; primary entrypoint and guide link added. |
| `docs/GATE_SPEC.md` | 1 | CURRENT_OPERATOR_DOC; exact physical acceptance target clarified. |
| `docs/migration/V4_3_TO_V5_2_MIGRATION_MATRIX.md` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/migration/V4_3_TO_V5_2_MIGRATION_REPORT.md` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/migration/evidence/FINAL_M0_CHECKS.txt` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/migration/evidence/PRE_CONTRACT_OFFLINE_RUNTIME_TESTS.txt` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/CORE_ENVIRONMENT_OPERATIONS.md` | 1 | CURRENT_OPERATOR_DOC; Gate B/core diagnostics retained, Isaac operator guide linked. |
| `docs/project/D0_TEMPORAL_RECORDING_INTEGRATION_20260917.md` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/GATE_B_Q1_EVIDENCE.txt` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/GATE_S0_TELEOP_DEPENDENCY_AMENDMENT.md` | 3 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/GATE_S2_DEPENDENCY_RECHECK.txt` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md` | 3 | STALE_CURRENT_DOC -> CURRENT_OPERATOR_DOC; current physical procedure and provenance replaced; blank template is not evidence. |
| `docs/project/GATE_S2_PHYSICAL_RUN_1_FAILED.md` | 6 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/GATE_S2_PROCESSOR_TESTS.txt` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/GATE_S2_RUNTIME_EVIDENCE.txt` | 4 | HISTORICAL_EVIDENCE; Recorded runtime commands/results; unchanged. |
| `docs/project/GATE_S2_UPSTREAM_AUDIT.md` | 4 | HISTORICAL_EVIDENCE; Dated 2026-09-08 Candidate B/base-S2 audit, including old toggle and pins; unchanged. |
| `docs/project/ISAAC_CAMERA_PERFORMANCE_20260915.md` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/ISAAC_TELEOP_PERFORMANCE_INSTRUMENTATION_20260916.md` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/ISAAC_XR_BACKLOG_20260915.md` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/ISAAC_XR_FIXES_20260915.md` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/ISAAC_XR_PHYSICAL_FOLLOWUP_20260916.md` | 6 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/PIPER_X_ISAAC_DEMO_SCENE_SPEC.md` | 4 | HISTORICAL_EVIDENCE; Research/design snapshot dated 2026-09-10, not implemented current operator instructions; unchanged. |
| `docs/project/ROBOSYN_VR_DEMO_REPORT.md` | 6 | STALE_CURRENT_DOC -> CURRENT_OPERATOR_DOC at new opening reference only; dated sections remain HISTORICAL_EVIDENCE byte-for-byte. |
| `docs/project/ROBOSYN_VR_DEMO_UPSTREAM_AUDIT.md` | 2 | HISTORICAL_EVIDENCE; Original Candidate B experiment audit, including old shared-Y toggle; unchanged. |
| `docs/project/integrations/20260918_kit1103_preview/README.md` | 4 | HISTORICAL_EVIDENCE; Already marked historical integration checkout; old paths/commands retained; current route via maintenance guide. |
| `docs/project/integrations/20260918_kit1103_preview/REPORT.md` | 9 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/integrations/20260918_kit1103_preview/evidence.json` | 8 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/migrations/20260918_isaac1103/MIGRATION_DIFF.md` | 8 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/migrations/20260918_isaac1103/OPERATIONS.md` | 7 | STALE_CURRENT_DOC -> GENERIC_BASE_S2_DOC with explicit CURRENT_OPERATOR_DOC routing; maintenance commands scoped, migration bundle instructions marked historical. |
| `docs/project/migrations/20260918_isaac1103/REPORT.md` | 6 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/migrations/20260918_isaac1103/UPSTREAM_AUDIT.md` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/migrations/20260918_isaac1103/legacy_runtime_snapshot.json` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/migrations/20260918_isaac1103/legacy_s2_config.yaml` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/migrations/20260918_isaac1103/postcutover.json` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/migrations/20260918_isaac1103/source_manifest.json` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/performance/20260915/piper_camera_probe.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/performance/20260915/piper_camera_xr_current.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/performance/20260915/piper_camera_xr_raw_cpu_upload.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/performance/20260915/piper_camera_xr_raw_cpu_upload_render_once.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/performance/20260915/piper_camera_xr_render_once.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/performance/20260915/piper_xr_panel_layout_probe.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/performance/20260915/xr_diagnosis_source_manifest.json` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/reconciliation/20260919_contracts_kit1103/historical-provenance.json` | 50 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/reconciliation/20260919_contracts_kit1103/history/0a0ed027/configs/isaac_s2_runtime.yaml` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/reconciliation/20260919_contracts_kit1103/history/0a0ed027/docs/migration/evidence/FINAL_M0_CHECKS.txt` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/reconciliation/20260919_contracts_kit1103/history/0a0ed027/docs/project/xr_fixes/20260916/07_camera_visual_tuning/source_manifest.json.original` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/reconciliation/20260919_contracts_kit1103/history/682ee936/configs/environments/isaac_release_3_0_0.yaml` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260915/01_recenter/isaac.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260915/01_recenter/source_manifest.json` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260915/02_panels/commands.txt` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260915/02_panels/isaac.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260915/02_panels/source_manifest.json` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260915/03_preview/commands.txt` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260915/03_preview/isaac.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260915/03_preview/isaac_initial_failure.log` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260915/03_preview/runtime_isaac.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260915/03_preview/source_manifest.json` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/01_recenter_resume/source_manifest.json` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/02_camera_feedback/isaac.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/02_camera_feedback/source_manifest.json` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/03_camera_pose/commands.txt` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/03_camera_pose/isaac.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/03_camera_pose/isaac_configured.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/03_camera_pose/isaac_initial.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/03_camera_pose/source_manifest.json` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/04_per_hand_speed_slider/commands.txt` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/04_per_hand_speed_slider/isaac.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/04_per_hand_speed_slider/source_manifest.json` | 3 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/05_preview_height/commands.txt` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/05_preview_height/isaac.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/05_preview_height/layout_probe.py` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/05_preview_height/source_manifest.json` | 3 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/06_camera_mount_side/commands.txt` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/06_camera_mount_side/isaac.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/06_camera_mount_side/isaac_configured.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/06_camera_mount_side/isaac_forward_sweep.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/06_camera_mount_side/isaac_side_only.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/06_camera_mount_side/source_manifest.json` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/07_camera_visual_tuning/commands.txt` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/07_camera_visual_tuning/isaac.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/07_camera_visual_tuning/isaac_configured.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/07_camera_visual_tuning/isaac_roll_height_pitch.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/07_camera_visual_tuning/source_manifest.json` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/08_target_api/commands.txt` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/08_target_api/isaac.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260916/physical_report/stdout.log` | 1 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260917/09_cross_user_camera_recursion/commands.txt` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |
| `docs/project/xr_fixes/20260917/09_cross_user_camera_recursion/source_manifest.json` | 2 | HISTORICAL_EVIDENCE; Dated record, snapshot or evidence payload; unchanged. |

## Explicitly requested documents without baseline matches

| Path | Classification / disposition |
|---|---|
| `docs/IMPLEMENTATION_PLAN.md` | CURRENT_OPERATOR_DOC; next physical S2 target and provenance added. |
| `docs/ENVIRONMENT_POLICY.md` | CURRENT_OPERATOR_DOC; operator composition distinguished from the unchanged base execution-profile command. |
| `docs/ACCEPTANCE_CHECKLIST.md` | CURRENT_OPERATOR_DOC; exact composition and independent slider acceptance checks added. |
| `docs/project/RUN_VR_OPERATIONS.md` | New CURRENT_OPERATOR_DOC; authoritative current operator guide. |
| `docs/project/RUN_VR_DOCUMENTATION_AUDIT.md` | New documentation audit; scope and current/historical reference map. |

All tracked files under `docs/project/migrations/20260918_isaac1103/` were also
reviewed as a group: only `OPERATIONS.md` is a maintained operating instruction.
`REPORT.md`, `UPSTREAM_AUDIT.md`, `MIGRATION_DIFF.md`, source manifests, JSON/log
results, config snapshots and qualification outputs are historical evidence and
remain unchanged, including files without a search hit. The integration README
already marks its checkout historical; its original commands are retained.

## Matching non-document references

These hits do not create operator instructions. Code, tests, configs and contract
remain byte-identical. Only root integrity metadata is regenerated/extended.

| Path | Lines | Role / disposition |
|---|---:|---|
| `MANIFEST.sha256` | 1 | Integrity hashes only: regenerate with tools/generate_manifest.py. |
| `configs/environments/isaac1103/ENVIRONMENT.yaml` | 3 | Implementation/test/config reference; inspected, unchanged. |
| `configs/environments/isaac61_preview_integration.yaml` | 2 | Implementation/test/config reference; inspected, unchanged. |
| `configs/environments/isaac_release_3_0_0.yaml` | 1 | Implementation/test/config reference; inspected, unchanged. |
| `configs/experiments/robosyn_test_assets.yaml` | 2 | Implementation/test/config reference; inspected, unchanged. |
| `configs/experiments/robosyn_vr_demo.yaml` | 3 | Implementation/test/config reference; inspected, unchanged. |
| `configs/isaac61_s2_runtime.yaml` | 1 | Implementation/test/config reference; inspected, unchanged. |
| `configs/isaac_s2_runtime.yaml` | 1 | Implementation/test/config reference; inspected, unchanged. |
| `configs/manifest_paths.txt` | 1 | Integrity membership only: append authoritative RUN_VR_OPERATIONS.md explicitly. |
| `configs/resolved_contract.yaml` | 41 | Audit only: isaac_vr_record.command and teleop.isaac.resolved_implementation describe base/generic S2; no semantic change or overlay promotion. |
| `run-vr` | 1 | Implementation/test/config reference; inspected, unchanged. |
| `tests/test_gate_s1_mapping.py` | 2 | Implementation/test/config reference; inspected, unchanged. |
| `tests/test_isaac_s2_processor.py` | 1 | Implementation/test/config reference; inspected, unchanged. |
| `tests/test_isaac_s2_upstream.py` | 6 | Implementation/test/config reference; inspected, unchanged. |
| `tests/test_resolved_contract.py` | 3 | Implementation/test/config reference; inspected, unchanged. |
| `tests/test_robosyn_vr_demo_config.py` | 3 | Implementation/test/config reference; inspected, unchanged. |
| `tools/check_isaac_preview_partitions.py` | 3 | Implementation/test/config reference; inspected, unchanged. |
| `tools/isaac_robosyn_vr_demo.py` | 4 | Implementation/test/config reference; inspected, unchanged. |
| `tools/isaac_s1_preview.py` | 1 | Implementation/test/config reference; inspected, unchanged. |
| `tools/isaac_s2_processor.py` | 1 | Implementation/test/config reference; inspected, unchanged. |
| `tools/isaac_s2_runtime.py` | 1 | Implementation/test/config reference; inspected, unchanged. |
| `tools/isaac_s2_upstream.py` | 1 | Implementation/test/config reference; inspected, unchanged. |
| `tools/launch_isaac_robosyn_vr_demo.py` | 3 | Implementation/test/config reference; inspected, unchanged. |
| `tools/run_isaac_s1.py` | 4 | Implementation/test/config reference; inspected, unchanged. |

## Acceptance and preservation decision

PRIMARY OPERATOR PATH is not ALREADY ACCEPTED GATE CONFIG. The RoboSyn overlay
retains `EXPERIMENTAL_TEST_ONLY_NOT_A_GATE`; its slider retains
`DEMO_ONLY_CANDIDATE_REQUIRES_PHYSICAL_RETEST`. The next physical acceptance must
record the exact default `./run-vr` isaac61 composition: Git commit, operator
command, generated `runtime.yaml`, `launch_manifest.json`, base S2 config, RoboSyn
overlay, processor revision/source and exact environment/package pins. No Quest
run or new human/gate evidence is claimed by this documentation change.

`GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md` is a current blank procedure, not a historical
completed worksheet. Rewriting its instructions does not transform old copies into
new evidence. `ROBOSYN_VR_DEMO_REPORT.md` receives only a new current routing section;
all pre-existing dated content is preserved. All other HISTORICAL_EVIDENCE files
above remain byte-identical to the audited commit.

The authoritative `RUN_VR_OPERATIONS.md` is explicitly appended to the protected
set (91 paths) in `configs/manifest_paths.txt`; no automatic discovery is used.
`docs/MANIFEST_POLICY.md` records the addition and the root manifest is refreshed
with its canonical generator. This audit is an explanatory index, not an additional
normative contract or registered runtime evidence object.

## Normative wording changed for review

No machine contract, gate rule, runtime config, selected pin, processor behavior
or acceptance state changes. The documentation now makes these claims explicit:

1. `README.md`, `ENVIRONMENT_POLICY.md`, `IMPLEMENTATION_PLAN.md` and the current
   operator/maintenance notes identify `./run-vr` as the primary operator path;
   `launch_isaac_s2.py` retains the base/generic role. This describes the existing
   runtime selection, not a replacement of the registered execution-profile command.
2. `GATE_SPEC.md`, `IMPLEMENTATION_PLAN.md`, `ACCEPTANCE_CHECKLIST.md` and the blank
   human template specify the next physical S2 target as the exact default
   isaac61 operator composition. Previously the template launched generic S2.
3. The current template replaces toggle-specific physical checks with independent
   continuous 2x–4x–6x slider checks, including no target jump. Old toggle behavior
   remains documented only for base/historical scope.
4. The checklist/template require explicit evidence of the selected composition:
   exact Git commit and operator command, generated config, launch manifest, base
   and overlay configs, processor revision/source and environment/package pins.
   This elaborates evidence capture; the machine DAG and evidence registry are unchanged.
5. The template adds current presentation checks (R3, X, B, three previews and
   partition isolation) and replaces the old assertion that S1 scene placement
   is unchanged with checking the actual demo placement/scale. This is a procedure
   update, not a claim of new physical success or S1 requalification.
6. Current documents explicitly keep operator status separate from acceptance.
   Promotion still requires registered evidence and contract reconciliation;
   a blank template, old report or no-client smoke cannot accept the overlay.
7. `MANIFEST_POLICY.md` and the reviewed membership list extend integrity coverage
   from 90 to 91 paths by selecting the new authoritative operator guide only.

## Dual-model findings after the Blackfire / Kit1103 merge

| Location | Base/generic model | Actual default operator model / documentation repair |
|---|---|---|
| `configs/resolved_contract.yaml`: `execution_profiles.isaac_vr_record.command`, `teleop.isaac.resolved_implementation` | Registered launcher is `tools/launch_isaac_s2.py`, extending the canonical S1 scene. | `run-vr` invokes the RoboSyn launcher. Both describe real supported paths; docs now distinguish them. Contract remains unchanged; operator-overlay promotion is pending. |
| `configs/isaac61_s2_runtime.yaml`: `processor.sensitivity` versus `configs/experiments/robosyn_vr_demo.yaml`: `teleop_tuning.sensitivity` | Per-arm thumbstick-click toggle, normal 2x / precise 0.5x. | `env.experiment_runtime` causes `run_s2()` to select `experiment.sensitivity`: per-controller horizontal slider 2x–4x–6x. R3 is recenter, not the operator sensitivity toggle. |
| Generated `runtime.yaml`, `tools/run_isaac_s1.py` and `tools/isaac_robosyn_vr_demo.py` | Generated config derives from final S1 config; the ordinary S1 branch builds the canonical contract scene. | `--robosyn-vr-demo` enters the separate fixed demo composer before ordinary S1 scene construction. The overlay selects scene bases/homes/contact tuning and XR presentation; inheriting an S1 config does not prove scene equivalence. |
| `GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md` | Former physical command and checks targeted the generic toggle path and its static anchor. | Current procedure targets default `./run-vr`, overlay slider/anchor and three previews; historical completed worksheets remain scoped to their original runs. |
| `docs/project/migrations/20260918_isaac1103/OPERATIONS.md` | Former current-facing command block pointed to generic S2 and described `run-vr` only as a separate demo. | Primary operator command now precedes separately labeled base S1/S2 checks; neither demo results nor base smokes imply the other's acceptance. |
| `ROBOSYN_VR_DEMO_REPORT.md`, S2/RoboSyn upstream audits and integration/migration evidence | Dated records contain Candidate B pins, shared-Y/normal-precise controls, two-panel or older storage instructions. | New current reference routes to the guide; original report sections and historical files remain unchanged. They are not merged-master physical evidence. |
| Preview/camera semantics | Base S2 describes canonical S1 cameras; older integration records used two previews. | Default operator launch uses three previews and Scene Partitions; the scene feed is presentation-only, not a new D0 input. |

These findings explain why a future acceptance decision must identify the exact
composition. This documentation commit does not resolve acceptance by renaming a
launcher, reinterpret prior evidence, or validate the merged runtime on a headset.

## Validation scope

Validated in the isolated `docs/run-vr-primary` worktree with the existing core
CPython 3.12.13 environment at
`/data/vla-infrastructure/core-reconcile-validation/20260919T082843.713211Z/env`.
No dependencies were installed and no Isaac/Quest runtime was launched.

- `tools/lint_spec_references.py`: PASS.
- `tools/validate_resolved_contract.py configs/resolved_contract.yaml`: structurally
  and semantically valid; FINAL RC NOT READY, including unresolved S2 as expected.
- `tools/generate_manifest.py generate` / `verify` and `sha256sum -c MANIFEST.sha256`:
  PASS, 91 explicitly reviewed paths.
- `pytest -q -p no:cacheprovider tests/test_manifest.py tests/test_resolved_contract.py
  tests/test_validator_baseline.py tests/test_validator_negative.py`: 68 passed.
- Local Markdown link and extended machine-reference checks: PASS. No separate
  repository link checker exists; local links in changed/new docs were checked.
- Whole tracked-reference search and current-doc sensitivity/launcher review: PASS.
- Byte comparisons: all runtime/code/config/tests unchanged; 312 other tracked
  documentation/evidence files unchanged; all pre-existing sections of the RoboSyn
  report unchanged. `git diff --check`: PASS.

Per the review correction, commit only on the worktree branch; no master merge,
push, or remote-ref update is part of this step.
