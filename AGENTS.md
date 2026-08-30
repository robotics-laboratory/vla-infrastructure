# AGENTS.md

## Mission

Build the minimum-custom-code PIPER-X robot-learning system defined by v5.2.

Do not build a robotics framework.

## Read first

For every task:

```text
NORMATIVE_MODEL.md
configs/resolved_contract.yaml
configs/gate_rules.yaml
the topic policy document
```

For hardware/safety also read:

```text
PIPER_X_VERIFICATION.md
SAFETY_TIMING.md
HIL_EXTENSION.md
```

## Mandatory upstream audit

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

## Reuse ladder

```text
upstream implementation
> upstream configuration
> composition
> LeRobot processor / rename map
> thin adapter
> local implementation against public boundary
> fork
```

## Forbidden by default

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

## Shared semantics

The shared contract is the policy-facing PIPER-X semantics, not identical raw simulator dictionaries.

Use runtime-specific processors at the edges.

## Action-label rule

```text
source intent/action
-> deterministic label processors
-> dataset_action_t
-> dataset.action
-> runtime-native mapping
-> accepted/executed native command
```

Do not silently replace the training label with the downstream actuator/device command.

## Temporal rule

```text
obs_t
-> decision
-> dataset_action_t
-> native actuation
-> transition/outcome_t
-> obs_t+1
```

Every converter explicitly maps native fields to these semantics.

## Evidence discipline

A gate cannot be accepted without evidence required by `configs/gate_rules.yaml`.

Do not write "verified manually" without a registered evidence object.

## Environment discipline

Execution profile is not environment identity.

Each runnable stage uses a declared profile and environment. Dependency conflict does not automatically authorize RPC.

## Code-size re-audit

Repeat upstream audit at roughly:

```text
>300 LOC in one integration module
>1000 LOC new runtime code for one gate
```

Tests/config/schema are excluded.

## Final report

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
