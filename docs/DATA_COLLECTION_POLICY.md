# DATA_COLLECTION_POLICY.md

## Final dataset owner

All final training data uses LeRobotDataset v3.

Required canonical source records:

```text
runtime=real,  source_class=human_vr
runtime=isaac, source_class=human_vr
runtime=isaac, source_class=<automated canonical source>
```

Do not permanently encode runtime+source as aliases such as `isaac:generated`.

## Source taxonomy

Canonical values:

```text
[[source:human_vr]]
[[source:scripted_expert]]
[[source:planner]]
[[source:datagen]]
[[source:policy_generated]]
[[source:replay_or_transform]]
```

This is semantic provenance, not a Python class hierarchy.

## Temporal semantics

Canonical transition `t`:

```text
obs_t
-> human / expert / planner / policy decision
-> source_action_t
-> deterministic label processors
-> dataset_action_t
-> runtime-specific native actuation mapping
-> environment/robot transition
-> outcome_t and obs_t+1
```

The stored BC pair is `(obs_t, dataset_action_t)` unless a later contract revision explicitly changes the learning target.

For every native recorder/converter, resolve:

```text
native field -> obs_t
native field -> action_t
native field -> outcome_t / termination / success
```

## Causality regression test

Before [[gate:D0]] acceptance, run a distinguishable synthetic trajectory such as:

```text
obs_t = t
action_t = 1000 + t
```

After recording/conversion, verify exact pairs `(obs_0, action_0)`, `(obs_1, action_1)`, etc.

Timestamp monotonicity alone does not prove causal pairing.

## Common training view

Classify features as:

```text
training_input
training_target
evaluation_only
provenance_only
privileged_debug
```

The exact policy-input set is whitelist-checked.

Simulator ground-truth state must not enter a real-deployable policy through implicit passthrough.

## Provenance

At minimum identify:

```text
runtime
source_class
task_id / task_revision
embodiment_revision
processor_contract_revision
dataset/source revision
generator/planner revision where applicable
source demonstration lineage where applicable
generator/randomization seed where applicable
policy checkpoint where applicable
conversion revision
```

Use native LeRobot metadata where suitable. A versioned sidecar/manifest is allowed when necessary.

## Failed/aborted episodes

Do not silently mix:

```text
success
failure
timeout
abort
tracking-stale
```

The QA report classifies them.

## Immutable source datasets

Keep source/canonical datasets identifiable. A mixed training dataset should be reproducibly materialized rather than destructively replacing the only source copy.
