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

The cache is retained through the run-close response and bounded by the run manifest's
declared step capacity plus reset, abort, and close requests. This is protocol semantics, not
authorization for a generic RPC framework. The one selected implementation is a local
Unix-domain socket carrying UTF-8 JSON Lines between the core evaluator and the concrete
Isaac process. `IsaacEvalEndpoint` owns episode ordering and the bounded dedup cache;
`UnixEvalClient` permits one in-flight request and never retries an ambiguous timeout.
The handshake returns an `endpoint_instance_id`, so a reconnect to a restarted process
invalidates the run. MuJoCo stays single-process unless measured constraints justify a
boundary later.

The canonical Isaac endpoint checks the run manifest against loaded runtime identity
before opening its socket. `environment_revision` is the loaded Isaac Lab checkout SHA;
the selected SDK path, Sim/Lab versions and Kit version must also match its configuration.
The model revision is the accepted asset source commit, with the composed asset hash
checked separately. Task identity and horizon come from the concrete S1 implementation.
`processor_revision` identifies the S1 D0 edge mapping (v1), not the S2 controller
processor (v3). The D0 fingerprint is recomputed using the existing canonical schema
fingerprint function. Mismatches fail closed; `eval-runtime-provenance.json` records the
loaded identity, asset and source hashes. This binding is not E1 evaluation acceptance.

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
