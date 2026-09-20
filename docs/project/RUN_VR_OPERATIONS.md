# Current Quest -> Isaac VR operations

## Purpose

**PRIMARY OPERATOR ENTRYPOINT: `./run-vr`.** The current operator composition is
**run-vr + RoboSyn demo overlay + final Isaac61 stack**. Use this guide for the
current Quest 3 demo/teleop workflow, from your own project checkout.

PRIMARY OPERATOR PATH does **not** mean ALREADY ACCEPTED GATE CONFIG. The selected
overlay remains `EXPERIMENTAL_TEST_ONLY_NOT_A_GATE`; its slider remains
`DEMO_ONLY_CANDIDATE_REQUIRES_PHYSICAL_RETEST`. Final physical S2 re-acceptance must
test this exact default composition before promotion. This simulation workflow
does not open a physical PIPER interface or record a D1 dataset.

## Quick start

Prerequisites: the pinned shared SDK/assets are installed and readable, your Linux
account has writable `/data/<username>`, and you have accepted the NVIDIA Isaac Sim
and CloudXR EULAs. In your own login shell:

```sh
cd ~/vla_infrastructure
export OMNI_KIT_ACCEPT_EULA=Y
export ISAACLAB_CXR_ACCEPT_EULA=1
./run-vr
```

