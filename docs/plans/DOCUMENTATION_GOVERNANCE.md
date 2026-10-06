# Remaining documentation governance work

Owner: governance.documentation. This maintained plan records follow-up decisions;
it is not evidence, a gate acceptance claim or a replacement for the contract.

## Initial migration review context

The initial migration base `98fb74f278e91a7f29a3b00f44a4a2284a053607`
predates INDEX and therefore required manual/code review of classification and
historical file changes. Review of governance commit
`4778ac305d68b2c051b0357487d7bbdb1d6ae9d1` observed 312 historical-classified
files, 0 modified historical files and 0 deleted historical files. These are
migration review observations, not an automated preservation PASS, independently
verified classification or gate evidence. Subsequent preservation uses the INDEX
from a trusted base containing governance.

## Known historical integrity debt

Source: the completed read-only audit of repository
`98fb74f278e91a7f29a3b00f44a4a2284a053607`.

- 59 mismatches in 12 historical output bundle manifests under
  `docs/project/performance/` and `docs/project/xr_fixes/`. The audit matched all
  expected bytes to `d2d18a3^`; path rewriting in `d2d18a3` is the suspected
  source of the transformed copies. Preserve both provenance and failed results.
- Decide separately how to retain originals and identify transformed copies.
  Do not restore files, refresh historical hashes, remove copies or rewrite
  artifact IDs as part of governance implementation.
- Three registered locators depend on `~/.cloudxr`; eleven artifacts are under
  cache locations. Decide durable storage/retention and relocation provenance
  separately before moving any external artifact.

Root selective MANIFEST and registered artifact validation have different scopes
from these historical bundles. Governance preservation checks compare baseline
bytes; they do not certify the bundles' original integrity. No new PASS evidence
is created by recording these audit findings.

## Applicability reviews

- [Old scene specification](../project/PIPER_X_ISAAC_DEMO_SCENE_SPEC.md): review
  unimplemented proposals against the selected three-camera contract. The scene
  camera is now a canonical training input as well as an optional preview; this
  does not adopt the historical proposal's other settings or acceptance claims. It is not
  an approved current implementation plan.
- [Old XR backlog](../project/ISAAC_XR_BACKLOG_20260915.md): reconcile remaining
  work with later fixes, migration and canonical configuration before selecting
  any item. Preserve the historical statuses rather than editing the old file.

Mixed reports have separate maintained owners: current VR operation belongs to
[RUN_VR_OPERATIONS](../project/RUN_VR_OPERATIONS.md), not the historical RoboSyn
report or pre-canonical documentation audit.

## Current implementation reconciliation

Current instructions describe the existing live RUN/DIAG, snapshot-backed RECORD,
strict all-frame replay, LeRobot materialization and demo admission. Implemented
features and physical qualification are separate facts. The recording plan retains
its original reviewed revision and dated checkpoints; its maintained task register
and current-scope section route subsequent work. No historical result is promoted
to acceptance of changed source bytes by updating this documentation.

Remaining work has separate owners:

- RECORD startup resource rollback and finalizer test synchronization: [recording remediation](ISAAC_VR_RECORDING_REMEDIATION.md).
- Request retry, malformed/error response handling, complete policy input and
  RGB retention: [evaluation policy](../EVALUATION_POLICY.md).
- S2 acceptance provenance and remaining D1 source admission: [operator guide](../project/RUN_VR_OPERATIONS.md)
  and [materialization/admission policy](../DATASET_MATERIALIZATION.md).
- Headless rendering: [simulation policy](../SIMULATION_POLICY.md); current
  non-headless qualification does not cover that path.

The [contract validator](../../tools/validate_resolved_contract.py) still needs
stronger proof checks. Gate validation checks PASS evidence kinds without enforcing
gate/profile/source/config applicability; local artifact validation skips content
hashing for existing directories. Require matching registered proof scope and a
defined directory integrity protocol. The acceptance checklist describes these
requirements; their documentation is not a claim that the validator already
enforces them. Historical integrity and external retention debt above remain open.

## Optional next changes

1. Design a generated project status view from contract/rules/index with explicit
   tested scope and unknowns. Do not infer readiness or duplicate selected facts.
2. Consider moving only maintained operations/templates after checking incoming
   links and selected MANIFEST paths. Leave existing history in place by default.
3. Address integrity debt in bounded preservation/repair changes with explicit
   original/transformed provenance; do not combine repair with cosmetic cleanup.
