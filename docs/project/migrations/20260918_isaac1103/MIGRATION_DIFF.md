# Migration diff review

Baseline home SHA:404d859cbc189e7dc661f2125d59e838ceee69fd.
Prior deployed integration SHA:60eb2605909557dbefd1e5c02db18bfa80c1217d.
Main gets one scoped migration commit; historical mass PNG/log directories and M0
pack edits from the old integration branch are deliberately excluded.

Pins: Sim6.0.1.0->6.1.0.0; Kit110.1.2->110.3.0; Lab913ac53f/16.4.0->
ae37b028(source)/0c2e2c64(lock-only materialization)/17.0.2;
RL0.16.0->0.16.3; lab_teleop0.8.0->0.9.0. IsaacTeleop1.4.98rc1,
CloudXR6.2.1, Python3.12.13, torch2.11+cu128, driver580.159.03 unchanged.

Semantic impact: S1 policy-facing model/task/observation/action/physics/cameras
unchanged and newly exercised. Presentation is partitioned; three containers are
retained following NVIDIA lifecycle guidance. REP-02 changes metadata, not v3 code.
Home's older v1 code also receives the prior already-deployed v3 integration and its
tests; this is disclosed separately from the new runtime repin. Physical S2 remains
unresolved. No robotics backend/IK/camera implementation is replaced locally.

Rollback: same home launchers with `--stack legacy`; old exact SDK/spec stays in
/data. No history restoration or pip mutation required. All live changes are
reviewable in the branch before the main checkout switches.

