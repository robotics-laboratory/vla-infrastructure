# v4.3 to v5.2 Hardened Migration Report

## 1. Starting Git revision

- Branch: master
- Revision: d8c31a6d5c3141d3bb35b78aac7772774e59b9c0
- Starting worktree: clean
- Migration branch: migration/v5.2
- Old live contract: schema version 3, contract revision 7, v4.3 instruction lineage (the old validator docstring called its latest incremental behavior v4.5).

## 2. v5.2 pack SHA / manifest result

- Archive SHA-256: e46212c9188d5c9a49a7c4f176e1a7d8c0edec5b1d568d937818ba51c71251b3
- sha256sum -c MANIFEST.sha256: all 31 members OK
- Extra pack members beyond the prompt's expected list: SOURCE_REFERENCES.md, tests/test_validator_baseline.py, and four .pytest_cache files.
- SOURCE_REFERENCES.md and the baseline test were installed; cache files were not.

## 3. Migration matrix summary

The full pre-contract matrix is docs/migration/V4_3_TO_V5_2_MIGRATION_MATRIX.md.

- ALREADY IMPLEMENTED: one uv core; PIPER-X single/bimanual plugin; exact feature order/conversions; shared host XR lifecycle diagnostic and offline tests.
- MIGRATED / RE-EXPRESSED: environment, upstream pins, plugin/driver identity, structured features, gripper semantics, model/frame identity, Isaac Teleop pin, host XR sources, evidence/artifact registries.
- NEW REQUIREMENT: v5.2 temporal causality, simulator/data/evaluation/materialization/QA gates, stricter physical evidence, benchmark readiness.
- NOT YET VERIFIED: physical Quest, FK/IK/model execution, hardware/CAN/firmware, safety/watchdog, datasets, simulators, HIL, rollout.

## 4. Preserved resolved facts

- core remains uv, CPython 3.12.13, torch 2.7.1+cu126 with bundled CUDA 12.6.
- LeRobot remains 0.6.1 at 7e241bd630a3719a56157a497ce5d08f244784f1.
- piper-sdk remains 0.6.1 at 081e7c588e5b79eeaefa67a0469bcc701c81014f.
- Local plugin remains lerobot_robot_piperx 0.1.0, implemented at c01076fc32794cffcc0eb10ea6157c34aeb8de24.
- Robot types remain piperx_follower and bi_piperx_follower.
- The 14 action and 14 scalar observation features remain left-then-right J1..J6 plus gripper.
- Joint units remain degrees; gripper API units remain millimetres of SDK travel.
- The driver command path remains JointCtrl J-position plus GripperCtrl.
- PIPER-X model identity remains agx_arm_urdf at f6642ce..., with base_link and gripper_base frames.
- Isaac Teleop remains 1.3.131 in the existing optional uv group.

## 5. Preserved evidence

Every top-level old evidence item is inventoried and registered in v5.2 form: candidate matrix, PIPER-X support, bimanual support, driver/firmware behavior, model cross-check, fork-vs-plugin decision, plugin seam/package boundary, version selections, robot/gripper static semantics, and core compatibility. The live plugin and XR tests were rerun offline.

## 6. Invalidated evidence + exact reason

- v43_root_manifest_claim: invalidated. The pre-migration root MANIFEST.sha256 contained a stale SHA for the live old contract after the final pre-migration commit. The exact archived contract SHA is bb3d4dc71b0a9b2aa1a9ce402d1bf1f70e9a18e9157caa506a737f8851028fad; the archive inventory is now the integrity source.

No physical evidence was invalidated because none existed.

## 7. Needs v5.2 reconciliation

- B: physical left/right Quest identity, controls, tracking loss, reconnect/shutdown, sampling/freshness thresholds.
- C: executable offline FK/IK/reference and model-artifact checks.
- D0: exact obs_t/action_t causality regression, common training view, provenance and camera/FPS contracts.
- R0/R1/R1B: all hardware identity, firmware, motion, fail-safe and inter-arm safety evidence.
- HIL: mixed-mode, generation invalidation, continuity and physical intervention evidence.

## 8. New v5.2 requirements with no v4.3 equivalent

S0, S1, S2, D1, G1, D2a, M1, E1, E2, E3, D2b, DM, DQ, B0 and the hardened run/materialization/parity manifests have no completed old equivalent. T0 remains conditional and was not run. B1 is not mandatory because no benchmark is selected.

## 9. Gate states after migration

