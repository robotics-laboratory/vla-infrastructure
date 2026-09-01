# HIL_EXTENSION.md

## Scope

Per-arm HIL is a narrow project extension around the selected LeRobot inference/control path. Do not replace upstream inference, recorder or policy runtime.

## Required modes

```text
POLICY_LEFT  + POLICY_RIGHT
HUMAN_LEFT   + POLICY_RIGHT
POLICY_LEFT  + HUMAN_RIGHT
HUMAN_LEFT   + HUMAN_RIGHT
```

Authoritative intervention features:

```text
intervention_left
intervention_right
```

## Mixed-mode semantics

The machine contract resolves:

```text
does policy receive fresh full-bimanual observations?
what happens to the suppressed arm policy action?
does the untouched arm continue a pre-takeover chunk?
what invalidates global vs per-arm generations?
what state is used to rebase on release?
```

No mixed-mode behavior is inferred from names alone.

## Generation invalidation

If async/chunk inference is used:

```text
request -> generation id
generation transition -> invalidate stale requests/results/queued chunks/interpolator state
```

A stale result must never enter execution after invalidation.

## Takeover/release

Use measured robot state for release/rebase when required. Resolve takeover/release continuity tolerance in `safety`.

## Machine evidence [[gate:HIL]]

Requires:

```text
deterministic concurrency tests
physical human-gate evidence
rebase implementation reference
generation owner/invalidation fields
mixed-mode semantics
```

Avoid timing-sensitive sleeps as race proof.
