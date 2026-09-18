# Integration result

User-authorized integration on2026-09-18, branch `integration/kit1103-preview`, based on demo60a2786. Shared independent checkout: `/data/vla-infrastructure/robosyn-kit1103`. The existing installations, accepted environment selection and original demo checkout were not upgraded in place. Launch/rollback instructions are in [README.md](README.md).

**Automated integration verified; physical Quest acceptance remains pending.** The operator was unavailable. Launching under a separate Linux UID was tested using a disposable container and its own CloudXR service, with the shared SDK mounted read-only and the original user's home absent. This proves the tested file/cache/runtime ownership path, not a physical headset connection from a colleague's account.

# Exact topology

| Element | Authoring / selection |
|---|---|
| World geometry | Unpartitioned/shared; existing partitioned world Gprims are rejected at bind |
| Each preview draw system | `primvars:omni:scenePartition = vla_xr_preview`, constant, on its concrete `/ui/draw_system_N` root in the session layer |
| Left/right wrist and scene cameras | `omni:scenePartition = vla_sensor_world` on all3 camera prims |
| XR world camera | Unassigned spectator; `showAllPartitionsByDefault=true` |
| Global switch | `/renderer/scenePartitioning/enabled=true` |
| Lab automatic per-environment partitioning | Disabled on these CameraCfg renderer configs; explicit demo topology owns selection |

Actual full-demo panel roots were `/ui/draw_system_0`, `_1`, `_2`. The report retains all authored paths separately from currently active paths (empty after normal shutdown). Sensor paths:

```text
/World/LeftPiper/Geometry/world/base_link/link1/link2/link3/link4/link5/link6/flange_link/gripper_base/S1WristCamera
/World/RightPiper/Geometry/world/base_link/link1/link2/link3/link4/link5/link6/flange_link/gripper_base/S1WristCamera
/World/RobosynDemo/SceneCamera
```

Creation/show calls public `XRSceneView.run_update()` to materialize its draw system, authors the partition before the next render, then validates. Hide/close unregisters that destroyed resource; show/recreation binds its replacement before rendering. Missing camera/root tokens or disabled settings raise instead of silently falling back. A stage replacement requires restarting/rebuilding the session.

The removed graph edge is `preview geometry -> sensor render collection`. Each sensor selects `vla_sensor_world`, preview is `vla_xr_preview`, and unpartitioned world geometry remains shared. Texture readback and preview publication still use the existing upstream Camera/SceneUI pipeline. `create_image_source -> None` remains a cache/lifecycle choice and does not provide isolation.

**Important integration finding:** tagging only the persistent `/ui` ancestor failed despite correct-looking USD inherited values. All3 sensors saw the marker from frame4; camera0 had22919 marked pixels in both raw and RGBA. That implementation was discarded. The retained implementation explicitly tags each concrete draw system, as in the qualified PoC. A separate early test stopped on a correctly triggered assertion when a closed panel was still registered; registration lifecycle was fixed, then retested.

# NVIDIA and source evidence

