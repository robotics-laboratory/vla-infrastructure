# Warp/Newton audit for live PIPER recording

Audited 2026-10-09. Project d5566834d29ef8bb56e4fb62bb324e23e0869100; parent-supplied trusted base beaedfd. Assigned checkout research/live-camera-recording-30hz retained. Installed IsaacLab clean at 0c2e2c64e51922d088b695d72ffe03faa5c6b95d. Exact installed file hashes and browser observation hashes are in `live30-deep-warp.sources.json`. No GPU execution, installs, hardware actions, production SDK changes or project source edits were performed by this agent. One source-guarded probe received AST checking only.

## Practical conclusion

CUDA graphs are a real installed Newton capability, but do not provide a supported wrapper around the current native PhysX/Kit loop. Graphing physics can remove repeated Python/kernel launch overhead; it cannot replay Kit app updates, XR polling, causal transition bookkeeping or renderer CPU waits. The already-installed Newton manager supplies the necessary graph machinery, so a custom simulator framework is unnecessary.

CPU native MuJoCo and GPU MuJoCo-Warp are useful *same-scene lower-bound experiments*, not qualified replacements. Installed MuJoCo does not implement the source solver's joint velocity limits. VBD, Featherstone and XPBD also omit required limit/constraint behavior. A fast benchmark that omits contacts, effective actuator parameters or source objects cannot answer the requested >30 wall-Hz, three live960×600 cameras with physical Quest3. Approximately50 wall-Hz without Quest is the parent's matched configuration screening target; none of the sources below proves it.

## A correction that changes solver selection

The original CPU USD audit found zero **PhysxMimicJointAPI** schemas, but incorrectly treated that as zero constraints for every solver. Actual Newton import produced four constraints and stopped at the guard. Raw `apiSchemas` metadata then established four authored **NewtonMimicAPI** schemas on the two fingers of each arm, referencing gripper with coefficients +0.5/-0.5. Unregistered custom schemas are absent from `GetAppliedSchemas()` in a plain pxr process. See [raw audit](stage-mimic-audit-all.json) and [actual Newton receipt](runs/newton-cpu-authored-mimics.receipt.json).

The corrected probe validates exact follower/leader paths and coefficients, then executes the retained model. CPU Newton/MuJoCo measured 2.9647 ms per four-step tick (337.30 Hz), 27 bodies/820 shapes, 110 final contacts; this is physics-only. Velocity limits remain unsupported, the MIDPHASE workaround is explicit, and custom equality compliance can differ from canonical PhysX with explicit finger targets. VBD/XPBD/Featherstone cannot be treated as drop-in backends for this authored Newton inventory. Four constraints were not added to manufacture the result.

## Installed APIs and constraints

Packages: Warp1.16.0, Newton1.5.2, MuJoCo3.11.0, MuJoCo-Warp3.11.0, IsaacLab17.0.2, isaaclab_newton5.4.1.

| Installed candidate | Relevant capability | Remaining fidelity gap |
| --- | --- | --- |
| Lab NewtonManager | Full decimation×actuators×solver CUDA graph; graph-safe callbacks; RTX-compatible capture | Need explicit field mapping, contact/controller parity and source state/image qualification |
| SolverMuJoCo GPU/CPU | Revolute/prismatic drives, effort limits, armature/friction; actual mimic/equality if authored | `joint_velocity_limit` and `joint_enabled` explicitly unsupported (`solver_mujoco.py:453`) |
| SolverVBD | Graphable rigid contacts and revolute/prismatic drives/limits | No armature, joint friction, effort or velocity limit, target mode, equality/mimic in1.5.2 (`solver_vbd.py:131`) |
| SolverFeatherstone | Reduced-coordinate articulated dynamics, armature/drives | Effort/velocity limits, joint friction, equality/mimic unsupported (`solver_featherstone.py:96`) |
| SolverXPBD | Graphable rigid/articulation experiments | Equality/mimic unsupported (`solver_xpbd.py:81`); no evidenced exact drive/contact parity |
| SolverKamino | Closed-loop mechanisms using loop joints | Installed source explicitly ignores equality/mimic/tendon model flags (`solver_kamino.py:1059`); not an automatic mimic replacement |

Native implicit solver velocity bounds cannot generally be reproduced by clipping a desired position/velocity or explicit PD torque: contact forces can accelerate a joint independently of its target. An external clamp also changes solver/contact dynamics. Therefore retaining those bounds needs an upstream supported feature, or explicit qualification of changed semantics; setting a populated but ignored Newton field does not solve it.

### Why graphing the existing PhysX loop is not supported

