# v4.3 to v5.2 Migration Matrix

Starting revision: `d8c31a6d5c3141d3bb35b78aac7772774e59b9c0`.

This matrix was written before changing the live resolved contract. `ALREADY IMPLEMENTED` means the live repository contains code or tests; it does not imply v5.2 gate acceptance.

| Old domain / gate | Old resolved fact | Old source / evidence | v5.2 target field(s) | Target gate | Disposition | Reason / gap |
|---|---|---|---|---|---|---|
| Core environment / E0 | One `core` environment | `pyproject.toml`, `uv.lock`, old contract, commit `ea927c1` | `environments.core`, `execution_profiles.offline_tests` | E0 | PRESERVE_AND_REFORMAT | Re-express the existing reproducible environment; do not recreate it. |
| Environment manager | `uv` | `pyproject.toml`, old `environments.core.manager_or_launcher` | `environments.core.manager` | E0 | PRESERVE | Still directly supported. |
| Python pin | CPython 3.12.13 | `.python-version`, `pyproject.toml`, `uv.lock` | `environments.core.python_version` | E0 | PRESERVE | Exact live pin. |
| uv lock/spec | `pyproject.toml` + `uv.lock`; old lock SHA recorded | live files and Git history | `artifacts.core_environment_spec`, `environments.core.spec_artifact_id` | E0 | PRESERVE_AND_REFORMAT | Register the current lock as a v5.2 artifact with its current SHA. |
| LeRobot | 0.6.1 at `7e241bd...` | old `implementation.lerobot`, upstream-audit evidence, lock | `implementation.lerobot` | A | PRESERVE_AND_REFORMAT | Version and immutable revision survive migration. |
| PyTorch / CUDA | torch 2.7.1+cu126; bundled CUDA 12.6 | `uv.lock`, old core environment record | `environments.core.torch_version`, `cuda_runtime` | E0 | PRESERVE | Package/runtime pin is live; no CUDA change is authorized. |
| `piper_sdk` | 0.6.1 at `081e7c5...` | old driver evidence, lock, package imports | `implementation.driver` | A | PRESERVE_AND_REFORMAT | Selected backend remains unchanged. |
| PIPER-X LeRobot plugin | local `lerobot_robot_piperx` 0.1.0 | commit `c01076f`, package source, tests | `implementation.robot_plugin` | A | PRESERVE_AND_REFORMAT | ALREADY IMPLEMENTED; only contract shape changes. |
| Single-arm robot type | `piperx_follower` | `PiperXFollowerConfig` registration and tests | `implementation.robot_plugin.single_arm_type` | A | PRESERVE | Literal runtime type. |
| Bimanual robot type | `bi_piperx_follower` | `BiPiperXFollowerConfig` registration and tests | `implementation.robot_plugin.bimanual_type` | A | PRESERVE | Literal runtime type. |
| Action features | 14 left-then-right scalar `.pos` values | old `robot_contract`, plugin source, tests | `robot_contract.action_features` | A | PRESERVE_AND_REFORMAT | Convert mapping to structured v5.2 feature records. |
| Observation features | same 14 scalars plus configured side-prefixed cameras | old contract, plugin source, tests | `robot_contract.observation_features` | A | PRESERVE_AND_REFORMAT | Static scalar contract is proven; camera instances remain unresolved until configured. |
| Joint order | J1..J6 per arm, left then right | old contract and tests | ordered feature records / representation | A | PRESERVE_AND_REFORMAT | Order remains literal in structured arrays. |
| Units | degrees; gripper millimetres | old contract, SDK conversion code, tests | feature `units`, `robot_contract.gripper.units` | A | PRESERVE | Static API semantics, not physical verification. |
| Gripper semantics | SDK travel relative to device-configured zero; observation absolute-value; command sign preserved | old contract, SDK evidence, plugin tests | `robot_contract.gripper` | A | PRESERVE_AND_REFORMAT | Physical range, zero and polarity remain null and unverified. |
| Driver command API | `C_PiperInterface_V2.JointCtrl` J-position path; `GripperCtrl` | old driver evidence and plugin source | `implementation.driver.command_api` | A | PRESERVE | No hardware claim is inherited. |
| PIPER-X model / URDF | `agx_arm_urdf` PIPER-X xacro | old `model.urdf` / declared limits | `model.authoritative_source` | C | PRESERVE_AND_REFORMAT | Pinned source survives; no new model execution was performed. |
| Model revision/hash | commit `f6642ce...`, xacro SHA `0ee3f52...` | old contract | model fields + `model_asset` artifact | C | PRESERVE_AND_REFORMAT | Register immutable source URI and the recorded real SHA. |
| Isaac Teleop pin | 1.3.131 | old implementation record, `pyproject.toml`, `uv.lock` | `teleop.real.runtime_dependencies.isaacteleop`; Candidate B's distinct pin is `teleop.isaac.runtime_dependencies.isaacteleop` | B / S0 | PRESERVE_AND_SCOPE | Gate B/core retains 1.3.131; Candidate B/Isaac owns its frozen 1.4.98rc1 without a false global pin. |
| Quest/CloudXR host path | one host-side lifecycle implemented | commit `d8c31a6`, `tools/quest_xr_diagnostics.py` | `teleop.real`, `execution_profiles.quest_xr_real` | B | PRESERVE_AND_REFORMAT | ALREADY IMPLEMENTED host diagnostic only; no Q1 evidence. |
| ControllersSource left/right | one source exposes both outputs | XR diagnostic source/tests and pinned API | `teleop.real.left_source`, `right_source` | B | PRESERVE_AND_REFORMAT | Static/host evidence only. |
| `quest_xr_diagnostics.py` | retained live | source file | B evidence and runtime path | B | PRESERVE | Runtime file deliberately unchanged. |
| XR host tests | two offline fake-session tests | `tests/test_quest_xr_diagnostics.py` | command-test evidence | B | PRESERVE_AND_REFORMAT | Supports host implementation, not physical human acceptance. |
| Physical Quest Q1 | not performed | old contract explicitly says physical validation not run | human-gate evidence | B | NEW_V5_2_REQUIREMENT_NO_OLD_EQUIVALENT | B must stay below accepted. |
| Dataset/action-label semantics | declarative `dataset_action` rule only | old docs/contract; no recorder/causality test | `dataset.temporal_semantics`, training view, causality evidence | D0 | NEEDS_V5_2_RECONCILIATION | No `obs_t/action_t` causality regression or materialized source exists. |
| Replay | profile mapped to core; no replay implementation/evidence | old execution profiles | future replay/QA evidence | DQ / later work | NEEDS_V5_2_RECONCILIATION | Upstream intent is not completed work. |
| HIL | requirements only; no implementation/evidence | old `hil` section and policy doc | structured `hil` contract | HIL | NEEDS_V5_2_RECONCILIATION | No concurrency or physical intervention evidence. |
| Hardware/CAN/firmware | all per-arm values unresolved | old `hardware` / `hardware_validation` | `hardware.left/right` | R0 | PRESERVE | Preserve absence as null; do not claim physical evidence. |
| Safety/watchdog | values unresolved; verification flags false | old timing/safety sections | `timing`, `safety` | R1/R1B | NEEDS_V5_2_RECONCILIATION | No physical low-level fail-safe or bimanual safety evidence. |
| Autonomous rollout | not done | no logs, manifests or authorization | `real_rollout` | R3 | NEW_V5_2_REQUIREMENT_NO_OLD_EQUIVALENT | No rollout evidence; migration must not run one. |
| Old contract manifest | root manifest did not match the live old contract after the final pre-migration commit | archived `MANIFEST.sha256` vs archived contract SHA | migration report | M0 | INVALIDATED | The stale manifest entry is not usable as integrity proof; exact archive SHA/inventory replaces it. |
| New simulator/eval/data gates | no v5.2-quality work exists | repository has no simulator runtime or datasets | S0, S1, S2, D1, G1, D2a, M1, E1, E2, E3, D2b, DM, DQ | corresponding gates | NEW_V5_2_REQUIREMENT_NO_OLD_EQUIVALENT | Remain unresolved; no migration feature work is authorized. |

## Evidence inventory boundary

The migration inventories every top-level item in the old contract's `evidence` mapping, plus the host-XR implementation/tests, the old E0/A test claims, and the stale old manifest claim. Composite old structures such as the candidate matrix are preserved as one historical evidence item because that is how the old contract stored them. No physical, dataset, simulator, HIL, replay, or rollout evidence existed to inventory.