- [RTX Scene Partitions](https://docs.omniverse.nvidia.com/materials-and-rendering/latest/cameras.html#scene-partitions): geometry primvars, camera selection, shared unpartitioned scene.
- [Kit110.3 release notes](https://docs.omniverse.nvidia.com/dev-guide/latest/release-notes/110_3.html): OMPE-94170 and the spectator-camera default setting. Source semantics alone did not validate the `/ui` shortcut; pixel tests rejected it.
- [Pinned Isaac Lab source](https://github.com/isaac-sim/IsaacLab/tree/ae37b028ea415c91ea2bc32609efcd759ed2b974): Camera, renderer config, camera-feed lifecycle and `session_lifecycle.py` per-user CloudXR launcher.
- [IsaacTeleop CloudXR](https://nvidia.github.io/IsaacTeleop/release/1.4.x/references/cloudxr.html): upstream runtime/session setup. The no-client test uses upstream `cloudxr-standalone.env` (emulated Quest3); normal interactive launch retains `cloudxrjs-cloudxr.env` (`auto-webrtc`).
- [NVIDIA ground asset](https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/6.1/Isaac/IsaacLab/Environments/Grid/default_ground_plane_checker_v1/default_ground_plane.usda): unchanged local mirror plus two relative textures; SHA-256 verified at launch. This removes an observed OmniClient cold-download failure under the container account. It does not replace geometry or alter the SDK.

Installed `XRSceneView.get_base_path`, `system_path`, `run_update`, UsdGeom primvars and camera attributes provide the authoring boundary. Access to the existing presenter's `_container` remains a pinned Python adapter dependency; no native/private ABI, compositor upload hack or custom XR protocol was introduced.

# Runtime evidence

All bulk evidence is outside git, under `/data/vla-infrastructure/isaac61_qualification/integration-users`. [evidence.json](evidence.json) registers exact paths, hashes, source/runtime records and results. Only3 representative PNGs are included in this report directory.

| Test | Result |
|---|---|
| Positive control,100 frames ×3 | Preview marker appears in raw/RGBA at frame4; detector is sensitive to this presentation |
| Integrated partitions,3000 frames ×3, live feeds | Zero marker pixels in raw/RGBA across9000 sensor frames; world reference objects detected in every frame |
| Motion/lifecycle | Camera poses change every frame; panel parent movement/teleports;11 panel recreations; hide/show;4 simulation resets |
| Full PIPER demo, target,300 control steps | PASS, all300 bimanual frames valid and strictly advanced;3 feed sources,903 publications; XR session started,299 action frames; reset/display/backdrop/recenter checks pass; exit0 |
| Full PIPER demo, rollback,300 steps | PASS on Sim6.0.1/Kit110.1.2,2 feeds,602 publications;300 valid/advanced bimanual frames; XR started; exit0 |
| Independent UID60961 | PASS: own home/CloudXR, read-only SDK,3 cameras/feeds,60 steps,183 publications,59 XR action frames, session required and started; exit0 |
| Core tests |82 passed,23 skipped |
| Target teleop tests |23 passed (the tests skipped by the core environment) |

The first successful integrated stress run is `uid-1006/regressions/1789724489593237098-partition`. Witness cameras observed the marker in2828/2831/2836 frames; intentional hidden intervals and some framing/startup frames explain why this is not3000. Sensor world-reference detection is3000/3000 for every camera. Witnesses are diagnostic render products, not physical headset evidence. The final source-pinned repeat `1789725240749949366-partition` also passed3000×3 with zero raw/RGBA detections and9000/9000 world witnesses. Deliberately corrupted camera token, panel token and global switch were all rejected by the guard. A separate JSONL analysis recomputed these counts and verified source hashes against the final files; registered in evidence.json.

Representative same-frame views: [sensor without preview](evidence/partition_sensor_frame2999.png), [witness with preview](evidence/partition_witness_frame2999.png). [Positive-control sensor at frame4](evidence/control_sensor_frame4.png) contains the presentation marker. These screenshots supplement per-frame programmatic counts.

# Multi-user behavior

`run-vr` selects one of two pinned SDKs without package installation. Code/SDK/assets live under shared `/data`, with no operational reference to `/home/ebulochkin`. Per-user Kit portable-root, XDG config/cache/data, temporary files, CUDA/Warp caches, asset conversion and reports belong to the caller. Mismatched `HOME`, foreign-owned state, state-root symlinks and in-repository state are rejected. Inherited runtime manifest/IPC paths are cleared. Git trusts only the specific verified shared checkout per command.

`auto` uses upstream `~/.cloudxr` for the caller and refuses to take over occupied standard port48322. `existing` accepts only the caller's runtime directory/manifest. This is sequential multi-user operation on standard ports, not simultaneous operators sharing one server. No colleague home, permissions or existing service was changed. The temporary test account/container was removed after retaining its evidence.

The first auto-webrtc no-client run correctly lacked a headset/session. The test launcher now explicitly uses upstream emulated Quest3 for `--xr-smoke` and requires a session; a successful scene-only run cannot silently count as XR-session verification. Normal physical launch still requires real tracking.

# Performance and limits

Sequential300-step full-demo measurements: legacy2 feeds **5.336 control Hz**; target3 feeds **6.121 control Hz**. These are simulation control-loop rates, not display or headset FPS; they do not establish30Hz teleop acceptance. No concurrent qualification renderer ran during these two loops. No material slowdown was seen in this comparison. Extra scene preview reuses an already-existing camera render product; only presentation/upload work is added.

No physical head/controller movement or physical Quest presentation has been verified in this integration. Driver580.159.03 was already validated by the user and worked in these tests. Hot camera teardown/recreation and XR restart inside the same Kit app retain known upstream lifecycle risks; the integrated operational path restarts the process. A diagnostic run exercising live XR restart logged CUDA copy errors; this is not counted as a passing lifecycle gate. Normal robot reset/hide/show is covered.

The auto-owned CloudXR test logged `XR_ERROR_INSTANCE_LOST` during shutdown after session completion when upstream stopped the runtime before Kit finished polling it. Exit status was0; `process.clean_shutdown` in the existing report schema means process exit status, not an error-free log. This issue is retained as a lifecycle limitation, not hidden or patched with private interfaces.

# Files and rollback

- `run-vr`, `tools/launch_isaac_robosyn_vr_demo.py`, `tools/isaac_demo_launch.py`: SDK selection, exact pins, ownership/preflight, per-user launch state.
- `tools/isaac_preview_partitions.py`: draw-system/camera authoring and fail-closed checks.
- `tools/isaac_robosyn_vr_demo.py`:3rd preview, policy lifecycle hooks, per-user converted assets/local pinned ground asset.
- `tools/run_isaac_s1.py`, `tools/isaac_s2_runtime.py`: explicit config selection and pre-render guard; accepted defaults remain available.
- Target YAML configs/environment descriptor: separate from accepted S0/S1/S2 configuration.
- `tools/check_isaac_preview_partitions.py`: isolated detector regression; no robot-control framework. Retains only frame4, last frame, first failure images; all per-frame metadata remains external.
- Tests: per-user isolation and unchanged teleop semantics. The stale recenter config expectation was updated to cover the already-existing sync/motion-barrier fields; recenter runtime behavior was not changed.

Rollback is `./run-vr --stack legacy --hud-on-start`; it uses the legacy interpreter as well as legacy packages/configs, separate caches and isolation=off. This was executed successfully, not only inspected. It also restores the old recursion behavior if a camera sees its preview. The original accepted installation/checkout remains an independent fallback.

# Gate accounting

| Field | State |
|---|---|
| GATE | NONE_EXPERIMENTAL integration; no S2 physical acceptance change |
| REUSED | NVIDIA RTX partitions, Camera, SceneUI/ByteImageProvider, CloudXR lifecycle, teleop/IK |
| PINNED / VERIFIED | Sim6.1.0.0, Kit110.3.0+feature.371399.00c488ae.gl, Lab ae37b028 / package17.0.2, teleop0.9.0 /1.4.98rc1 |
| EXECUTION PROFILE / ENVIRONMENT | isaac_vr_demo, isolated target SDK; legacy SDK selectable |
| CONTRACT CHANGES | None; policy-facing state/action semantics unchanged |
| EVIDENCE ADDED | Registered runtime results, source hashes, pixel counts, separate-UID run, unit results |
| ARTIFACTS ADDED | Reports/scripts/configs,3 PNGs in git; runtime outputs external |
| PROCESSORS / ADAPTERS | Small partition lifecycle/launcher composition; existing control processors retained |
| TESTS | Automated pixel, full-scene, rollback, ownership and teleop checks above |
| HUMAN EVIDENCE | Pending physical Quest run under a colleague Linux account |
| BLOCKERS / REOPEN REASONS | Any leaked frame; missing isolation token; physical tracking/display failure; unacceptable operator FPS; unsupported hot teardown |
| NEXT GATE | Physical Quest acceptance with3 previews, active tracking/teleop and sensor camera aimed at presentation |
