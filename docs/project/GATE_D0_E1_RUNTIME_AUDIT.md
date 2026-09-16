# D0/E1 runtime implementation audit

Date: 2026-09-16

## Temporal recording / D0

CAPABILITY / GATE

Source-time persistence and fail-closed frame admission at D0; numeric limits and real
dataset acceptance remain owned by D1/G1/R2.

PINNED UPSTREAM CANDIDATES

LeRobot 0.6.1 at `7e241bd630a3719a56157a497ce5d08f244784f1`.

WHAT UPSTREAM ALREADY OWNS

`DatasetWriter.add_frame` validates declared features, creates `frame_index`, computes
`timestamp = frame_index / fps`, and persists the episode. The writer deliberately has
no knowledge of XR/camera/joint acquisition clocks or source-age limits.

EXACT REMAINING GAP

Validate one selected physical-source bundle in a common monotonic domain and persist
sequence, acquisition timestamp, domain, age, and cross-modal skew before the upstream
writer is called.

PROCESSOR / CONFIG / ADAPTER REQUIRED

`tools.d0_temporal.TemporalFrameRecorder`, configured from the resolved D0 feature map
and gate-owned numeric limits. It delegates every accepted frame to upstream unchanged
apart from the required provenance-only timing features.

ENVIRONMENT IMPACT

The core profile enables LeRobot's pinned `dataset` extra so the real v3 writer seam is
covered by integration tests. Isaac remains free of LeRobot.

WHY NO PROJECT FRAMEWORK IS NEEDED

The adapter has one method at one existing persistence seam; it is not a replacement
recorder or a source hierarchy.

## Isaac evaluation / E1

CAPABILITY / GATE

Episode-sensitive request identity and deduplication for the already selected isolated
Isaac evaluation process. E1 remains unresolved until a real checkpoint run and its
manifest/result artifacts exist.

PINNED UPSTREAM CANDIDATES

LeRobot 0.6.1 evaluator in core and the accepted Isaac Lab Candidate B runtime at
`913ac53f51b2f8d02c9e121caa4cbdd06262948e`.

WHAT UPSTREAM ALREADY OWNS

LeRobot owns checkpoint loading, policy processors, inference, and result aggregation.
The concrete `BimanualPiperXIsaacEnvironment` owns reset, D0 observation/action mapping,
physics, reward, termination, truncation, and success.

EXACT REMAINING GAP

The two pinned environments cannot share a Python process. The boundary needed request
identity, episode ordering, reconnect-safe deduplication, restart detection, and a
non-pickle codec.

PROCESSOR / CONFIG / ADAPTER REQUIRED

`tools.isaac_eval_rpc` implements exactly one local Unix-domain JSON-Lines boundary.
`IsaacEvalEndpoint` wraps the concrete Isaac environment; `UnixEvalClient` is the core
side. `run_isaac_s1.py --eval-socket --eval-run-manifest` activates the endpoint in the
accepted Isaac process.

ENVIRONMENT IMPACT

No dependency is added to Candidate B: the endpoint uses the Python standard library
and NumPy already present there. Core gets only the LeRobot dataset extra required by
the D0 integration test/recording path.

WHY NO PROJECT FRAMEWORK IS NEEDED

There is no simulator registry, backend interface, service discovery, generic remote
environment, or MuJoCo transport. The implementation names Isaac and its four protocol
operations directly.
