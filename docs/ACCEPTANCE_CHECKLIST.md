# ACCEPTANCE_CHECKLIST.md — v5.2

This checklist is explanatory. Machine acceptance is `../configs/gate_rules.yaml` plus the validator.

## Contract integrity

- [ ] schema validation fail-closed;
- [ ] no legacy magic placeholders;
- [ ] no unknown profile/environment/evidence/artifact references;
- [ ] local artifact hashes verify;
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
- [ ] firmware/profile/API pinned per arm;
- [ ] home/limits/sign tests pass;
- [ ] Isaac FK/TCP parity accepted;
- [ ] MuJoCo FK/TCP parity accepted;
- [ ] gripper endpoints verified.

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
