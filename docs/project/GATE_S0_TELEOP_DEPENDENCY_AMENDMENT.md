# Gate S0 teleop dependency ownership amendment

Audit date: 2026-09-08  
Reopened gate: S0 dependency ownership only  
Verdict: **RE-ACCEPTED**

## Contradiction resolved

The historical `implementation.isaac_teleop` field was ambiguous: its name implied
one project-wide implementation while its value described the accepted Gate B/core
runtime. Candidate B's frozen S2 surface requires a different upstream-supported
version. One global value therefore could not truthfully describe both isolated
execution environments.

The field is replaced by the existing runtime split:

| Runtime owner | Execution profile / environment | Dependency | Exact version / revision | Source of truth |
|---|---|---|---|---|
| Gate B physical Quest | `quest_xr_real` / `core` | `isaacteleop` | `1.3.131` / `7002ed63d69454ae4f15c0ee19f803fd2846592b` | core `uv.lock` |
| Gate S2 simulated Isaac | `isaac_vr_record` / `isaac` | `isaacteleop` | `1.4.98rc1`; bundled CloudXR `6.2.1` | Candidate B frozen `uv.lock` teleop extra |
| Gate S2 simulated Isaac | `isaac_vr_record` / `isaac` | `isaaclab_teleop` | `0.8.0` / `913ac53f51b2f8d02c9e121caa4cbdd06262948e` | Candidate B in-tree package |

The validator binds each dependency record to the spec artifact of the environment
used by its owning execution profile. It also rejects a commit-typed revision that
is not a full commit identifier. The schema rejects the former global field, so no
second conflicting source of truth remains.

Gate B's CloudXR `6.2.0` observation is already core-environment scoped. Candidate
B's locked `isaacteleop` wheel bundles CloudXR runtime `6.2.1`, verified through
`isaacteleop.cloudxr.runtime.runtime_version()`. The two native runtimes do not share
an environment or session and neither fact repins the other.

## Mandatory upstream audit

| CAPABILITY / GATE | PINNED UPSTREAM CANDIDATES | WHAT UPSTREAM ALREADY OWNS | EXACT REMAINING GAP | PROCESSOR / CONFIG / ADAPTER REQUIRED | ENVIRONMENT IMPACT | WHY NO PROJECT FRAMEWORK IS NEEDED |
|---|---|---|---|---|---|---|
| Gate B Quest acquisition | `isaacteleop==1.3.131` at `7002ed63…` in core | accepted session lifecycle, one controller source, physical L/R streams, buttons, validity and recovery | none; accepted evidence remains authoritative | none | no change to core or Gate B | the accepted upstream session already owns acquisition |
| S0 dependency ownership | Candidate B `913ac53f…`, frozen `isaacteleop==1.4.98rc1`, in-tree `isaaclab_teleop==0.8.0` | exact lock, package composition, XR experiences, session and retargeter packages | express two isolated runtime pins without a false global pin | scoped contract records and narrow validation only | no install or process-boundary change in this amendment | the existing `teleop.real` / `teleop.isaac` split is sufficient |
| S2 Quest-to-Isaac control | the Candidate B S2 surface above | CloudXR/Quest session lifecycle, controller source, rebase and retargeting seams | concrete PIPER-X processor, native actuation composition and physical acceptance | one concrete S2 processor/config, no general teleop framework | expand only the existing Candidate B environment from its frozen teleop extra | upstream owns device/session/retargeting; S1 owns simulation |

## Preserved accepted facts

- Gate B remains accepted on the exact runtime that produced its physical evidence.
- Gate S1 and its non-XR runtime, bimanual scene, wrist cameras, reset lifecycle and
  native actuation path are unchanged.
- Isaac remains isolated from core; LeRobot remains absent from the Isaac
  environment.
- Gate C, D0, MuJoCo, and the deferred EVAL/CONTROL transport decisions are
  unchanged.
- No global repin, new environment hierarchy, simulator backend, RPC, or alternate
  Quest implementation was introduced.
