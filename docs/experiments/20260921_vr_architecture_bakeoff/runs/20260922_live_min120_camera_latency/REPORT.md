# LIVE-MIN120 per-camera latency characterization

Frozen failed diagnostic record. Owner: `vr.performance`. This run published no
dataset observations, does not change the canonical runtime or D0 semantics, and
does not qualify a temporal join or physical candidate.

## Scope

- Tested repository HEAD: `690b332689611be5333a61a58832c144f78dc14e`
- Branch/worktree: `wip/vr-recording` at
  `/home/ebulochkin/vla_infrastructure/.worktrees/vr-recording`
- Runtime: 120 Hz physics, 30 Hz control target, four physics steps and one render
  per control, RTX Minimal mode 2, XR scale 0.4
- Cameras: three independent non-tiled 640 x 480 products; previews off; owned RGB
  freeze on
- Diagnostic source SHA-256: `829f6c4bb7e65ba4cc8a370b302d88ee37b3b32ad9dfd8c391cca103300037e5`
- Witnesses: deterministic four-state movement of the existing native PhysX cubes,
  made kinematic only inside the diagnostic so gravity/contact cannot change their
  commanded identity; the existing moving robot finger remained a secondary
  articulation witness

The accepted classifier used visible cube centroid and mask area against four
render-only reference states, distinguishing N, N-1, N-2, and N-3. Camera frame,
data-generation, extraction, and render counters were retained but were not used
as proof of depicted state. The scene articulation marker was intermittently
self-occluded, so it was corroborating rather than the all-boundary classifier.

## Per-camera latency

With two render-only primes, the 1,000 consecutive changing-boundary histogram was:

| camera | 0 | -1 | -2 | -3 | unresolved | longest stable suffix |
|---|---:|---:|---:|---:|---:|---:|
| left wrist | 7 | 992 | 0 | 0 | 1 | 120 |
| right wrist | 0 | 983 | 0 | 13 | 4 | 12 |
| scene | 0 | 994 | 0 | 0 | 6 | 120 |

The non-N-1 boundaries were:

- Left: 104, 204, 420, 824, 828, 876, and 880 at offset 0; 564 unresolved.
- Right: 106, 108, 206, 422, 548, 566, 768, 796, 826, 830, 878, 882,
  and 924 at offset -3; 352, 653, 980, and 988 unresolved.
- Scene: 104, 420, 824, 828, 876, and 880 unresolved.

Offsets are therefore time-varying, not a stable common or role-specific latency.
The repeated correlated left/scene slips and independent right slips also rule out
a fixed per-role buffer depth. Reference acquisition advanced physics from 4,149
to 4,149, proving that the reference images themselves were render-only.

The robot articulation witness was visible in nearly all scene boundaries and its
independent geometric nearest-state diagnostic also varied (-1 on 731 boundaries,
-2 on 267, unresolved on 2). It corroborates instability but is not used to
upgrade an unresolved cube classification.

## Startup / priming

Each priming case advanced zero physics (149 before and after). The first 30
changing rendered boundaries produced:

| primes | left wrist | right wrist | scene | cost ms |
|---:|---|---|---|---:|
| 0 | -1: 29, unresolved: 1 | -1: 20, -3: 6, unresolved: 4 | -1: 29, 0: 1 | 5.993 |
| 1 | -1: 30 | -1: 20, -3: 6, 0: 1, unresolved: 3 | -1: 29, 0: 1 | 60.702 |
| 2 | -1: 30 | -1: 21, -3: 6, unresolved: 3 | -1: 30 | 84.857 |
| 3 | -1: 30 | -1: 21, -3: 6, unresolved: 3 | -1: 30 | 102.829 |
| 4 | -1: 30 | -1: 21, -3: 6, unresolved: 3 | -1: 30 | 118.778 |

Two primes remove the bounded left/scene startup transient, but no allowed prime
count stabilizes the right camera. Primes 2, 3, and 4 reproduced the same right
sequence, including -3 at boundaries 4, 8, 12, 16, 20, and 24. The longer run
then demonstrated additional time-varying slips in all roles, so this is not only
a deterministic phase-specific offset that a role join can encode.

## Temporal join and downstream qualifications

A temporal join is **not required or safe to prototype** because no deterministic
per-role offset exists. Buffer depth and publication latency are therefore
undefined, and canonical `state_N + images_N` observation semantics were never
published or altered. Frame/extraction identities cannot repair this because the
previous run already showed identical identities with different depicted content.

The stop condition prevented the 300 joined-observation run, terminal render-only
drain, reset/recenter/session invalidation, 300-warmup plus 3 x 3,000 performance
runs, and physical candidate creation. No renderer, physics rate, control rate,
XR scale, camera topology, preview policy, RGB ownership, or quality setting was
tuned.

## Evidence

- `priming-summary.json`: complete 0-through-4 prime histograms, first-30 offset
  sequences, and transition timelines; SHA-256
  `ab3639cb3e93cfafdeae83bc9f1f8ee45b7adb94f7c49ce122c6dd98acfde0c1`.
- `long-summary.json`: 1,000-boundary result and runtime/priming identities;
  SHA-256 `097e612df1a3c90d95035d1ed52bbb6a9c5350cf3e4a98ed06ebe556b9622ad1`.
- `classifications.jsonl`: retained raw per-boundary role classifications,
  content errors/margins, RGB hashes, and extraction identities; SHA-256
  `b2bb5e56b71259b95de2f3544a2664f1d51a1ce5fbab51e4c3d419a791fbc729`.

The outer `xr-smoke` commands returned the expected unattended session-gate
failure because no headset operator was available; each characterization artifact
itself reports `failure: null` and `verdict: CHARACTERIZED`.

## D0 and gates

D0 contract change required: **NO**. The diagnostic never completed or published
an observation. D0, S0, and S1 remain unchanged; S2 and D1 remain unresolved. No
4D work or push was performed.

## Verdict

**120 HZ CAMERA LATENCY TIME-VARYING — BLOCKED**
