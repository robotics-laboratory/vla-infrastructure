# PIPER-X VR Teleoperation & Dataset Collection

Collect bimanual robot demonstrations in NVIDIA Isaac Sim using a Meta Quest 3,
then turn them into LeRobot datasets for training vision-language-action models.

The project connects two AgileX PIPER-X arms, VR controllers, simulation and
dataset tooling. Its current workflow is **Quest → Isaac teleoperation → recorded
state and actions → offline RGB → LeRobotDataset v3**. The repository also contains
a LeRobot plugin for physical PIPER-X arms and the shared robot/data definitions
needed to carry demonstrations between simulation and hardware.

## What you can do today

- **Teleoperate two simulated PIPER-X arms.** Quest controllers drive the arms
  through relative pose commands and Isaac Lab inverse kinematics, with gripper,
  clutch, recenter and reset controls.
- **Collect demonstrations.** Start and stop recording from the controllers,
  save or discard a demonstration, and classify it as success, failure or
  incomplete. Tracking interruptions produce separate technical segments within
  the same demonstration.
- **Replay recorded states and render camera images offline.** Each recorded
  transition retains its observation, action and successor identities. Replay
  restores the recorded scene state without advancing physics.
- **Build and inspect LeRobotDataset v3 outputs.** Conversion joins RGB to the
  recorded observations and checks every dataset row and video stream.
- **Diagnose performance and data integrity.** The runtime provides control
  timing, recording diagnostics, source manifests and strict artifact checks.

The default task is `dual_cube_to_matching_plates`: move two colored cubes onto
their matching plates. Observations use two wrist cameras and one scene camera,
using native ZED optics at 960×600. RUN, DIAG and RECORD use F,F,F,T rendering
from startup: one render tick per four physics substeps. Simulation runs at
120 Hz physics with 30 Hz logical control;
these settings do not guarantee 30 Hz in wall time.

## How recording works

During recording, the system captures native/Fabric scene state and post-IK,
preclip training actions through NVIDIA Episode Recorder. Training labels use
degrees/millimetres; the applied clipped native command in radians/metres and
its residual/saturation are stored separately. Dataset camera rendering and live
RGB reads are suspended. Four physics steps use **F,F,F,T** rendering: one final
render/Kit pump per control transition, retaining the XR presentation path.

After recording, the saved states are replayed to render the three camera views.
Images are matched to immutable observation identities before conversion to
LeRobot format. This keeps dataset image rendering out of the teleoperation loop
and preserves the pairing between what the policy observes and its action.

```text
Quest controllers → relative pose processing → IK → simulated PIPER-X
                                                    │
                                           state/action recording
                                                    │
                                   strict replay → three-view RGB
                                                    │
                                            LeRobotDataset v3
```

A saved demonstration is not automatically admitted for training. Source
verification, conversion checks and physical qualification are separate steps.

## Getting started

### Requirements

The Isaac runtime targets Ubuntu 22.04/24.04 on an RTX workstation. The pinned
environment specifies at least 16 GB VRAM and 32 GB RAM; testing has used an
RTX 4090. Physical VR operation requires a Quest 3, the CloudXR client and
accepted NVIDIA Isaac Sim/CloudXR EULAs.

Core tooling uses Python 3.12.13, `uv` and LeRobot 0.6.1. Isaac runs in a separate
pinned environment with Isaac Sim 6.1, Kit 110.3 and Isaac Lab. Shared SDKs and
assets live under `/data`; runtime state and recordings default to a private
directory under `/data` for each account. Explicit private output paths outside
the checkout are also supported. Keep generated datasets outside the checkout.

Install the core environment:

```bash
uv sync --frozen
```

This installs dataset and development tooling. Set up the Isaac environment
using the [Isaac installation guide](docs/project/migrations/20260918_isaac1103/OPERATIONS.md)
and [pinned environment specification](configs/environments/isaac1103/ENVIRONMENT.yaml)
before launching VR.

### Launch the scene

Run from the repository root. After accepting the NVIDIA EULAs:

```bash
export OMNI_KIT_ACCEPT_EULA=Y
export ISAACLAB_CXR_ACCEPT_EULA=1

./run-vr --dry-run   # Check the installed environment and selected assets
./run-vr            # Start Quest teleoperation
./run-vr diag       # Start the same runtime with diagnostic observers
```

The host prints the headset client URL and connection instructions. See the
[VR operator guide](docs/project/RUN_VR_OPERATIONS.md) for headset setup,
controller mappings and runtime options.

### Record a demonstration

```bash
./run-vr record
```

Recording starts in `WAITING`:

1. Press **X** to start.
2. Press **Y** to stop.
3. Press **X** to save or **B** to discard.
4. After selecting Save, press **X** for success, **Y** for failure or **B** for incomplete.

Release each button before the next press. The saved-demo index is published
only after task outcome selection; saved failure and incomplete demos remain
operator-retained. The headset shows recording status and a Stop/Save/classification panel with
button hints and highlighted choices. The host reports lifecycle changes and
output paths. A clean host Ctrl-C can finish with PASS when runtime checks pass.
Saved-demo metadata groups the technical recording segments.

Follow [dataset materialization](docs/DATASET_MATERIALIZATION.md) to extract the
recording, render offline RGB, create LeRobot outputs and evaluate admission.

## Components

| Component | Responsibility |
|---|---|
| `run-vr` | Entry point for run, diagnostic, recording and replay modes |
| `tools/isaac_vr_*` | VR scene, cameras, recording, replay and dataset conversion |
| `tools/isaac_s2_*` | Shared teleoperation loop, input processing and timing |
| `packages/lerobot_robot_piperx` | LeRobot integration for single and bimanual physical PIPER-X arms |
| `configs/` | Runtime settings, dependency specifications and robot/data contracts |
| `tests/` | Offline regression and integration checks |
| `docs/` | Setup, operations, dataset workflow and retained experiment results |

Isaac Lab, Isaac Teleop/CloudXR, NVIDIA Episode Recorder and LeRobot own their
respective runtime and storage functions. Project code composes them and maps
their inputs and outputs to explicit PIPER-X semantics.

## Current status

Isaac VR teleoperation, native state/action recording, offline RGB and LeRobot
conversion are implemented. S2 physical Quest 3 acceptance is registered with
operator observations, retained run provenance and a documented operator-stop
reassessment. Human-VR dataset admission remains open; this is a development
system, not a qualified release.

Automated demonstration generation, complete Isaac/MuJoCo policy evaluation and
physical policy rollout are further project milestones. Their requirements and
acceptance criteria are tracked separately from the working collection path.
RUN/DIAG use native ZED camera previews, with L3 switching between headset and
wall placement in left / scene / right order. RECORD keeps cameras state-only
and renders their RGB later during offline replay.

## Development and documentation

Core development commands:

```bash
uv run pytest
uv run python tools/validate_resolved_contract.py configs/resolved_contract.yaml
```

The contract validator distinguishes a valid configuration from a finished
release. `FINAL RC NOT READY` means required qualification milestones remain open.

- [VR operations](docs/project/RUN_VR_OPERATIONS.md): launch, controls and recording.
- [Dataset materialization](docs/DATASET_MATERIALIZATION.md): offline RGB, conversion and admission.
- [Core environment](docs/project/CORE_ENVIRONMENT_OPERATIONS.md): dependency setup and host tooling.
- [Documentation map](docs/README.md): further design, hardware and verification references.

For contributions, read [AGENTS.md](AGENTS.md) and the relevant component's
documentation before changing runtime or data semantics.
