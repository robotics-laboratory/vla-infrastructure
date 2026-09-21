# Camera phase findings

Frozen research record, 2026-09-21 UTC. Classification: **REAL CAMERA LAG** in
this bounded, actively driven simulation probe. The XR camera content discrepancy
is not confined to the previous USD material marker: an existing PhysX cube and
the actual robot gripper visual mesh also reproduce the previous physics state.
This does not qualify a physical Quest run or a natural-contact trajectory.

## Scope and ownership

Kind: experiment (frozen run findings). Status: historical. Owner: `vr.performance`. Mutable: false.
Documentation and artifact/evidence registration belong to the enclosing bake-off.
No canonical source/configuration files were changed. Tested checkout:
`/home/ebulochkin/vla_infrastructure/.worktrees/vr-recording`, branch
`wip/vr-recording`, HEAD `8d854b94c91a3a9e051e742fa7dd6b6a0a0939c4`.
The runtime lineage remains `bd288917ac44a873feef04df9a488c4046927d87`.

The declared Isaac environment is `/data/vla-infrastructure/isaac61_production/env`
and pinned Isaac Lab checkout is
`/data/vla-infrastructure/isaac61_production/IsaacLab`. These are XR-enabled
synthetic session and no-client probes, with no physical headset operator or
physical robot motion. The stimulus is an experiment-only native state mutation,
not a passive diagnostic observer and not a recording consumer.

[Phase probe](phase_probe.py) runs after 100 ordinary diagnostic controls in the
three durable runs. It executes 24 additional control boundaries, with four
physics steps and four renders per boundary. The first five probe boundaries are
warmup; all 19 remaining boundaries are retained. Physics stays at 120 simulated
Hz. There is no outlier removal and no long-benchmark claim.

Before every physics integration the experiment sets distinguishable native
positions for the existing left cube and joint coordinates for the existing left
articulation. It also updates six USD emissive bits per canonical camera. The
cube and actual `gripper_base` visual geometry receive static diagnostic colors;
these colors are not changed per step. Native measured state is retained at every
substep. Cameras are extracted at the existing control boundary. This tests
transform/render phase, not S1 dynamics, teleoperation actions, task success or D0
transaction acceptance.

## Results

Here `P` denotes the final measured physics state at a control boundary. Thus
`P-1` is the earlier report's `P+3` when its control begins at `P` and ends at
`P+4`. The observed gap is one physics substep, not one whole control transition.

| Trial | USD bits, all three cameras | Existing PhysX cube, fixed scene view | Actual articulation visual mesh |
|---|---|---|---|
| Durable no-XR | Current state in 19/19 boundaries per camera | Current state in 19/19; centroid residual mean 0.846 px, max 1.035 px | Visible geometry; geometric-centroid method biased by occlusion, so no exact-lag verdict from that method |
| Durable XR | Previous state in 19/19 boundaries per camera | Previous state in 19/19; residual mean 1.028 px, max 2.534 px; current-state residual mean 64.398 px, max 65.750 px | Same centroid limitation; resolved by the separate native image-reference trial below |
| XR native image-reference trial | Previous state in 19/19 boundaries per camera | Previous state in 19/19; residual mean 1.067 px, max 3.259 px; current-state residual mean 64.379 px, max 65.751 px | Previous-state reference matches all three selected boundaries; current-state reference has zero silhouette overlap |

Every measured boundary in these trials has a render-generation delta of four.
Wrist-view native-object centroid estimates are deliberately not used as phase
proof: the cameras move with the articulation and some witnesses are outside
those views. Fixed-scene-view projection and separately rendered references own
the native-geometry verdict. USD bits separately cover all three camera roles.

### Articulation reference qualification

The original geometric-centroid estimate was misleading because the visible
magenta portion of the gripper mesh is partly occluded by the wrist and camera.
It falsely preferred a more distant lag in the XR trial. Those raw estimates are
retained; they must not be interpreted as a three-substep articulation lag.

