# HIL_EXTENSION.md

## 1. Reuse rule

Run the HIL implementation/tests from the environment mapped to the `hil` execution profile in `configs/resolved_contract.yaml`. If HIL requires a separate environment from the main control process, treat that as an architecture/process-boundary issue under `ENVIRONMENT_POLICY.md`, not as a shell convenience.


Inspect pinned current LeRobot DAgger/HIL first.

Implement ONLY the remaining per-arm gap.

If the pinned upstream already provides correct independent per-arm semantics, reuse it.

---

## 2. Required modes

```text
POLICY_BOTH
HUMAN_LEFT + POLICY_RIGHT
POLICY_LEFT + HUMAN_RIGHT
HUMAN_BOTH
```

Authoritative intervention bits:

```text
intervention_left
intervention_right
```

If compatibility requires a global field:

```text
intervention_any = intervention_left OR intervention_right
```

It is derived, never independent truth.

---

## 3. Correct action pipeline

Use the same data action space resolved for recording/training:

```text
policy data_action ────────────┐
processed human data_action ───┼─> per-arm merge
takeover mask ─────────────────┘
                                      ↓
                              merged_data_action
                                      ↓
                     deterministic label processors
                                      ↓
                               dataset_action
                                      ↓
                               dataset.action
                                      ↓
                          normal Robot/send path
```

Do not skip deterministic label processors between HIL merge and `dataset.action`.

Do not call `dataset.action` the actually executed/sent command unless separately verified.

---

## 4. Quest takeover/release

Use current measured robot state and existing LeRobot Isaac Teleop clutch/rebase/FK pattern where possible.

The first human command after takeover must satisfy the configured continuity tolerance.

---

## 5. Async policy generation protocol

A queue flush is insufficient because an old request can still be in flight.

The control/inference owner maintains:

```text
policy_generation_id
```

### Request association

At the moment an inference request is dispatched:

```text
request_id -> current policy_generation_id
```

must be fixed.

The result retains that generation association regardless of its later receipt timestamp.

### Generation invalidation event

At least these events invalidate prior context:

```text
takeover transition
release transition
rebase/reset that invalidates policy context
```

The control owner must perform the invalidation transition as one logical operation:

```text
1. increment policy_generation_id
2. invalidate queued old-generation actions/chunks
3. mark pending old-generation results unacceptable
4. reset/reseed interpolator / relevant state
5. acquire fresh full observation
6. dispatch a new request tagged with the new generation
```

Exact locking/async primitive depends on the current upstream architecture. Do not create a generic concurrency framework.

### Result acceptance

Before a result enters the execution queue/interpolator:

```text
result.generation_id == current policy_generation_id
```

must hold.

Otherwise discard it even if the receipt timestamp is fresh.

---

## 6. Bimanual stale-chunk rule

Do not assume the untouched arm's old trajectory remains valid after the other arm is corrected.

Default conservative behavior:

```text
invalidate old bimanual chunk
→ fresh full observation
→ fresh policy inference
```

unless a pinned policy/runtime provides a stronger verified partial-replanning guarantee.

---

## 7. Do not build

- generic ActionMux framework
- replacement DAgger runtime
- custom episode recorder
- custom policy engine
- generic request broker solely for generation IDs

Modify the narrowest upstream seam.
