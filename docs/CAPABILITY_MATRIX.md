# CAPABILITY_MATRIX.md

## Mandatory rows

| Runtime | Source/controller | Operation | Required output |
|---|---|---|---|
| real PIPER-X | [[source:human_vr]] | teleoperate + record | LeRobotDataset v3 |
| Isaac PIPER-X | [[source:human_vr]] | teleoperate + record | LeRobotDataset v3 |
| Isaac PIPER-X | automated source | generate + record | LeRobotDataset v3 |
| Isaac PIPER-X | policy | simulation evaluation | run manifest + metrics |
| MuJoCo PIPER-X | policy | simulation evaluation | run manifest + metrics |
| real PIPER-X | policy | real rollout | rollout manifest + evidence |

Automated Isaac sources may be:

- [[source:scripted_expert]]
- [[source:planner]]
- [[source:datagen]]
- [[source:policy_generated]]

The generated portion requires no per-step human control.

## Evaluation modes

```text
real_rollout
sim_eval
benchmark_native_eval
```

A selected benchmark run is conditionally mandatory only when requested in the contract.

## Common training semantics

Datasets intended for one policy require a materializable common training view:

```text
policy observation features
policy action target
task/instruction semantics
temporal pairing
FPS/resampling policy
```

Source datasets may contain privileged/provenance fields outside this view.

## Cross-runtime PIPER-X parity

Matching API shapes is insufficient.

Acceptance includes:

```text
home/zero
joint limits
positive joint direction
gripper endpoints
FK/TCP parity
policy-facing units/meaning
```
