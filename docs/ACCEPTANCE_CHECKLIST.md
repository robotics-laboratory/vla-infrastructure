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
- [ ] missing required telemetry rejects the observation without synthetic zeros;
- [ ] partial arm actions and not-motion-ready commands fail before SDK motion;
- [ ] enable timeout and bimanual lifecycle rollback/cleanup pass offline tests;
- [ ] firmware/profile/API pinned per arm;
- [ ] home/limits/sign tests pass;
- [ ] Isaac FK/TCP parity accepted;
- [ ] MuJoCo FK/TCP parity accepted;
- [ ] gripper endpoints verified.

## Current physical S2 acceptance

- [ ] exact default `./run-vr` isaac61 composition tested using the
  [current worksheet](project/GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md) and
  [operator guide](project/RUN_VR_OPERATIONS.md);
- [ ] Git commit, exact operator command, generated `runtime.yaml`,
  `launch_manifest.json`, `isaac61_s2_runtime.yaml`, `robosyn_vr_demo.yaml`,
  processor revision/source and exact environment/package pins retained;
- [ ] independent left/right sliders: min 2x, center 4x, max 6x, continuous
  interpolation and no target jump from slider changes physically checked;
- [ ] axes, rotation, clutch, grippers, tracking recovery, reconnect, reset,
  R3 recenter, X/B presentation, three previews and shutdown checked;
- [ ] final human evidence registered with required machine evidence under
  `configs/gate_rules.yaml`; no blank/old worksheet or no-client smoke promoted;
- [ ] PRIMARY OPERATOR PATH distinguished from ALREADY ACCEPTED GATE CONFIG:
  the selected RoboSyn overlay and slider remain experimental pending acceptance.

`tools/launch_isaac_s2.py` remains the BASE / GENERIC S2 LAUNCHER; its toggle
configuration and base checks do not replace this operator acceptance target.

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
