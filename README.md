> Общий VR launcher с Kit 110.3 / тремя preview и откатом: [инструкция](docs/project/integrations/20260918_kit1103_preview/README.md).
> Запускать из `/data/vla-infrastructure/robosyn-kit1103` под своим Linux-пользователем.
> Physical Quest acceptance новой интеграции ещё не выполнен.

# PIPER-X + Quest 3 Codex Instruction Pack — v5.2 Hardened

v5.2 is a consolidation/hardening release.

It keeps the v5.1 architecture:

```text
native upstream runtimes
+ LeRobot/Gym/EnvHub/native benchmark seams
+ thin processors/adapters
+ one explicit PIPER-X policy/data contract
- project-owned universal simulator backend
```

but replaces the weak `DECIDE/PIN + *_complete: true` completion model with a machine-enforced contract.

## Mandatory project capabilities

```text
REAL PIPER-X
- Quest/VR teleoperation
- LeRobotDataset v3 recording
- real policy rollout
- hardware safety / HIL acceptance

ISAAC
- Quest/VR teleoperation
- dataset recording
- automated episode generation
- policy evaluation

MUJOCO
- policy evaluation
```

Benchmark-native evaluation remains a first-class supported mode. A specific benchmark is mandatory only when `requirements.capabilities.selected_benchmark` is true.

## Three distinct execution modes

```text
REAL ROLLOUT
policy -> LeRobot Robot -> physical PIPER-X

SIM EVAL
policy -> LeRobot processors -> Gym/EnvHub/native sim env -> metrics

BENCHMARK-NATIVE EVAL
policy -> minimum edge processors -> official benchmark protocol -> comparable result
```

Do not collapse them into one project-owned `rollout()` abstraction.

## What is new in v5.2

- standalone gate definitions;
- one explicit normative/conflict model;
- strict full JSON Schema with closed objects;
- no magic `DECIDE/PIN` placeholders: unresolved values are `null`;
- gate state machine instead of free-floating `*_complete` booleans;
- machine-readable gate dependency DAG;
- first-class evidence and artifact registries;
- local artifact existence/SHA-256 verification;
- fail-closed JSON Schema dependency;
- structured execution profiles;
- machine-readable timing/safety/hardware/calibration/HIL contracts;
- explicit `obs_t <-> action_t` temporal semantics;
- native-recorder conversion causality test;
- D2a -> R2 -> D2b dataset parity ordering;
- executable mixed-source dataset materialization contract;
- full-read/video/DataLoader dataset QA gate;
- PIPER-X sign/home/limits/FK/TCP/gripper cross-runtime parity;
- reproducible Isaac/MuJoCo evaluation run manifests;
- same-checkpoint cross-sim validation;
- real-rollout acceptance manifest;
- machine-derived Final RC readiness;
- negative tests covering known v5.1 false-green classes;
- stale reference/spec linter.

## Canonical files

Read `docs/NORMATIVE_MODEL.md` first.

Live repository operating commands preserved from the pre-v5.2 project are in
`docs/project/CORE_ENVIRONMENT_OPERATIONS.md`; that note is operational, not a
second resolved contract.

- `AGENTS.md`
- `docs/NORMATIVE_MODEL.md`
- `docs/CAPABILITY_MATRIX.md`
- `docs/GATE_SPEC.md`
- `docs/DATA_COLLECTION_POLICY.md`
- `docs/DATASET_MATERIALIZATION.md`
- `docs/SIMULATION_POLICY.md`
- `docs/EVALUATION_POLICY.md`
- `docs/BENCHMARK_POLICY.md`
- `docs/ENVIRONMENT_POLICY.md`
- `docs/PIPER_X_VERIFICATION.md`
- `docs/SAFETY_TIMING.md`
- `docs/HIL_EXTENSION.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/ACCEPTANCE_CHECKLIST.md`
- `docs/MIGRATION_V4_3_V5_1_TO_V5_2.md`
- `docs/DESIGN_BASIS.md`
- `docs/SOURCE_REFERENCES.md`
- `configs/resolved_contract.yaml`
- `configs/resolved_contract.schema.json`
- `configs/gate_rules.yaml`
- `tools/validate_resolved_contract.py`
- `tools/lint_spec_references.py`
- `tests/test_validator_negative.py`

## Validator semantics

Normal validation:

```bash
python tools/validate_resolved_contract.py configs/resolved_contract.yaml
```

A valid but unfinished project prints:

```text
CONTRACT STRUCTURALLY VALID
CONTRACT SEMANTICALLY VALID
FINAL RC NOT READY
```

To require release readiness:

```bash
python tools/validate_resolved_contract.py configs/resolved_contract.yaml --require-final-rc
```

To require one gate:

```bash
python tools/validate_resolved_contract.py configs/resolved_contract.yaml --require-gate S1
```

## Reuse rule

```text
REUSE
> CONFIGURE
> COMPOSE
> PROCESSOR / RENAME MAP
> THIN ADAPTER
> NEW IMPLEMENTATION
```

The stricter v5.2 machine layer is not permission to build more robotics infrastructure.
