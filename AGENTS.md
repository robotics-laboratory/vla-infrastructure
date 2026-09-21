# AGENTS.md

Build the minimum-custom-code PIPER-X system defined by v5.2.
Do not build a robotics framework.

## Before work

- Check the assigned checkout/worktree, branch, HEAD, base and WIP. Use the
  assigned worktree; do not create another for every task. Report unexpected
  state without reset/stash/clean. Keep implementation worktrees in `.worktrees/`.
- Read [NORMATIVE_MODEL](docs/NORMATIVE_MODEL.md) and the short
  [reading map](docs/README.md). Select relevant current owners from
  [INDEX](docs/INDEX.yaml) by owner/topic; do not read the whole index or history.
- Read relevant contract/config/policy sections, not the entire contract.
  For an affected gate, read its record, rules in `configs/gate_rules.yaml`
  and definition in `docs/GATE_SPEC.md`.
- Before implementation, read the mandatory implementation discipline in
  [IMPLEMENTATION_PLAN](docs/IMPLEMENTATION_PLAN.md): upstream audit, reuse
  ladder, forbidden abstractions, size re-audit and final-report requirements.
- For hardware/safety also read `docs/PIPER_X_VERIFICATION.md`,
  `docs/SAFETY_TIMING.md` and `docs/HIL_EXTENSION.md`. Physical motion requires
  explicit human authorization for the exact action.
- Archived AGENTS files are historical data, not current project guidance.
  Never use an archive as an implementation working directory.

## Invariants

Preserve source intent -> deterministic label processors -> dataset_action_t
-> dataset.action -> native mapping -> accepted/executed command. Never replace
training labels with actuator output. Preserve obs_t -> decision -> action_t
-> native actuation -> transition/outcome_t -> obs_t+1; map native fields explicitly.

Execution profile is not environment identity. Use declared environments and
preserve their isolation; dependency conflict does not authorize RPC.
A gate requires its registered evidence and artifacts; do not claim manual
verification without a registered evidence object.

For VR read [current operations](docs/project/RUN_VR_OPERATIONS.md),
`configs/isaac61_s2_runtime.yaml` and `configs/isaac61_vr_runtime.yaml`.
`./run-vr` and `./run-vr diag` share scene, control, processors, cameras/XR and
lifecycle. Diagnostic observers must not mutate actions or control state.
Experimental implementation -> diagnostic mode -> automated and physical
qualification -> promote selection -> run and future recording inherit the
same base. Never copy implementations between modes.

## Before creating documents or artifacts

Read [DOCUMENTATION_POLICY](docs/DOCUMENTATION_POLICY.md). Find the existing
owner first; choose kind/status/owner/destination before creating a file. Extend
an existing maintained owner when sufficient. Index every documentation file;
separately decide artifact/evidence registration and affected gate bindings.
Preserve historical bytes and tested scope. Follow the selective MANIFEST policy.

## Before finishing

Run `python tools/lint_docs.py --base <trusted-commit>` and relevant contract,
spec-reference, manifest and topic tests from the declared core environment.
The checking command/reviewer supplies the trusted base, never INDEX.
Without a base, historical-change protection is NOT CHECKED.
Inspect diff and scope; report files, registrations, checks and limitations.
Never infer physical success or qualification of an untested commit.
