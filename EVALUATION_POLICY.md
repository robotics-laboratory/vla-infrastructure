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
