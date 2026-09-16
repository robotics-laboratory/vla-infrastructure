# Gate S0 Isaac compatibility remediation — Candidate B

Date: 2026-09-08
Result: **PASS / REPIN TO CANDIDATE B**
Classification: **HISTORICAL / RESOLVED / NOT CURRENT RUNTIME**

This is the sole retained narrative for the superseded pin and rejected Candidate
A. Current runtime identity lives in `configs/environments/isaac_release_3_0_0.yaml`.

## Reopen reason

The accepted beta2 pin was stale because the executable upstream-native
wrist-camera/render behavior required by S1 failed. The remediation qualified two
successive upstream candidates without patching Isaac Lab, Isaac Sim, the renderer,
or the NVIDIA driver.

| Candidate | Exact revision | Result | Decision |
|---|---|---|---|
| old accepted `v3.0.0-beta2.patch1` | `ffff603eafc6b74264a5261cc0183d6a65390d78` | FAIL: native wrist render path | superseded |
| A `release/3.0.0-beta2` | `99f1423e5d4a26216c0eedeb2aa78099a8c3a7d1` | FAIL: camera/RGB/reset rendering | rejected |
| B `release/3.0.0` | `913ac53f51b2f8d02c9e121caa4cbdd06262948e` | PASS | selected |

Candidate B passed exact runtime identity, accepted Gate C articulation, native
parented wrist-camera transforms, 220/220 one-camera frames, 440/440 bimanual
frames, independent wrist following, 275–280 px rendered target motion, reset to
baseline below 0.03 px centroid error, and clean process exit.

## Dependency disposition

The environment uses Candidate B's own frozen root workspace. Its
`[tool.uv].override-dependencies` intentionally replaces Isaac Sim requirements.
The resulting 11 `uv pip check` incompatibilities are not erased or described as a
clean metadata solution; the exact list is in `GATE_S0_COMPATIBILITY_PROBES.txt`
and `configs/environments/isaac_release_3_0_0.yaml`.

The bounded S1 surface qualified with those conflicts present. They become a
blocker only if an actual required path fails. They must be re-audited before S2,
Isaac Teleop/XR, or any other environment expansion.

## Host disposition

Candidate B documents Linux `580.95.05` or later. The unchanged host driver is
`580.159.03`; it satisfies the documented recommendation and passed empirically.
No driver change is required. Heavy checkouts, environments, caches, and run
artifacts remain under `/data/vla-infrastructure`; `/data/piper-stand` was not mutated.
The superseded `595.58.03` blocker was an old-pin conclusion and is not a current
Candidate B requirement.

## Architecture disposition

The isolated process split remains necessary and sufficient. It is independent of
the old camera defect and of whether package metadata is mutually satisfiable with
LeRobot. LeRobot remains in core; Isaac remains native and isolated. EVAL and
CONTROL transports remain deferred. No framework, generic backend, raw Replicator
replacement, Base Kit path, or universal camera abstraction is authorized.
