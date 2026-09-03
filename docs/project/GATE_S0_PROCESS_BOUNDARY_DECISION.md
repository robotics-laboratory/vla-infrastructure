# Gate S0 process-boundary architecture decision

Decision date: 2026-09-01

Live repository baseline: `8767dd83c60b9f5929988ff7e5252771bb34f811`

Decision status: **ACCEPTED FOR GATE S0**

```text
PROCESS BOUNDARY JUSTIFIED: YES
SAME-PROCESS E1 REQUIRED: NO
TRANSPORT SELECTED: NO
RPC IMPLEMENTATION SELECTED: NO
```

This is a focused follow-up to the completed Gate S0 audit and remediation.
It changes the architecture decision that made the audited dependency conflict
an S0 blocker. It does not invalidate, replace, or rewrite the earlier evidence,
and it does not implement S1, M1, E1, CONTROL, or any transport.

## 1. Preserved evidence chain

The evidence chain is intentionally chronological:

```text
docs/project/GATE_S0_UPSTREAM_AUDIT.md
-> resolver incompatibility discovered
-> docs/project/GATE_S0_ISAAC_COMPATIBILITY_REMEDIATION.md
-> no released same-process Isaac + LeRobot path
-> semantic same-process analysis
-> this narrow process-boundary architecture decision
```

The remediation verdict remains true for its question: LeRobot 0.6.1 and the
selected released Isaac stack cannot share one normally resolved Python
environment. This decision does not claim otherwise. It establishes that the
E1 semantics do not require that package co-location.

## 2. Decision drivers

The shared contract is D0 policy/data semantics, not a shared interpreter and
not arbitrary native simulator dictionaries. The core evaluator can retain the
normal LeRobot checkpoint, processor, inference, aggregation, and manifest
path while an isolated Isaac process retains the native environment lifecycle.

E1 needs a strict episodic step boundary, but not shared memory or shared
package imports. A synchronous, one-step-in-flight protocol preserves:

```text
obs_t
-> LeRobot decision and postprocessing
-> canonical_D0_action_t
-> Isaac native mapping and actuation
-> transition/outcome_t
-> canonical_D0_obs_t+1
```

The Isaac endpoint reports reward, success, termination, and truncation for
the transition. The core evaluator continues to own seed-set selection and
`lerobot-eval` aggregation. This is a narrow environment boundary, not a
replacement policy runtime or evaluation implementation.

## 3. Selected process topology

### CORE / LeRobot process

- LeRobot 0.6.1 checkpoint loading;
- checkpoint policy preprocessing and postprocessing;
- policy inference;
- `lerobot-eval` aggregation and result generation;
- evaluation manifest ownership;
- seed-set selection.

### ISAAC process

- Isaac application and vendor runtime;
- PIPER-X environment, physics, rendering, and cameras;
- task and reset;
- application of the requested seed and reporting of the effective seed;
- D0-to-native and native-to-D0 processors;
- reward, success, termination, and truncation;
- native recording.

No LeRobot distribution is required in the Isaac process. No Isaac package is
required in `core`.

## 4. Environment and execution-profile ownership

Environment identity, process role, and execution profile are distinct.
No environment is added merely to name a process.

| Execution profile | Environment/process ownership |
|---|---|
| `offline_tests` | `core` |
| `isaac_env` | `isaac` |
| `isaac_vr_record` | `isaac` |
| `isaac_generate` | `isaac` |
| `isaac_dataset_convert` | `core` |
| `isaac_eval` | multi-process: `core` LeRobot evaluator + `isaac` native environment endpoint |
| `mujoco_env` | `core` |
| `mujoco_eval` | `core` |

The `isaac_eval` profile's primary/launch-owning environment is `core`; the
profile topology also declares its required `isaac` process. Its command remains
unresolved until E1. MuJoCo remains a normal same-process Gymnasium/LeRobot path
in `core`; it is not forced through the Isaac boundary.

## 5. EVAL semantic boundary

