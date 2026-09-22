# Documentation reading map

Start with [NORMATIVE_MODEL](NORMATIVE_MODEL.md). Use [INDEX.yaml](INDEX.yaml) to
select `status: current` owners for your topic; search an owner name and read its
entry, not every indexed file. Historical proof is read only when the relevant
contract evidence/artifact binding or investigation requires it.

## Sources of truth

- Rules: [NORMATIVE_MODEL](NORMATIVE_MODEL.md), topic policies below,
  [gate definitions](GATE_SPEC.md) and [machine gate rules](../configs/gate_rules.yaml).
- Selected facts, gate records and proof bindings: [resolved contract](../configs/resolved_contract.yaml).
- Documentation ownership/lifecycle: [INDEX](INDEX.yaml) and
  [DOCUMENTATION_POLICY](DOCUMENTATION_POLICY.md).
- Integrity membership: [MANIFEST_POLICY](MANIFEST_POLICY.md) and
  [reviewed paths](../configs/manifest_paths.txt).

## Select a task route

| Task / INDEX owner | Rules to read | Selected sections/configs | Current instructions |
|---|---|---|---|
| VR run/diag / `vr.operations`, `vr.acceptance` | [Simulation](SIMULATION_POLICY.md); S2 definition/rules; S1/D0 if semantics change | Contract `teleop.isaac`, `execution_profiles.isaac_vr`, `environments.isaac`, affected gates; [shared S2](../configs/isaac61_s2_runtime.yaml), [VR composition](../configs/isaac61_vr_runtime.yaml) | [VR operations](project/RUN_VR_OPERATIONS.md), [physical worksheet](project/GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md) |
| Isaac environment/S1 / `isaac.installation` | [Environment](ENVIRONMENT_POLICY.md), [simulation](SIMULATION_POLICY.md), relevant S0/S1 requirements | Contract `environments.isaac`, `simulation.isaac`, `implementation.isaac_lab`; [environment spec](../configs/environments/isaac1103/ENVIRONMENT.yaml), [S1 config](../configs/isaac61_s1_runtime.yaml) | [Isaac operations](project/migrations/20260918_isaac1103/OPERATIONS.md), [core operations](project/CORE_ENVIRONMENT_OPERATIONS.md) |
| Recording/D0/D1 / `data.collection` | [Data collection](DATA_COLLECTION_POLICY.md), [materialization](DATASET_MATERIALIZATION.md); affected D0/D1/G1/R2 requirements | Contract `dataset`, relevant `timing` and `simulation.isaac.recorder`; source-specific execution profile | [Implementation workflow](IMPLEMENTATION_PLAN.md), [Isaac VR recording remediation and task register](plans/ISAAC_VR_RECORDING_REMEDIATION.md); resolve source entrypoints from contract, never infer a recorder from an old report |
| Real hardware/safety / `hardware.verification`, `safety.timing` | [PIPER-X verification](PIPER_X_VERIFICATION.md), [timing/safety](SAFETY_TIMING.md), [HIL](HIL_EXTENSION.md) | Relevant `hardware`, `model`, `robot_contract`, `safety`, `hil`, `real_rollout` and gate sections | [Authorized physical boundary](IMPLEMENTATION_PLAN.md#physical-boundary); exact motion requires human authorization |
| Evaluation / `evaluation.policy` | [Evaluation](EVALUATION_POLICY.md), [benchmark](BENCHMARK_POLICY.md) when applicable | Contract `evaluation`, `process_architecture.eval_boundary`, `benchmark`, selected profiles; E1/E2/E3/B0/B1 as applicable | [Implementation workflow](IMPLEMENTATION_PLAN.md); gate evidence supplies historical proof, not new-run acceptance |
| Documentation/evidence / `governance.documentation` | [Documentation policy](DOCUMENTATION_POLICY.md), [manifest policy](MANIFEST_POLICY.md) | Relevant contract `artifacts`, `evidence`, `gates`; [INDEX](INDEX.yaml) | [Remaining governance work](plans/DOCUMENTATION_GOVERNANCE.md); finish checks in the policy |

The maintained Isaac operations guide currently lives inside a migration
folder; INDEX explicitly classifies that file as current. Other migration
members remain historical. Do not infer lifecycle from directory alone.
Versions, controls, gate states and test counts stay in their owning sources.
