# ENVIRONMENT_POLICY.md

## Environment != execution profile

An environment describes dependencies/runtime. A profile describes how a stage launches. Several profiles may share one environment.

## Required environment records

v5.2 always declares:

```text
core
isaac
mujoco
```

MuJoCo should map to `core` if compatible, but a justified separate environment is permitted. Isaac may require a vendor runtime.

## Required environment fields

Every accepted environment records:

```text
id
purpose
manager/launcher
Python version
reproducible spec artifact
torch version where applicable
CUDA runtime where applicable
vendor runtime where applicable
system requirements
canonical launch prefix
```

## Required execution profile fields

Every runnable profile records:

```text
environment id
working directory
command template
prerequisites
```

Unknown environment references are invalid.

## Current Quest -> Isaac operator launch

[[profile:isaac_vr]] launches `./run-vr`; `./run-vr diag` uses the same profile and
environment with diagnostic observers. Modes do not create environment identities.
Pins remain in the selected environment and shared S2 config; the canonical VR
composition carries operator semantics only. See
[operator operations](project/RUN_VR_OPERATIONS.md) for ownership and rollback.
Physical S2 acceptance is required. The unresolved D1 recorder has no execution
profile or working record command.

## No hidden mutation

No accepted manual `pip install` may exist outside the reproducible spec.

## Dependency ownership across environments

A dependency version is owned by the runtime/environment that executes it. Separate
accepted environments may carry different upstream-supported versions when their
reproducible specifications require them. Such facts must be recorded under the
owning runtime, reference that environment's spec artifact, and must not also be
represented by an ambiguous project-global pin.

## Dependency conflict

```text
capture exact evidence
decide whether same-process is semantically required
prefer compatible upstream pins/config
create special env only when justified
do not invent RPC automatically
```

## Mandatory profiles

```text
[[profile:offline_tests]]
[[profile:quest_xr_real]]
[[profile:real_dataset_record]]
[[profile:real_rollout]]
[[profile:hil]]
[[profile:piper_readonly]]
[[profile:piper_motion]]
[[profile:isaac_env]]
[[profile:isaac_vr]]
[[profile:isaac_generate]]
[[profile:isaac_dataset_convert]]
[[profile:isaac_eval]]
[[profile:mujoco_env]]
[[profile:mujoco_eval]]
[[profile:dataset_materialize]]
[[profile:dataset_qa]]
[[profile:benchmark_template]]
```