After all measured boundaries finished, the experiment restored the recorded
native articulation joint coordinates for each of `P`, `P-1`, `P-2`, and `P-3` at
three selected boundaries. Restoration uses upstream
`write_joint_position_to_sim_index`, zeros joint velocity, calls `sim.forward()`,
and performs four settling-only `sim.render()` calls. The fixed scene camera is
then extracted. No action is replayed and no physics integration is requested.
The physics-step counter remains unchanged across all 12 reference generations.
These 48 reference renders are outside the measured control boundaries and are
never claimed as canonical capture performance or dataset frames.

The comparison isolates the actual gripper mesh's static magenta silhouette.
Only robot state is restored for these references; other scene pixels are not
part of this mask metric. IoU is intersection over union of the two masks.

| Probe tick | Previous-state IoU | Previous-state centroid difference | Current-state IoU | Current-state centroid difference |
|---|---:|---:|---:|---:|
| 21 | 0.955318 | 0.455388 px | 0 | 95.769290 px |
| 22 | 0.937431 | 0.072831 px | 0 | 95.819617 px |
| 23 | 0.959792 | 0.455405 px | 0 | 95.796207 px |

`P-2` IoU is zero at all three boundaries; `P-3` IoU is 0.092633–0.099960.
The maximum previous-state reference centroid discrepancy is 0.455405 px.
Pixel-perfect equality is not claimed. Representative native-reference images
were inspected; the measured and previous-state gripper locations agree.

## Preserved attempts and limitations

1. The first XR attempt failed before any new phase measurement because both a
   rigid-body prim and its nested visual prim were named `gripper_base`. The
   resolver now explicitly selects the body using `UsdPhysics.RigidBodyAPI`.
   Its traceback, source and ordinary timing records are retained. No result
   JSON was produced; its absence is recorded, not repaired.
2. The next XR attempt used a newly attached articulation sphere that was not
   visible. Its cube result still matched the previous native state in 19/19
   scene-view boundaries: mean residual 1.415 px, max 3.534 px. Articulation was
   unresolved. Its USD bit threshold was too low for reflected black surfaces;
   those bit results are invalid. The failed method and images are retained.
3. The durable pair recolors existing gripper geometry and uses a corrected USD
   bit threshold. The native-reference trial resolves the remaining gripper
   centroid ambiguity. The earlier raw `best_lag` fields remain intact.

This is bounded visual phase evidence under deliberately separated native-state
stimuli. It is not a general proof for every robot mesh, every rigid object, every
camera pose or physical Quest load. It nevertheless disproves a marker-only
explanation and prevents treating 4B counter agreement alone as proof of current
XR pixel content. Existing non-XR historical evidence retains its original scope.

## Source-backed mechanism, not a proven root cause

Pinned `PhysxManager.forward()` updates articulation kinematics and Fabric before
presentation. With Fabric enabled, normal USD pose synchronization is disabled.
The XR experience independently enables asynchronous app rendering while
Replicator asynchronous rendering is false. These separate paths explain why
USD/material-only tests cannot establish physical-transform phase. The observed
native-geometry lag is now measured directly; the exact responsible queue/handoff
has not been isolated by a settings ablation.

| Pinned file | Relevant lines | SHA-256 |
|---|---|---|
| `source/isaaclab_physx/isaaclab_physx/physics/physx_manager.py` | 490–496, 860–893 | `a20f98c841ea031329d0d083303e1fb4c84cb13a7ba3f4cc6bbeee028302bd35` |
| `source/isaaclab/isaaclab/sim/simulation_context.py` | 780–846 | `c3c17f084bc21ddfd80649f8179a6aa916d857a1dcaa1cc1c7f2b7c3945936b2` |
| `apps/isaaclab.python.xr.openxr.kit` | 21–25 | `313ef3c9b47596ecbaec73e4e94152a1905a6e89d1abece898fdd541bd3542b6` |

CodeGraph warned that its index belonged to another worktree; current on-disk
sources in the assigned checkout and pinned installation were therefore inspected
directly. No index or SDK source was changed.

## Commands and exact source identities

All commands ran from the assigned checkout. GPU launches used the existing
installed environment through the canonical launcher. The first two commands
used temporary import hooks; their exact source bytes and recorded inner argv are
retained so reproducibility does not depend on recovering disposable files.

