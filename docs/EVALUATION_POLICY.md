# EVALUATION_POLICY.md

## Generic simulator evaluation

Isaac and MuJoCo evaluation use reproducible run manifests.

Each accepted run records:

```text
checkpoint artifact + SHA-256
policy config artifact
preprocessor artifact
postprocessor artifact
policy contract revision
environment revision
task id/revision
seed set
number of episodes
episode horizon
success semantics revision
timeout semantics
execution profile
raw log artifact
result artifact
```

## Episode-sensitive request identity

The isolated Isaac evaluation boundary uses client-generated `request_id` values scoped
by `run_id`. Reset, step, abort, and close are non-idempotent operations and require the
identity. Every operation response echoes it.

The runtime endpoint binds each `(run_id, request_id)` to the canonical operation and
payload fingerprint:

```text
same identity + same fingerprint      -> return cached response; do not execute again
same identity + different fingerprint -> protocol error; do not execute
ambiguous timeout                     -> no automatic retry
explicit retry                         -> same request_id only
transport reconnect                    -> dedup cache remains valid
endpoint restart                       -> invalidate run; infrastructure failure
```

The cache is retained until run close and bounded by the run manifest's declared
`n_episodes × horizon` plus lifecycle requests. This is protocol semantics, not
authorization for a generic RPC
framework: transport and implementation remain deferred, and MuJoCo stays single-process
unless measured constraints justify a boundary later.

## Cross-sim comparison [[gate:E3]]

Require:

```text
same checkpoint SHA-256
same policy contract revision
same canonical task id/revision
compatible policy-facing input/output contracts
```

Seed integers need not be numerically equal if runtimes implement RNG differently. Each side must have a pinned reset/seed protocol.

If exact initial states can be shared, prefer an explicit initial-condition manifest.

## Metrics

At minimum record:

```text
episodes attempted
success count/rate
timeout count
failure count/category where available
reward aggregation where meaningful
```

Do not require equal Isaac/MuJoCo scores.

## Ready vs complete

Configuring an eval path does not complete eval. `accepted` requires an actual run artifact.
