# NORMATIVE_MODEL.md

## 1. Purpose

v5.2 separates static specification rules, resolved project facts, evidence and runtime artifacts.

A resolved value is not proof by itself.

## 2. Normative roles

### Static specification

These define what is allowed and what must be proven:

```text
../AGENTS.md
NORMATIVE_MODEL.md
DOCUMENTATION_POLICY.md
MANIFEST_POLICY.md
CAPABILITY_MATRIX.md
GATE_SPEC.md
DATA_COLLECTION_POLICY.md
DATASET_MATERIALIZATION.md
SIMULATION_POLICY.md
EVALUATION_POLICY.md
BENCHMARK_POLICY.md
ENVIRONMENT_POLICY.md
PIPER_X_VERIFICATION.md
SAFETY_TIMING.md
HIL_EXTENSION.md
../configs/resolved_contract.schema.json
../configs/gate_rules.yaml
```

### Resolved facts

`../configs/resolved_contract.yaml` is the sole machine-readable store of project-specific resolved values. It does not override the static specification.

For current VR, shared S2 processor/runtime semantics live in
`../configs/isaac61_s2_runtime.yaml`; selected operator composition lives in
`../configs/isaac61_vr_runtime.yaml`. Environment pins stay in the environment/S2
records. Markdown links to these machine sources instead of maintaining another
list of current numeric controls/settings. Historical evidence retains its original
inputs and scope. A selected composition is not an accepted gate.

### Evidence

The contract's `evidence` registry points to proof such as upstream source inspection, tests, human gates, hardware observations and run results.

### Artifacts

The `artifacts` registry identifies reproducible inputs/outputs such as environment specs, model assets, calibration, dataset manifests, checkpoints and evaluation reports.

### Documentation governance

[DOCUMENTATION_POLICY.md](DOCUMENTATION_POLICY.md) owns documentation placement,
lifecycle, preservation and registration workflow. [INDEX.yaml](INDEX.yaml) owns
per-file classification, document ownership and navigation only. The mandatory
implementation discipline in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
preserves the detailed agent reuse/audit rules; its roadmap is explanatory.
[README.md](README.md) routes reading without duplicating selected facts.

INDEX does not own gate states, evidence results, artifact identities or runtime
pins. The contract and gate rules retain those roles. [MANIFEST_POLICY.md](MANIFEST_POLICY.md)
owns the explicitly selected integrity set; neither INDEX coverage nor Git
tracking adds MANIFEST membership. Historical classification preserves tested
scope; it neither invalidates evidence nor establishes its authenticity.

## 3. Conflict behavior

If any of these disagree:

```text
static specification
resolved contract
accepted evidence
actual runtime/hardware observation
```

then:

```text
STOP
mark the affected gate blocked/unresolved
record the reason
reconcile contract/evidence
rerun dependent gates when required
```

There is no "higher document wins and continue" shortcut.

## 4. Gate states

Allowed:

```text
unresolved
resolved
configured
smoke_validated
artifact_validated
human_verified
accepted
blocked
```

Only `accepted` satisfies prerequisites of another accepted gate.

`accepted` means all machine prerequisites, required fields, PASS evidence, artifacts and gate-specific checks exist.

## 5. Final RC

`release.final_rc_state` is checked against independently derived readiness.

A false `ready` claim fails validation. If every mandatory gate is accepted but the contract still says `not_ready`, validation also fails.

## 6. Reopening accepted work

Legitimate reasons include:

```text
contradiction
invalidated/lost evidence
unsupported or stale dependency
confirmed upstream defect
safety-relevant upstream change
hardware/firmware change
environment/ABI breakage
```

## 7. Machine-reference syntax

Normative Markdown references machine IDs as:

```text
[[gate:S1]]
[[profile:isaac_eval]]
[[source:human_vr]]
```

`../tools/lint_spec_references.py` checks these identifiers.