EVAL is synchronous and episode-sensitive. Its semantic protocol revision is
`piper_x_eval_boundary_v1`. Transport and wire encoding are deliberately not
selected by S0.

The eventual handshake must verify all of:

- protocol revision;
- D0 contract fingerprint;
- environment revision;
- PIPER-X asset/model revision;
- task ID and task revision;
- processor revision;
- horizon.

Minimum operations and fields:

```text
reset(
  run_id,
  episode_id,
  seed,
  task_id,
  task_revision
)
-> canonical_D0_obs_0
-> effective_seed

step(
  episode_id,
  step_index,
  canonical_D0_action_t
)
-> canonical_D0_obs_t_plus_1
-> reward_t
-> terminated_t
-> truncated_t
-> success_t
-> termination_reason
```

The boundary also owns `abort`, `close`, and a minimal health state.

Required failure and ordering semantics:

- exactly one step request may be in flight;
- an ambiguous step timeout is never retried automatically;
- transport failure is infrastructure failure, not task truncation;
- arbitrary Isaac-native dictionaries never cross the boundary;
- Python pickle is forbidden.

E1 will own protocol/codec implementation, the Isaac episodic endpoint, the
core Gymnasium-compatible Isaac proxy, and tests/manifest glue. None exists at
S0.

## 6. CONTROL ownership only

CONTROL is separate from EVAL. It is asynchronous and freshness-sensitive.
S0 records ownership only; it defines no transport or implementation.

Conceptual controller command fields:

- canonical PIPER-X command semantics;
- sequence;
- source timestamp;
- source/control state.

Conceptual observation fields:

- measured canonical observation where required;
- simulator timestamp;
- sequence;
- health/state.

CONTROL requires stale commands to be dropped and never replayed. Native
simulator/device fail-safe behavior remains owned by the runtime-specific edge.
CONTROL does not own reset, seeds, episode metrics, recording, generation, or
asset management.

## 7. Transport decision

Transport selection is **DEFERRED**. No ZeroMQ, gRPC, socket family, shared
memory mechanism, RPC framework, serializer, or deployment topology is selected.
The EVAL and CONTROL semantics do not imply that they must later share a
transport.

## 8. S0 acceptance ownership from live machine rules

The live authority is `configs/gate_rules.yaml` plus
`tools/validate_resolved_contract.py`, not earlier prose.

The S0 rule requires:

```text
prerequisites: D0, C, E0
resolved paths:
  implementation.isaac_lab.version
  implementation.isaac_lab.revision
  implementation.mujoco.version
  implementation.mujoco.revision
  environments.isaac.manager
  environments.mujoco.manager
PASS evidence kinds:
  upstream_source
  document_review
artifact kind:
  report
```

It requires no `command_test`, `artifact_validation`, hardware evidence,
installed runtime, runnable `isaac_env` command, environment smoke test, asset,
task, parity report, or actual evaluation run.

The validator checks required paths/evidence/artifacts only when a gate is
marked accepted. `--require-gate S0` first performs full structural and semantic
validation and then checks that the recorded S0 state is `accepted`. It has no
hidden Isaac installation probe.

By contrast, S1 requires the Isaac asset/task/processors/execution/reset fields,
an `isaac_env` command, command-test evidence, artifact-validation evidence,
model/parity/test artifacts, and embodiment parity. E1 later requires S1 plus
an actual run and run-manifest/evaluation-result artifacts.

Therefore:

```text
S0 ACCEPTANCE REQUIRES ISAAC INSTALLATION: NO
```

## 9. Selected isolated Isaac stack

Same-process compatibility with LeRobot is not a selection criterion.