In the headset open the configured [NVIDIA release-1.4.x client](https://nvidia.github.io/IsaacTeleop/client/release-1.4.x/),
select **Isaac Lab**, press **Reset to defaults**, then select **Quest 3** and
connect to this host. These settings live in headset browser cache/localStorage;
the host prints the setup instructions but does not apply them to the browser.
Wait for both controllers to track. Preview panels start hidden; press X to show
them. Follow the [current physical acceptance worksheet](GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md)
when collecting acceptance evidence.

## What it launches

```text
./run-vr
  -> /data/vla-infrastructure/isaac61_production/env/bin/python
  -> tools/launch_isaac_robosyn_vr_demo.py
  -> generated runtime.yaml
     + configs/isaac61_s2_runtime.yaml
     + configs/experiments/robosyn_vr_demo.yaml
  -> tools/run_isaac_s1.py --robosyn-vr-demo --s2-teleop
  -> tools/isaac_robosyn_vr_demo.py::run_robosyn_vr_demo
  -> DemoRuntime
  -> env.experiment_runtime
  -> tools/isaac_s2_runtime.py::run_s2
```

The launcher generates `runtime.yaml` from `configs/isaac61_s1_runtime.yaml`,
with private per-user generated asset paths. It passes the base S2 config through
`--s2-config`; the demo composer loads the RoboSyn overlay and attaches its
`DemoRuntime` to the environment. This is runtime composition, not a recursive
YAML merge. Launch provenance is saved before the child process starts.

The default physical, non-smoke command includes `--xr`,
`--s2-cloudxr-profile cloudxrjs`, and `--s2-require-tracking`. It requires tracked
frames from both controllers. Default profile: `dual_cube_to_matching_plates`;
default limit: 18000 control steps (not a wall-clock duration).

## Default stack

`stack = isaac61`, runtime `/data/vla-infrastructure/isaac61_production/env`.

| Component | Selected pin |
|---|---|
| Isaac Sim | 6.1.0.0 |
| Kit | 110.3 |
| Isaac Lab | 17.0.2 |
| Isaac Lab frozen checkout | `0c2e2c64e51922d088b695d72ffe03faa5c6b95d` |
| isaacteleop | 1.4.98rc1 |
| isaaclab_teleop | 0.9.0 |
| CloudXR | 6.2.1 |
| Preview isolation | `scene-partitions` |
| Preview cameras | `3` |

Exact environment and materialization records are in
[the final environment specification](../../configs/environments/isaac1103/ENVIRONMENT.yaml).
The selected processor revision is `piper_x_isaac_s2_bimanual_relative_v3`.

## Config precedence

[Base S2](../../configs/isaac61_s2_runtime.yaml) supplies environment checks,
processor revision, clutch, gripper and tracking semantics.
[The operator/demo overlay](../../configs/experiments/robosyn_vr_demo.yaml)
supplies the demo scene, presentation and selected sensitivity. `run_s2()` uses:

```python
sensitivity = (
    experiment.sensitivity if experiment is not None else config["processor"]["sensitivity"]
)
```

For `./run-vr`, `experiment` is the attached `DemoRuntime`. Effective sensitivity
is **slider**, using each controller's own `thumbstick_x`, independently per arm:

| Thumbstick position | Translation scale | Rotation scale |
|---|---:|---:|
| -1 (left) | 2x | 2x |
| 0 (center) | 4x | 4x |
| +1 (right) | 6x | 6x |

Interpolation is continuous, piecewise linear and clamped. Changing the slider
changes the gain on relative motion; it must not jump the target when the
controller pose is stationary. Physical usability and continuity remain retest items.

**BASE / GENERIC S2 LAUNCHER: `tools/launch_isaac_s2.py`.** Without `DemoRuntime`,
the same processor selects the base config's per-arm thumbstick-click toggle:
normal 2x / precise 0.5x. These are two selected configurations of one processor.
The generic launcher remains supported for base S2, tests and smokes; it is not
deprecated and is not the primary operator workflow. The contract's
`execution_profiles.isaac_vr_record.command` and `teleop.isaac.resolved_implementation`
still describe this base path; this documentation step does not promote the overlay
or change those machine-readable facts.

## Current controls

| Input | Current operator behavior |
|---|---|
| Left/right controller grip pose | Relative translation and rotation drive the corresponding simulated arm through upstream retargeting and differential IK. Test all axes/signs for both hands. |
| Each horizontal thumbstick | Independent continuous 2x–4x–6x translation/rotation slider. |
| Each squeeze > 0.5 | Clutch that arm: hold Cartesian intent while moving the controller; release discards the first delta and rebases. |
| Each analog trigger | Independent gripper: 0 fully open (0.1 m), 1 fully closed (0 m), linear intermediate aperture; reset aperture 0.05 m. |
| R3 (right thumbstick click) | One rising edge recenters through upstream teleport-to-view at the demo scene-camera pose. Motion is held on request and references rebase on the following control frame; later transform changes rebase again. It does not reset the scene. |
| X (left primary) | Show/hide all three preview panels on a rising edge; camera acquisition continues. |
| B (right secondary) | Toggle visual backdrop visibility on a rising edge; initially visible. |
| Client start/stop | Upstream control-message channel changes teleoperation activity; inactive input holds targets. This is distinct from terminating the host process. |
| Client reset | Reset the demo environment, processor, IK and upstream references; require fresh per-arm rebase. X/B visibility is preserved. |
| Host Ctrl-C | Request controlled process shutdown and retain available result/performance output; interruption exits 130 and is not a PASS claim. |

Teleoperation is active by default once the session is running. Missing/invalid
tracking holds the affected arm and clears its relative reference; the valid
other arm remains usable. Recovery uses the first valid pose as a zero-motion
baseline. Disconnect holds both arms; reconnect must rebase without stale replay.

## Cameras / preview

The three feeds are **left wrist**, **right wrist**, and **scene preview**
(`demo_scene`). The third camera is preview-only, not a canonical D0 policy input.
All are configured at 640x480 and 30 Hz simulation time; this is not a measured
30 Hz wall-time guarantee. X changes panel visibility, not sensor acquisition.

Scene Partitions keep presentation panels visible to the headset while excluding
them from sensor views, preventing camera/preview recursion. Keep the default
`preview_isolation=scene-partitions` for current acceptance. A missing partition
fails closed. Restart the process for camera teardown/recreation or XR restart.

## Outputs

The launcher prints `Demo output:` and creates:

```text
/data/<Linux username>/vla-runtime/isaac-isaac61/runs/<UTC stamp>-<profile>-hud-off/
```

`--hud-on-start` changes the suffix to `hud-on`. A private, absolute, external
`--state-root` overrides the state root. Expected artifacts:

- `launch_manifest.json`: project commit/branch/tracked status, selected source
  hashes, actual child command, stack/package pins, preview options and host paths.
- `runtime.yaml`: generated runtime config.
- `result.json`: runtime report and launcher process/shutdown information.
- `performance.jsonl`: control-step timing records.
- `stdout.log`: child stdout/stderr.

Early failures can leave an incomplete set. `--dry-run` still checks pins and
writes manifest/config but starts no simulation and produces no runtime result.
Optional `--capture-preview-evidence` writes bounded PPM/metadata under
`camera_feed_diagnostics/`; `--scene-preview /absolute/path/outside/repo.png`
saves a scene image. Neither option is required for the default launch.

For acceptance retain the exact `./run-vr` invocation separately: the manifest
stores the expanded child command. Also retain/hash both source configs, generated
config, manifest, processor source/revision, exact Git commit and environment/package
pins. The manifest's selected source hashes alone are not a complete acceptance
bundle. See the worksheet for the full record.

## Alternative stack

```sh
./run-vr --stack legacy
```

This is a rollback/debug path, not the current target: it selects the preserved
Candidate B interpreter `/data/vla-infrastructure/envs/isaac-s1-candidate-b`,
Isaac Sim 6.0.1.0 / Lab 16.4.0 / isaaclab_teleop 0.8.0, two previews,
isolation `off`, and separate `isaac-legacy` state. The RoboSyn overlay and processor
v3 remain selected; rollback does not restore historical controller semantics.
The old stack does not provide the current anti-recursion guarantee.

## Troubleshooting

- **Port 48322 occupied:** its owner must stop the CloudXR server normally.
  `--cloudxr-mode existing` is only for your own server with readable manifest and
  current-UID IPC under the selected state root's `cloudxr/`; do not reuse another
  user's runtime.
- **EULA failure:** after accepting the licenses, set the two variables in Quick
  start in the same shell. A pin check may fail before the EULA check.
- **Wrong stack:** inspect printed command and `launch_manifest.json`; default is
  `isaac61`, explicit `--stack isaac61` selects it. Remove a legacy override.
- **Dirty checkout / pin mismatch:** the shared Isaac Lab, model and RoboSyn
  checkouts must match their pins and be clean; frozen workspace/assets/packages
  are checked. Restore the intended pinned installation; do not patch shared SDKs
  or install replacement packages. Project tracked dirt is recorded in the manifest;
  use a clean exact project commit for physical acceptance.
- **Client setup:** use the exact versioned URL above and reset its Isaac Lab /
  Quest 3 settings; host environment variables do not reset browser localStorage.

For base S1/S2 checks and SDK materialization see
[runtime maintenance operations](migrations/20260918_isaac1103/OPERATIONS.md).
Historical launch references are classified in [the documentation audit](RUN_VR_DOCUMENTATION_AUDIT.md).