```sh
env PYTHONPATH=/tmp/vr4p5-phase-hook VR4P3_OUTPUT=/tmp/vr4p5-phase-xr VR4P3_CONTENT=1 OMNI_KIT_ACCEPT_EULA=Y ISAACLAB_CXR_ACCEPT_EULA=1 ./run-vr diag --xr-smoke --state-root /tmp/vr4p5-phase-state --max-control-steps 120 --performance-warmup-steps 60 --performance-window-steps 60 > /tmp/vr4p5-phase-xr-launch.log 2>&1

env PYTHONPATH=/tmp/vr4p5-phase-hook VR4P3_OUTPUT=/tmp/vr4p5-phase-xr2 VR4P3_CONTENT=1 OMNI_KIT_ACCEPT_EULA=Y ISAACLAB_CXR_ACCEPT_EULA=1 ./run-vr diag --xr-smoke --state-root /tmp/vr4p5-phase-state --max-control-steps 100 --performance-warmup-steps 60 --performance-window-steps 60 > /tmp/vr4p5-phase-xr2-launch.log 2>&1

python3 docs/experiments/20260921_vr_architecture_bakeoff/launch.py phase --mode xr-smoke --ticks 100 --warmup 30 --state-root /tmp/vr4p-audit --output /tmp/vr4p5-phase-durable-xr > /tmp/vr4p5-phase-durable-xr-launcher.log 2>&1

python3 docs/experiments/20260921_vr_architecture_bakeoff/launch.py phase --mode smoke --ticks 100 --warmup 30 --state-root /tmp/vr4p-audit --output /tmp/vr4p5-phase-durable-no-xr > /tmp/vr4p5-phase-durable-no-xr-launcher.log 2>&1

python3 docs/experiments/20260921_vr_architecture_bakeoff/launch.py phase --mode xr-smoke --ticks 100 --warmup 30 --state-root /tmp/vr4p-audit --output /tmp/vr4p5-phase-reference-xr > /tmp/vr4p5-phase-reference-xr-launcher.log 2>&1
```

| Attempt | Probe SHA-256 | Exit |
|---|---|---:|
| Failed resolver | `c332cf4a3b0c69854429a2f60710cc7292f21ceddb2254ef55f8685e77945b1e` | 1 |
| Invisible sphere | `b625268041703b5b66d36be4940a541bf12e6a67ff59e3a21fa386504e00ee41` | 0 |
| Durable XR | `54339e17010a31ecd60635e5c6485a7fe3e116d70251355234a75751b895fb79` | 0 |
| Durable no-XR | `54339e17010a31ecd60635e5c6485a7fe3e116d70251355234a75751b895fb79` | 0 |
| XR image references | `c5d0e4c5159422b1e6ed5b9030d444412528cd0b01c3424d3e2f766b5cb4536e` | 0 |

Exit zero is successful experiment execution, not acceptance of current-state
camera alignment. All three durable launch directories contain exact source
snapshots and launch hashes. The prototype passed syntax compilation and the
final reference trial executed the tested source above; no canonical promotion
or physical qualification follows from these checks.

## Retention

The assembled retention directory is `/tmp/vr4p5-phase-retention`, pending the
parent bake-off's durable outer-archive preservation and registration. It contains
five attempt directories, old hook sources, all three durable source snapshots,
all phase arrays/statistics and representative PPMs, launch stdout/stderr and GPU
samples where collected. Each attempt's `runtime/` directory retains its original
`run_manifest.json`, generated `runtime.yaml`, `performance.jsonl`, `stdout.log`
and `result.json` when one existed. `locator-map.json` retains the exact original
paths and inner argv; `sha256.json` records copied-byte integrity hashes. The Kit state,
shader caches and unrelated experiment outputs are excluded. Missing physical
observations are not synthesized.

The first launch spent several minutes compiling shaders in a new isolated state
root. This startup time is not a phase measurement or steady-state performance
result. Later launches used existing shader caches. XR shutdown logs contain the
upstream `xrWaitFrame` validation warning; final completed trials still returned
zero and preserved their results. No headset comfort claim is made.