| File | Why |
|---|---|
| `.gitignore` | Home project entry point, /data runtime state, no generated output in git |
| `README.md` | Home project entry point, /data runtime state, no generated output in git |
| `configs/environments/isaac1103/ENVIRONMENT.yaml` | Isaac pins/config only; old SDK spec retained; processor metadata v3 |
| `configs/environments/isaac1103/materialization.json` | Isaac pins/config only; old SDK spec retained; processor metadata v3 |
| `configs/environments/isaac1103/upstream-lock.patch` | Isaac pins/config only; old SDK spec retained; processor metadata v3 |
| `configs/environments/isaac61_preview_integration.yaml` | Isaac pins/config only; old SDK spec retained; processor metadata v3 |
| `configs/experiments/robosyn_test_assets.yaml` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `configs/experiments/robosyn_vr_demo.yaml` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `configs/isaac61_s1_runtime.yaml` | Isaac pins/config only; old SDK spec retained; processor metadata v3 |
| `configs/isaac61_s2_runtime.yaml` | Isaac pins/config only; old SDK spec retained; processor metadata v3 |
| `configs/isaac_s2_runtime.yaml` | Isaac pins/config only; old SDK spec retained; processor metadata v3 |
| `configs/resolved_contract.yaml` | Scoped S0 Isaac amendment/new S1 evidence; S2 stays unresolved; accepted A/B/C/D0 preserved |
| `docs/project/GATE_S2_DEPENDENCY_RECHECK.txt` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/GATE_S2_PHYSICAL_RUN_1_FAILED.md` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/GATE_S2_PROCESSOR_TESTS.txt` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/GATE_S2_RUNTIME_EVIDENCE.txt` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/GATE_S2_UPSTREAM_AUDIT.md` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/PIPER_X_ISAAC_DEMO_SCENE_SPEC.md` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/ROBOSYN_VR_DEMO_REPORT.md` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/ROBOSYN_VR_DEMO_UPSTREAM_AUDIT.md` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/integrations/20260918_kit1103_preview/README.md` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/integrations/20260918_kit1103_preview/REPORT.md` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/integrations/20260918_kit1103_preview/UPSTREAM_AUDIT.md` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/integrations/20260918_kit1103_preview/core_tests.txt` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/integrations/20260918_kit1103_preview/evidence.json` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/integrations/20260918_kit1103_preview/evidence/control_sensor_frame4.png` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/integrations/20260918_kit1103_preview/evidence/partition_sensor_frame2999.png` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/integrations/20260918_kit1103_preview/evidence/partition_witness_frame2999.png` | Preserve existing integration/S2 historical evidence and documented demo setup |
| `docs/project/migrations/20260918_isaac1103/OPERATIONS.md` | Frozen spec/provenance, registered machine evidence, operations and rollback |
| `docs/project/migrations/20260918_isaac1103/REPORT.md` | Frozen spec/provenance, registered machine evidence, operations and rollback |
| `docs/project/migrations/20260918_isaac1103/UPSTREAM_AUDIT.md` | Frozen spec/provenance, registered machine evidence, operations and rollback |
| `docs/project/migrations/20260918_isaac1103/affected-tests.txt` | Frozen spec/provenance, registered machine evidence, operations and rollback |
| `docs/project/migrations/20260918_isaac1103/final-inventory.json` | Frozen spec/provenance, registered machine evidence, operations and rollback |
| `docs/project/migrations/20260918_isaac1103/frozen-dry-run.txt` | Frozen spec/provenance, registered machine evidence, operations and rollback |
| `docs/project/migrations/20260918_isaac1103/legacy_runtime_snapshot.json` | Frozen spec/provenance, registered machine evidence, operations and rollback |
| `docs/project/migrations/20260918_isaac1103/legacy_s2_config.yaml` | Frozen spec/provenance, registered machine evidence, operations and rollback |
| `docs/project/migrations/20260918_isaac1103/offline-tests.txt` | Frozen spec/provenance, registered machine evidence, operations and rollback |
| `docs/project/migrations/20260918_isaac1103/source_manifest.json` | Frozen spec/provenance, registered machine evidence, operations and rollback |
| `run-vr` | Home project entry point, /data runtime state, no generated output in git |
| `tests/test_gate_s1_mapping.py` | Existing integration tests and scoped pin/provenance/lifecycle regressions |
| `tests/test_isaac_demo_launch.py` | Existing integration tests and scoped pin/provenance/lifecycle regressions |
| `tests/test_isaac_s2_processor.py` | Existing integration tests and scoped pin/provenance/lifecycle regressions |
| `tests/test_isaac_s2_upstream.py` | Existing integration tests and scoped pin/provenance/lifecycle regressions |
| `tests/test_resolved_contract.py` | Existing integration tests and scoped pin/provenance/lifecycle regressions |
| `tests/test_robosyn_vr_demo_config.py` | Existing integration tests and scoped pin/provenance/lifecycle regressions |
| `tools/check_isaac_preview_partitions.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/check_isaac_s1_preview.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/isaac_demo_launch.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/isaac_preview_partitions.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/isaac_robosyn_vr_demo.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/isaac_s1_preview.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/isaac_s2_processor.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/isaac_s2_runtime.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/isaac_s2_upstream.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/launch_isaac_robosyn_vr_demo.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/launch_isaac_s1.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/launch_isaac_s2.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/materialize_isaac1103.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/quest_xr_diagnostics.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `tools/run_isaac_s1.py` | Canonical launch compatibility, retained upstream SceneUI lifecycle, partition guard or existing integration publication |
| `docs/project/migrations/20260918_isaac1103/MIGRATION_DIFF.md` | Final registered evidence / representative sample / migration review |
| `docs/project/migrations/20260918_isaac1103/evidence/control_sensor_raw.png` | Final registered evidence / representative sample / migration review |
| `docs/project/migrations/20260918_isaac1103/evidence/partition_witness.png` | Final registered evidence / representative sample / migration review |
| `docs/project/migrations/20260918_isaac1103/evidence/preview_input.png` | Final registered evidence / representative sample / migration review |
| `docs/project/migrations/20260918_isaac1103/evidence/sensor_raw.png` | Final registered evidence / representative sample / migration review |
| `docs/project/migrations/20260918_isaac1103/final_s1_parity.json` | Final registered evidence / representative sample / migration review |
| `docs/project/migrations/20260918_isaac1103/owned-process-check.json` | Final registered evidence / representative sample / migration review |
| `docs/project/migrations/20260918_isaac1103/registered_runs.json` | Final registered evidence / representative sample / migration review |
| `docs/project/migrations/20260918_isaac1103/s1_comparison.json` | Final registered evidence / representative sample / migration review |
| `docs/project/migrations/20260918_isaac1103/scope_preservation.json` | Final registered evidence / representative sample / migration review |
| `docs/project/migrations/20260918_isaac1103/spec-lint.txt` | Final registered evidence / representative sample / migration review |
| `docs/project/migrations/20260918_isaac1103/validator.txt` | Final registered evidence / representative sample / migration review |
