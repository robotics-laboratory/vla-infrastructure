# Production cutover upstream audit

Baseline accepted contract:404d859cbc189e7dc661f2125d59e838ceee69fd. Integration baseline:60eb2605909557dbefd1e5c02db18bfa80c1217d. Migration branch starts from the latter; production checkout remains unchanged pending gates.

CAPABILITY / GATE: scoped S0 Isaac repin/amendment, exact final S1, combined canonical S1 robot/camera + production SceneUI presentation validation; S2 remains unresolved pending physical Quest.

PINNED UPSTREAM CANDIDATES: Sim6.1.0.0/Kit110.3.0+feature.371399.00c488ae.gl, Lab ae37b028ea415c91ea2bc32609efcd759ed2b974 (source17.0.2, RL0.16.3), isaaclab_teleop0.9.0, IsaacTeleop1.4.98rc1/CloudXR6.2.1. Legacy Sim6.0.1.0/Lab913ac53f51b2f8d02c9e121caa4cbdd06262948e retained.

WHAT UPSTREAM ALREADY OWNS: frozen workspace/dependencies, AppLauncher, Camera, PhysX articulation/URDF conversion, teleop lifecycle/ControllersSource, DifferentialIKController, SceneUI camera feed manager/presenter, RTX Scene Partitions. Project owns only PIPER-X edge semantics and pinned presentation adapter.

EXACT REMAINING GAP: REP-01 upstream lock lists editable package versions inconsistent with the clean source; fix only two lock version fields, materialize a new environment and prove a subsequent frozen sync is empty. REP-02 metadata says processorv2 but codev3; synchronize metadata to code and preserve legacy evidence. Canonical batched Camera needs explicit concrete camera paths for the existing preview guard; combined validation must exercise real robot scene and production manager, not only synthetic panels.

PROCESSOR / CONFIG / ADAPTER REQUIRED: no processor semantics change. Locked environment amendment, shared pinned launch selection with explicit legacy rollback, same SceneUI presenter/manager with thin batched feed view, concrete partition path binding and descendant assertions. Bounded integrated validation callback uses production path and records per-frame marker/raw/cache/upload evidence. No alternate camera renderer/IK/XR implementation.

ENVIRONMENT IMPACT: new /data/vla-infrastructure/isaac61_production checkout/environment. Lock-only materialization commit records upstream parent; original source contents unchanged. No in-place upgrade, hidden pip, GateB/core repin, generic environment registry or RPC.

WHY NO PROJECT FRAMEWORK IS NEEDED: upstream implementation/configuration > existing composition > concrete thin adapter. Reuse existing S1 and S2 paths, no new simulator backend.

Code-size re-audit before edits: inherited run_isaac_s1 and demo modules already exceed300LOC. Limit edits to launch/version/evidence and concrete preview binding; move no solver/recorder/runtime ownership locally. New single integration module >300LOC or new affected runtime >1000LOC triggers renewed audit. Test harness code is excluded but must remain concrete and bounded.

References: installed pinned source and previous scoped audit under docs/project/isaac_runtime_repin/20260918 in integration worktree. Historical accepted facts are not overwritten until final evidence supports Isaac-only amendment. No physical success claim is authorized by automated tests.

## Concrete compatibility findings

The pinned `RenderContext.prepare_stage` requires every Camera to use the same
`num_envs`. Canonical wrist Camera has two views; adding a one-view scene Camera
fails with `num_envs 2 vs 1`. The minimal public-config adaptation creates two
identically posed scene views, presents the first, and tags both as sensor views.
The second is not a policy role. This adds one redundant presentation render view
and must be included in performance assessment. No camera source was forked.

The pinned `Camera` has public `reset`, destructor cleanup and private invalidation;
no public `close` for deterministic hot deletion. Camera recreation is qualified
through process restart; reset and preview manager recreation occur in-process.
No private invalidation method is called to claim unsupported hot recreation.

CloudXRLauncher(install_dir=...) is the upstream public lifecycle used to keep
CloudXR files in per-account /data. The launcher-owned runtime is passed to Kit
and IsaacTeleop via their documented environment seam; XR profile is disabled before owner cleanup and Kit fast shutdown. Standalone profile is test-only; physical launch retains cloudxrjs.

REP-02 canonical processor code in the deployed integration is v3, SHA-256
b75f86884e0b2a80886425229aae901ba3aad5fa6d4de2ec86bff8cd41fc053c.
This migration changes its metadata only. The home master is older (v1): publishing
the already prepared integration also brings commits031143d and09c789f's prior
tracking/gripper/speed-slider remediation. These are explicitly distinguished from
new SDK changes and do not constitute new physical S2 acceptance.

## Preview lifecycle blocker found during final combined gate

The second3000-frame trial also had zero sensor leakage but only2706/3000 witness
frames. Repeated destruction/recreation of the UI is not a supported lifecycle:
pinned `omni.kit.scene_view.xr_utils-1.0.2+00c488ae` `ui_container.py` lines35-40 and
69-71 explicitly warn about accumulated SceneView state and instruct callers to
keep containers and use show/hide. Production composition now retains exactly
three upstream panels, uses show/hide while feed managers are recreated, rebinds
partitions on every show, and releases panels once at final shutdown. No renderer,
texture provider, protocol or generic pool/framework was added. Fixed descriptors
and a three-panel upper bound reject layout changes that would allocate more views.
Tests continue to capture every sensor tick with the same zero-leakage requirement.

Installed source: `/data/vla-infrastructure/isaac61_production/env/lib/python3.12/site-packages/isaacsim/extscache/omni.kit.scene_view.xr_utils-1.0.2+00c488ae/omni/kit/scene_view/xr_utils/ui_container.py`.
This concrete failed runtime observation justifies the minimal lifecycle adaptation;
it is not a timing workaround for anti-recursion.

## Owned CloudXR shutdown

A completed smoke left an owned runtime process behind. Installed SimulationApp.close
uses `/app/fastShutdown` and can bypass Python atexit/any statements following close.
The launcher composition therefore requests public XRCore.request_disable_profile,
checks public is_xr_enabled after updates, stops public CloudXRLauncher.stop, then
closes Kit. TeleopSession has already been stopped by the upstream device lifecycle.
A timeout is a failure, not silently accepted cleanup. This is a concrete lifecycle
compatibility fix; no custom XR protocol or second session is introduced.