Warp graph capture records supported device operations, not arbitrary Python execution. PhysX simulation remains native simulate→fetch_results; [Omni Physics describes fetchResults as a blocking completion/write boundary](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/latest/dev_guide/physics_umbrella/physics_umbrella_runtime.html). Replaying only captured CUDA kernels would omit the native simulation call, CPU transition counters, input/action updates and app/XR lifecycle. No primary source or NVIDIA forum search produced a supported current PhysX whole-tick graph recipe. This is a negative search result, not proof that every future PhysX implementation cannot graph.

For pure Warp kernels, [Warp1.16's Launch objects](https://nvidia.github.io/warp/v1.16/user_guide/runtime.html) avoid Python argument preparation but do not remove GPU driver launches. This optimization is **already present** in installed `_WarpLaunchCache`: PhysX articulation data uses `_read_launch_cache`, and actuator collection uses `_launch_cache`. Recommending cached launch objects again is not new work. The parent's guarded implicit-once/lazy-acceleration experiment targets remaining repeated computation and is not duplicated here.

### Newton already has an RTX-compatible graph path

`NewtonManager._capture_relaxed_graph` (`newton_manager.py:2422`) prewarms scratch allocations, disables Python GC during capture, creates a nonblocking CUDA stream, begins RELAXED capture externally, then registers it with Warp's `capture_begin(external=True)`. Registration is necessary for `mujoco_warp` conditional loops to emit graph nodes instead of synchronizing. The manager defers capture until the first step when RTX is active, and captures the full decimation loop when all actuators are graph safe. Use this installed upstream implementation; a hand-written ctypes clone adds risk without a demonstrated gap.

The bridge's remaining synchronization is concrete: `sync_transforms_to_usd` writes body poses into Fabric and calls `wp.synchronize_device` (`:779`) before hierarchy propagation. It only runs once per rendered frame, already avoiding per-physics-step sync. Removing that wait without a CUDA→Fabric/RTX completion dependency can publish stale transforms; a graph cannot erase the need for ownership/dependency. Snapshot publication or a verified shared-stream/event boundary is the appropriate design experiment.

CPU APIC graphs are not a wrapper around native `mujoco.mj_step`: a Python call to the C solver would execute at capture time, not become a replayed supported Warp operation. The prepared probe graphs only MuJoCo-Warp CUDA, and keeps native CPU eager.

## Specific correctness findings from primary issue research

1. [Newton#3805, opened2026-08-05](https://github.com/newton-physics/newton/issues/3805): postcompile inertia orientation updates can leave native CPU MuJoCo midphase BVHs in their old frame and silently omit real contacts. Installed1.5.2 `_sync_mjw_inertias_to_mjc_cpu` at4395 still has the reported pattern and contains no MIDPHASE/BVH correction. Reported workaround is disabling `mjDSBL_MIDPHASE`, retaining narrow-phase contact detection. This is recorded explicitly by the CPU probe. Contact parity must still be checked; never accept the faster missing-contact path.
2. [Newton#3128, opened2026-06-10](https://github.com/newton-physics/newton/issues/3128): CPU Newton rebuilds `xfrc_applied` from Newton state forces, discarding direct MuJoCo-array writes. Apply forces through the correct owning interface. This is relevant to future interactive grasp/force probes, not evidence against the current unforced trajectory.
3. [IsaacLab#5064, opened2026-03-19](https://github.com/isaac-sim/IsaacLab/issues/5064): older beta state/velocity writes used display/default buffers rather than live solver state. This report is version-specific, not established on installedEA. It motivates explicit buffer ownership tests and avoiding writes to `model.joint_qd` as if it were live state.
4. [MuJoCo#3435, opened2026-07-27](https://github.com/google-deepmind/mujoco/issues/3435): JAX ordering between BVH refit and rendering was insufficient because mutable renderer state did not create a graph dependency. Even a GPU renderer needs a verified refit→render dependency. Our direct Warp/OVRTX route does not use JAX, so this issue is guidance, not its measured defect.
5. [Newton#4220, September2026](https://github.com/newton-physics/newton/issues/4220): current development upgrades regressed large-scene initialization. This concerns startup, not sustained wall-Hz, and reinforces measuring isolated upgrades rather than replacing production dependencies.

In [Newton discussion639, maintainer response2025-09-02](https://github.com/newton-physics/newton/discussions/639), Miles Macklin explains that small world counts can lose to CPU engines because of GPU fixed overhead; optimization emphasized thousands of RL worlds. That supports testing nativeCPU for one bimanual scene. It does not establish any speedup on PIPER or the present GPU. [The GA roadmap](https://github.com/newton-physics/newton/discussions/2176) describes simplified high-throughput tiled rendering and ongoing low-latency work. Batched world-steps/s figures must not be substituted for single live-scene action/camera wall-Hz.

Current [Newton main changelog](https://github.com/newton-physics/newton/blob/main/CHANGELOG.md) contains newer graph-friendly controllers, implicit actuator response and FK/collision optimizations. These are candidates for an isolated version experiment; they are not installed1.5.2 APIs or transferable measured percentages. Search also found a workflow mention of VBD mimic convergence PR4238; exact PR fetch failed, so that mention is not implementation evidence.

## Render bridging and scientific state

Installed Newton `ViewerRTX._update_ovrtx_transforms` maps an OVRTX CUDA transform binding, obtains a Warp mat44d view with DLPack, writes all shape transforms in one kernel, and unmaps using the producing CUDA stream (`viewer_rtx.py:1628`). This is concrete upstream code demonstrating GPU transform publication without CPU matrices. It is a useful reusable mechanism if Newton is selected; it does not by itself produce three cameras, preserve the original USD/MDL scene or provide XR. ViewerRTX rebuilds a viewer stage from model visuals and is not an automatic replacement for the original renderer.

The parent's exact-world OVRTX snapshot path is preferable for preserving the current PhysX model while trying render overlap. Applying Newton solely to make OVRTX work unnecessarily changes contact physics. Warp's simplified tiled raytracer may establish a throughput ceiling, but its appearance pipeline is not the retained RTX camera pipeline. Do not call resulting pixels unchanged ZED RGB because resolution/intrinsics match.

For any delayed images, preserve source observation ID, source simulation time, exact camera transforms/intrinsics, scene generation and original deterministic14-value labels; join all three camera outputs against that source ID. A bounded one/two-control image delay changes delivery time, not the observation's identity. Immutable state slots and explicit rendering completion fences are required. Repeated stale buffers or asynchronous counters are not unique live samples.

## Prepared microprobe and recommended use

`/tmp/live30-newton-probe.py` plus `.preimages.json` is184LOC, exact-source/package guarded and AST PASS. No model/GPU initialization has been executed by this agent. Parent invokes the declared Isaac interpreter with:

```sh
/data/vla-infrastructure/isaac61_production/env/bin/python /tmp/live30-newton-probe.py --stage /data/ebulochkin/vla-runtime/live30-20261009/piper-inputs/stage_snapshot.usd --stage-audit /tmp/live30-deep-ovphysx-stage-audit.json --out /tmp/live30-newton-cpu-run --backend cpu --allow-execute
```

Use fresh output directories/processes for cpu, cpu-direct, cuda-eager and cuda-graph. The CPU default records the MIDPHASE-disabled workaround. `--midphase native` is only a paired defect/performance ablation. GPU modes use explicit device selection. Every timed group is four1/120-second steps, contacts enabled, no fixed-link collapse or omitted source root. Default body/joint readback is included in timing; `--readback none` exposes the lower bound separately. No cameras, XR, dynamic source input or recorder is included.

`cpu-direct` bypasses Newton conversions while using the same compiled MuJoCo model and fixed initial controls. Comparing it with `cpu` estimates Newton wrapper cost; it does not provide equivalent live Newton outputs or action handling. The model manifest, effective gains, imported MJCF, exact hashes, initial/final states, per-tick timing and failures are retained. Import inventory and finite final state are necessary checks, not contact/optical/label qualification. Dynamic closed-loop target equivalence and effective velocity bounds remain unverified/unsupported.

The experiment is worth doing if it can rule out a physics-latency branch cheaply. Only if a candidate preserves required physical behavior and has sufficient single-scene budget should it be composed with shared original XR/control/recording. First compare contact/grasp responses and joint limits, then allthree source-bound decoded camera streams, then matched activeXR/noQuest≈50Hz, then explicitly authorized physicalQuest>30Hz. No task/runtime/gate selection should change merely because this lower-bound microprobe is fast.

## Provenance, registration and limits

These are temporary research artifacts under /tmp, owner vr.performance, kind experiment, mutable working audit. Parent may consolidate them into the existing 20261009_live_camera_recording_30hz/deep_research bundle and index retained files. No evidence/artifact registry or gate bindings were altered by this agent. No S2/D1 acceptance, physical success or measured impact is claimed. Browser response hashes identify saved text observations, **not raw upstream HTTP source bytes**; installed source hashes are exact bytes. Failed URL/capture searches and egress denial are retained in the ledger. No skills were installed and no model/framework abstraction was added.
