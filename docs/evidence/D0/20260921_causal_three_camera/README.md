# D0 v4 causal three-camera offline evidence

This frozen bundle proves contract/schema/validator semantics on the source bytes
in [inputs_and_schema.json](inputs_and_schema.json), based on commit
`76b93ee6562ac1da2e21551d1aff5454cfd7a859`. It does not qualify Isaac runtime,
Quest, physical motion, a dataset source, or any later recording stage.

## Result and reproducibility

[causality_tests.txt](causality_tests.txt) retains the actual core-environment
pytest output: **105 passed, 4 subtests passed**. The manifest contains the exact
command, Python/environment, tested source digests, ordered schema and recomputed
fingerprint. The one deselected test checks the final gate graph after registration;
it is run by the final full-suite validation. No causality test is omitted.

Contract revision changes from `piper_x_d0_policy_data_v2` to
`piper_x_d0_policy_data_v4`; contract version is 5.2.6 and schema version stays 5.2.
The exact training order is state, left wrist, right wrist, scene, task, action.
The old fingerprint is
`eb7e4613e5f8d0ff59039874555e6f2d73b728973e64cc01da8414e010d8d33d`.
The project implementation recomputes
`5926a9271f997202970f757738327593d22ed2ad2696c478cb69a75d35dd1ee1`.
The complete typed ordered specification is retained in the manifest, not inferred
from those hash strings. State/action names, units and semantics are unchanged.

## Upstream and reuse audit

Capability/gate: D0 semantics and offline proof. Pinned candidate: LeRobot 0.6.1 at
`7e241bd630a3719a56157a497ce5d08f244784f1`; installed record_loop, writer, default
processor and feature builder hashes exactly match the preserved
[pinned audit](../../../project/GATE_D0_UPSTREAM_AUDIT.md). Source statements were
re-read locally. LeRobot owns processors, frame construction, pacing, dense logical
time, dataset format and persistence. Its writer follows send_action before the
next observation; executable statements retain pre-native labels despite the
misleading upstream comment about saving the sent command.

The gap is source-profile causal identity and immutable payload binding. A small
neutral validator supplies those records and prepare/complete/commit/abort. The
existing physical algorithm is extracted and reused without changing age, skew,
sequence or clock behavior. The real compatibility facade keeps the upstream seam.
Its explicit commit_transaction_frame bridge verifies the actual typed payload at
persistence, while final causal commit still requires the successor observation.
Legacy record_loop integration still requires source-owned identity wiring before
full v4 source admission; no real source has been admitted by these tests.

No environment change, new dependency, backend, RPC layer, recorder, controller,
IK implementation or camera driver was introduced. The source runtime remains
responsible for truthful atomic identities and content-addressed references. The
validator proves consistency of supplied identities; offline fakes cannot prove
that a device or simulator produced them.

The size audit was repeated before crossing 500 added/reworked production lines
and the new module's 300-line mark: 553 added/reworked lines including moved
physical code, 90 removed, net +463. Reuse retained the existing physical checks
and LeRobot integration. The extra scope is the explicit real persistence bridge,
typed payload hashing and source-admission checks. A framework provides no missing
capability here; the transaction keeps only identities/digests, one pending record
and run-local duplicate history. Destroy the validator at run close.

## Negative evidence

- Exact synthetic pairs `(obs_t=t, action_t=1000+t)` across all three profiles;
  action t-1 and t+1 are rejected; clipped native payload differs from the label.
- Observation/action substitution at prepare and commit; a changed scene payload
  is rejected by the real persistence bridge before the writer receives it.
- Run/episode/source, reset, control-reference and session/source epoch crossing;
  epoch change invalidates pending work; new reset epochs may restart sequences.
- Commit before completion, wrong completion tick, failed transition, forged token,
  aborted transaction, reused transition/commit and mismatched successor.
- Missing scene identity, repeated/regressing source identity, physical metadata
  mismatch, stale camera/joint/XR, future source time, missing physical XR, skew,
  clock mismatch and repeated/regressing sequence/time. Physical metadata is frozen
  and prepared bundles cannot cross an episode reset.
- Isaac human has resolved XR identity and tracking validity without physical
  acquisition time; Isaac automated has generator provenance without XR; real
  human requires all seven physical timing streams. Legacy physical automated
  probes remain compatibility tests, not an admitted source profile.
- Three-camera order, actual fingerprint, source-profile dispatch and admission,
  schema/whitelist parity, preserved physical limits and prerequisite graph checks.

The real/PIPER tests retain CAN per-component oldest-time assembly and wall-clock
calibration/drift rejection. Limits remain camera/XR/skew 75 ms and joint/action
45 ms. No R2/HIL physical requirement is relaxed.

## Scope, registration and remaining work

The new artifact/evidence IDs are `gate_d0_v4_report`, `gate_d0_v4_inputs`,
`gate_d0_v4_test_output`, `gate_d0_v4_review` and `gate_d0_v4_causality`.
They supplement preserved historical D0 objects; no old evidence bytes or identity
are rewritten. S0/S1 records are unchanged. S2/D1 remain unresolved. D0 acceptance
is committed only after the new proof and prerequisite/governance checks pass.
Root MANIFEST membership is unchanged; this new bounded bundle has its own artifact
hashes and explicit INDEX entries.

Real three-camera source requirement defined; actual source registration remains
pending: **UNREGISTERED / EVIDENCE PENDING**, with `dataset.sources: {}`. No legacy
RoboSyn dataset, source path or immutable dataset ID has been invented.

4B capture barrier, 4C resolved XR/preclip seam, 4D RecorderManager/HDF5,
4E converter and 4F performance plus physical D1 remain future runtime work.
The Isaac action seam is specified, not implemented or qualified here.

Development checks initially found a cache-write sandbox error, missing editable
plugin import, a schema-edit targeting error and expected missing v4 evidence.
They were corrected with a /tmp cache, this checkout's package PYTHONPATH, the
intended schema location and new evidence registration. Scoped Ruff and mypy pass.
An optional whole-tree mypy run reports 95 errors in 12 unchanged Isaac/support
files, including unavailable SDK imports; it is not a runtime qualification test.
