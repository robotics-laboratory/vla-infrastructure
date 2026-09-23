# IMPLEMENTATION_PLAN.md — v5.2

v5.2 is standalone. Migrated evidence satisfies a gate only if it meets v5.2 requirements.

Recommended implementation sequence (the exact dependency DAG is owned by
`../configs/gate_rules.yaml`):

```text
[[gate:M0]]
 |
 +-> [[gate:E0]]
 +-> [[gate:A]]
 +-> [[gate:B]]
 +-> [[gate:C]]
        |
        v
     [[gate:D0]]
        |
        +--------------------------+
        |                          |
        v                          v
      SIM                        REAL
        |                          |
     [[gate:S0]]                [[gate:R0]]
        |                          |
     [[gate:S1]]                [[gate:R1]]
      /   |   \                    |
     /    |    \                [[gate:R1B]]
[[gate:S2]] [[gate:G1]]             |
   |             |               [[gate:R2]]
[[gate:D1]]      |                  |
   \             /                  |
    [[gate:D2a]]                    |
         |                          |
     [[gate:M1]]                    |
      /       \                     |
[[gate:E1]] [[gate:E2]]             |
      \       /                     |
       [[gate:E3]]                  |
             \                      /
              \                    /
               [[gate:D2b]]
                    |
                 [[gate:DM]]
                    |
                 [[gate:DQ]]
                    |
           [ [[gate:T0]] if required ]
                    |
                 [[gate:HIL]]
                    |
                 [[gate:R3]]
```

Benchmark branch:

```text
[[gate:B0]]
   |
[ [[gate:B1]] if selected benchmark required ]
```

## Per-gate workflow

1. read `NORMATIVE_MODEL.md` and `../configs/gate_rules.yaml`;
2. verify prerequisites;
3. use declared [[profile:offline_tests]] or the gate-specific profile;
4. inspect pinned upstream before code;
5. register evidence/artifacts;
6. update only facts supported by evidence;
7. move gate state only as far as evidence permits;
8. run validator, spec-reference linter and relevant tests;
9. commit gate separately.

## Physical boundary

Codex may prepare commands and analyze logs. It must not infer unobserved physical success. Motion requires explicit human authorization for the exact action.

## Current physical S2 target and feature flow

[[gate:S2]] human acceptance tests the canonical `./run-vr` composition in run mode.
Use the [operator guide](project/RUN_VR_OPERATIONS.md) and
[current worksheet](project/GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md).
Retain `run_manifest.json`, generated config and exact source/config hashes.

Experimental implementation -> `./run-vr diag` -> automated and physical
qualification -> promote selected config/status -> `./run-vr` inherits the feature
-> record consumer inherits the same base semantics.
Promotion changes config/status, never copies Python implementation. There is one
scene builder and control loop with mode-specific observers/side effects.
The state-only `./run-vr record` and snapshot `replay` commands are implemented.
D1 source admission, conversion and demonstration qualification remain pending.

## Mandatory implementation discipline

The following requirements apply before implementation work. They are preserved
from the root agent instructions; this maintained section owns their detail.

### Mandatory upstream audit

Before substantial runtime code report:

```text
CAPABILITY / GATE
PINNED UPSTREAM CANDIDATES
WHAT UPSTREAM ALREADY OWNS
EXACT REMAINING GAP
PROCESSOR / CONFIG / ADAPTER REQUIRED
ENVIRONMENT IMPACT
WHY NO PROJECT FRAMEWORK IS NEEDED
```

### Reuse ladder

```text
upstream implementation
> upstream configuration
> composition
> LeRobot processor / rename map
> thin adapter
> local implementation against public boundary
> fork
```

### Forbidden by default

Do not create without demonstrated need:

- universal `SimulatorBackend`;
- `RobotBackend`;
- generic simulator registry/factory;
- project-wide `EpisodeSource` or `EpisodeGenerator` hierarchy;
- custom dataset format;
- replacement dataset recorder;
- replacement `lerobot-eval`;
- replacement policy runtime;
- duplicate FK/IK solver;
- custom OpenXR/CloudXR protocol;
- generic action ontology;
- mandatory RPC because environments differ;
- one environment/container per conceptual component.

### Shared semantics

The shared contract is the policy-facing PIPER-X semantics, not identical raw simulator dictionaries.

Use runtime-specific processors at the edges.

### Action-label rule

```text
source intent/action
-> deterministic label processors
-> dataset_action_t
-> dataset.action
-> runtime-native mapping
-> accepted/executed native command
```

Do not silently replace the training label with the downstream actuator/device command.

### Temporal rule

```text
obs_t
-> decision
-> dataset_action_t
-> native actuation
-> transition/outcome_t
-> obs_t+1
```

Every converter explicitly maps native fields to these semantics.

### Evidence discipline

A gate cannot be accepted without evidence required by `configs/gate_rules.yaml`.

Do not write "verified manually" without a registered evidence object.

### Environment discipline

Execution profile is not environment identity.

Each runnable stage uses a declared profile and environment. Dependency conflict does not automatically authorize RPC.

### Code-size re-audit

Repeat upstream audit at roughly:

```text
>300 LOC in one integration module
>1000 LOC new runtime code for one gate
```

Tests/config/schema are excluded.

### Final report

```text
GATE
REUSED
PINNED / VERIFIED
EXECUTION PROFILE / ENVIRONMENT
CONTRACT CHANGES
EVIDENCE ADDED
ARTIFACTS ADDED
PROCESSORS / ADAPTERS
TESTS
HUMAN EVIDENCE
BLOCKERS / REOPEN REASONS
NEXT GATE
```
