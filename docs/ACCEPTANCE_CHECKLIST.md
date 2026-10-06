# ACCEPTANCE_CHECKLIST.md — v5.2

This checklist is explanatory. Machine acceptance is `../configs/gate_rules.yaml` plus the validator.

## Contract integrity

- [ ] schema validation fail-closed;
- [ ] no legacy magic placeholders;
- [ ] no unknown profile/environment/evidence/artifact references;
- [ ] local artifact hashes verify;
- [ ] evidence applicability matches the claimed profile, source/config identities
  and tested scope; a PASS from another gate/runtime is not transferred;
- [ ] Markdown machine references lint;
- [ ] migration aliases gone after migration completion.

## Data semantics

- [ ] explicit `obs_t/action_t` transition semantics;
- [ ] causality regression test passes;
- [ ] dataset.action is resolved training label;
- [ ] accepted/native command remains separate;
- [ ] privileged features cannot leak into policy input;
- [ ] provenance/lineage explicit.

## Source datasets

- [ ] Isaac human-VR source accepted;
- [ ] Isaac automated source accepted;
- [ ] real human-VR source accepted;
- [ ] D2a/D2b parity reports accepted.

## Final dataset

- [ ] deterministic materialization route pinned;
- [ ] projected schema fingerprints identical;
- [ ] final immutable dataset identity recorded;
- [ ] all frames/video streams read;
- [ ] DataLoader smoke passes;
- [ ] semantic replay/inspection passes where applicable.

## PIPER-X

- [ ] static driver/API semantics pinned;
- [ ] missing required telemetry rejects the observation without synthetic zeros;
- [ ] partial arm actions and not-motion-ready commands fail before SDK motion;
- [ ] enable timeout and bimanual lifecycle rollback/cleanup pass offline tests;
- [ ] firmware/profile/API pinned per arm;
- [ ] home/limits/sign tests pass;
- [ ] Isaac FK/TCP parity accepted;
- [ ] S1 native state/two-wrist scope and supported rendering configuration recorded;
  headless rendering is used only after separate qualification;
- [ ] MuJoCo FK/TCP parity accepted;
- [ ] gripper endpoints verified.

## Current physical S2 acceptance

- [ ] canonical `./run-vr` in run mode tested using the
  [current worksheet](project/GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md);
- [ ] `run_manifest.json`, generated config, tracked/untracked status, exact invocation,
  processor/source/config hashes and selected environment pins retained;
- [ ] controls, scene/cameras and presentation verified against the canonical VR
  config and shared S2 config, including independent sliders and stationary-pose continuity;
- [ ] axes, rotation, clutch, grippers, tracking recovery, reconnect, reset,
  recenter, preview/backdrop controls and shutdown checked;
- [ ] required camera guards and Scene Partitions remain active in run mode;
- [ ] diagnostics qualify the same control semantics without a second runtime;
- [ ] human evidence registered under `configs/gate_rules.yaml`; smoke PASS and
  experimental asset-lab runs are not accepted physical S2 evidence.

## Isaac recording and materialization

- [ ] RECORD uses the shared scene/control path and immutable pre-action
  snapshot/native state, with no live canonical RGB claim;
- [ ] only completed causal transactions with a verified successor append native rows;
- [ ] strict replay opens the retained snapshot, verifies its dependencies and
  visual provenance, and reports zero physics callbacks;
- [ ] every admitted observation has all three offline RGB roles joined by exact
  observation/snapshot identities;
- [ ] full-read converter/QA and physical recording evidence support source admission;
  command availability and injected smoke do not accept D1.

## Evaluation

- [ ] actual Isaac run artifact exists;
- [ ] actual MuJoCo run artifact exists;
- [ ] same checkpoint SHA for cross-sim;
- [ ] same policy/task revision;
- [ ] seeds/reset protocol recorded;
- [ ] episode count/horizon/success/timeout semantics recorded.

## Safety / real rollout

- [ ] timing/freshness resolved;
- [ ] low-level fail-safe physically verified;
- [ ] joint step/slew resolved;
- [ ] bimanual safety evidence accepted;
- [ ] HIL accepted if required;
- [ ] real rollout checkpoint/processors/task pinned;
- [ ] E-stop/human authorization retained;
- [ ] rollout artifact/result retained.

## Final RC

- [ ] validator prints `FINAL RC READY`;
- [ ] `--require-final-rc` exits 0.