| Gate | State | Basis |
|---|---|---|
| M0 | accepted | Archive/inventory, pack manifest, migration matrix/report, v5.2 checks |
| E0 | accepted | Existing core lock/spec and offline checks |
| A | accepted | Preserved upstream pins, live plugin, exact structured contract, offline tests |
| B | smoke_validated | Host-only shared lifecycle works; physical human gate absent |
| C | resolved | Pinned model/frame identity; executable model checks absent |
| D0 | unresolved | Causality/common-training-view evidence absent |
| S0 | unresolved | No simulator/evaluation audit in M0 |
| S1 | unresolved | No Isaac environment |
| S2 | unresolved | No Quest-to-Isaac physical validation |
| D1 | unresolved | No Isaac human dataset |
| G1 | unresolved | No Isaac automated dataset |
| D2a | unresolved | No Isaac source parity |
| M1 | unresolved | No MuJoCo environment |
| E1 | unresolved | No Isaac evaluation run |
| E2 | unresolved | No MuJoCo evaluation run |
| E3 | unresolved | No cross-sim comparison |
| R0 | unresolved | No hardware read-only evidence |
| R1 | unresolved | No one-arm physical validation |
| R1B | unresolved | No bimanual physical safety evidence |
| R2 | unresolved | No real human dataset |
| D2b | unresolved | No real/Isaac parity |
| DM | unresolved | No materialized mixed dataset |
| DQ | unresolved | No full-read dataset QA |
| T0 | unresolved | Conditional requirement disabled |
| HIL | unresolved | No implementation/physical evidence |
| R3 | unresolved | No real policy rollout |
| B0 | unresolved | No benchmark readiness work |
| B1 | unresolved | No benchmark selected/run |

Only accepted satisfies prerequisites. A prior host-side XR implementation does not make B accepted, and old action-label prose does not make D0 accepted.

## 10. Environment / execution profile mapping

- core: resolved to the existing uv environment; offline_tests and the known host quest_xr_real command map here.
- isaac: required v5.2 record exists but dependencies, runtime and commands remain null; no install or pin was selected.
- mujoco: required v5.2 record exists but remains unresolved; no install or pin was selected.
- Future real dataset, rollout, HIL, hardware-motion, simulator, materialization, QA and benchmark commands remain null where their executable semantics are not yet established.

## 11. Files installed

The active v5.2 set includes README, AGENTS, NORMATIVE_MODEL, CAPABILITY_MATRIX, GATE_SPEC, all data/simulation/evaluation/benchmark/environment/PIPER-X/safety/HIL policies, implementation/acceptance/migration/design/source-reference docs, strict schema, gate rules, validator, reference linter and both validator regression modules.

## 12. Files archived

The exact old README/instructions/policies, old contract/schema/validator, and old manifest are under docs/archive/v4_3_pre_v5_2/; inventory.json records source path, archive path, SHA-256 and starting commit.

## 13. Runtime files deliberately left unchanged

- packages/lerobot_robot_piperx/
- tools/quest_xr_diagnostics.py
- tests/test_lerobot_robot_piperx.py
- tests/test_quest_xr_diagnostics.py
- uv.lock
- runtime dependency semantics in pyproject.toml

## 14. Dependency changes

NONE. PyYAML and jsonschema were already pinned. Python, torch, CUDA, LeRobot, piper-sdk and Isaac Teleop pins were not changed.

## 15. Test results

- uv lock --check: exit 0, 80 packages resolved.
- uv run pytest -q: 39 passed.
- uv run pytest -q tests/test_validator_negative.py: 21 passed.
- uv run ruff check .: all checks passed.
- uv run mypy: no issues in 6 source files.

Ruff mechanically formatted only newly installed v5.2 Python tooling/tests and the migrated contract test. No robotics runtime source was formatted or rewritten.

## 16. Validator result

CONTRACT STRUCTURALLY VALID, CONTRACT SEMANTICALLY VALID, FINAL RC NOT READY. --require-gate M0 exits 0. --require-final-rc correctly exits 1.

## 17. Spec linter result

SPEC REFERENCE LINT OK. Active top-level normative Markdown contains no stale status references, unknown machine IDs, or forbidden legacy placeholders. Archived v4.3 documents are outside the linter's active top-level scope.

## 18. Blockers

Mandatory unfinished blockers derived by the validator: B, C, D0, S0, S1, S2, D1, G1, D2a, M1, E1, E2, E3, R0, R1, R1B, R2, D2b, DM, DQ, HIL, R3 and B0.

These are project roadmap blockers, not M0 migration blockers.

## 19. Recommended next gates

Smallest valid next work is C (offline embodiment/model checks) and the remaining physical evidence for B, with D0 only after C is accepted. S0 and R0 may then proceed along their separate non-motion audit/read-only branches. This migration deliberately stops before all of them.