| Component | Exact S0 selection |
|---|---|
| Isaac Lab | tag `v3.0.0-beta2.patch1`, commit `ffff603eafc6b74264a5261cc0183d6a65390d78` |
| Isaac Sim | `6.0.1.0` |
| Python | CPython `3.12.13` within the required `3.12.x` line |
| torch | `2.11.0+cu128`, required by the Isaac Sim 6.0.1 core package and admitted by the Isaac Lab source-package requirement `>=2.10` |
| torchvision | `0.26.0+cu128`, required by the Isaac Sim 6.0.1 core package |
| CUDA | PyTorch CUDA 12.8 runtime; host driver per Isaac Sim 6.0.1 requirements |
| Gymnasium | `1.2.1` in the vendor environment |
| Isaac Teleop | `1.3.131`, commit `7002ed63d69454ae4f15c0ee19f803fd2846592b`, when the later S2 profile requires it |

The reproducible strategy is an exact source checkout plus the upstream
source-package metadata and NVIDIA launcher in the dedicated `isaac`
environment, with the Isaac Sim core package's exact torch/torchvision pins.
The Isaac Lab repository's development-only torch 2.10 pin is not the selected
runtime constraint; its supported source-package metadata admits torch 2.11.
LeRobot is explicitly excluded from that solve. The checked-in
selection manifest is not installation or smoke evidence; S1 must materialize
and verify the environment on an eligible host and retain the resulting lock,
installation, compatibility-check, and launch outputs.

The earlier audit also found package-metadata inconsistencies inside the broad
NVIDIA extras (notably development `coverage` pins and the later S2 CloudXR
`websockets` extra). S0 does not conceal them or assert that those extras have
executed. The selected vendor workflow and required capability subset must be
materialized without project dependency overrides before S1 acceptance; the
Teleop/CloudXR combination must additionally be verified before S2. A failure
there reopens the affected executable gate, not this audit/selection decision.

## 10. Driver and storage ownership

Preserved host facts:

- installed NVIDIA driver: `580.159.03`;
- Isaac Sim 6.0.1 published/tested x86_64 Linux driver: `595.58.03`;
- current target filesystem free space was below the published 50 GB minimum.

Classification:

```text
DRIVER ISSUE OWNED BY: S1
STORAGE ISSUE OWNED BY: S1
```

Both prevent materializing and executing the selected Isaac environment on the
current host. Neither prevents S0 from pinning and reviewing that environment,
because the S0 machine rule contains no runtime-installation or hardware-host
evidence requirement. No host change was made.

## 11. Reuse and forbidden-abstraction check

```text
SimulatorBackend: NO
RobotBackend: NO
simulator registry/factory: NO
custom OpenXR: NO
custom CloudXR: NO
replacement lerobot-eval: NO
generic recording framework: NO
generic generation framework: NO
mandatory transport for MuJoCo/all simulators: NO
```

Future project-owned E1 work remains limited to protocol/codec, one Isaac
episodic endpoint, one core Gymnasium-compatible Isaac proxy, and tests/manifest
glue. The implementation must be re-audited if it grows beyond that narrow gap.

## 12. Mandatory upstream audit summary

```text
CAPABILITY / GATE
  S0 simulator/evaluation architecture selection
PINNED UPSTREAM CANDIDATES
  LeRobot 0.6.1; Isaac Lab v3.0.0-beta2.patch1; Isaac Sim 6.0.1.0;
  Isaac Teleop 1.3.131; MuJoCo 3.9.0; Gymnasium 1.3.0
WHAT UPSTREAM ALREADY OWNS
  LeRobot checkpoint/processors/inference/eval aggregation; Isaac application,
  environment lifecycle, physics/rendering/managers/recording; MuJoCo physics,
  rendering, and Gymnasium seam
EXACT REMAINING GAP
  PIPER-X tasks/assets/processors and later narrow E1 process-boundary glue
PROCESSOR / CONFIG / ADAPTER REQUIRED
  D0 edge processors; Isaac endpoint/core Gym proxy only for E1
ENVIRONMENT IMPACT
  core remains LeRobot+MuJoCo; isaac remains one isolated vendor environment
WHY NO PROJECT FRAMEWORK IS NEEDED
  only one Isaac endpoint and one core proxy are required; native upstream
  lifecycle and normal lerobot-eval remain authoritative
```
