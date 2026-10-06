# Head-locked / wall preview placement

Frozen bounded S2 evidence over `3977470` on `codex/vr-recording-ui`. Tested source
hashes, native outputs/manifests, exact temporary observers, failed attempts and
scope are retained in [checks](checks.json). Core stdout is [retained](core_tests.txt).
Historical ZED/FFFT proof is unchanged and does not automatically qualify these
new panel placements. No gate state is promoted.

Capability / upstream audit: Isaac Lab 17.0.2 / materialization `0c2e2c64`, Sim 6.1 /
Kit 110.3, `isaaclab_teleop` 0.9.0 own packing, head-locked/world descriptors,
Camera feeds and SceneUI panel construction. Kit `xr_utils` 1.0.2 owns persistent
UiContainers and visibility; destroying/recreating them on every button press
would accumulate view state. A narrow adapter preconstructs two panel sets, then
selects the active panel for each existing feed. It uses the upstream layout
functions and presenter rather than a new renderer or camera implementation.
Only the active three panels receive uploads. Six UiContainers are bounded for
the run lifetime; three native ZED Camera products remain. No new image source,
dependency, SDK change, processor semantics, recording format or D0 schema.
The existing large runtime/dispatcher modules were re-audited; new placement
ownership stays in the small helper. Environments remain the declared core and
isolated Isaac installations.

Selected behavior: default head-locked row moves down 8 cm. L3 (left thumbstick
click) toggles the row between head-locked and the fixed wall plane. Sensitivity
uses horizontal thumbstick position, so L3 is free in this VR profile. The separate
plain S2 click-sensitivity profile rejects this conflict. Both layouts are
LEFT WRIST → SCENE → RIGHT WRIST; X still controls visibility, B the wall and R3
recenter. RECORD retains X/Y/B and rejects a simultaneous preview-layout pipeline.
Its unconditional recording-view wall hide is removed without enabling Camera
sensors/products. Entering wall mode restores a B-hidden wall.

The native UI fixture deliberately avoids CloudXR session entry while the user's
RUN remains active. It executes the production VR scene builder and qualification
reset, real native Cameras, FFFT/capture and upstream SceneUI. Sixty holds/advances
include six mode changes (held presses do not repeat), X hide/show, B hide/restore
and a scene reset with the wall mode selected. The same camera objects survive;
all checked product counts are three. Nine RGBA source/upload samples match.
Native controller mapping/profile-isolation and state-only wall behavior tests
pass (three unittest cases). Independent native Gf checks orient the wall row
with readable normal -X, up +Z and left-to-right centres at Y=+0.65, 0, -0.65;
all panels are 2 cm in front of the wall. A separate production RECORD smoke
commits three injected rows, stays at FFFT with zero camera products and visible
background on every measured advance. Both processes shut down cleanly.

Commands from the assigned worktree, with EULA variables and DISPLAY=:0:

```sh
core=/data/vla-infrastructure/core-reconcile-validation/20260919T082843.713211Z/env/bin/python
"$core" /tmp/vr_layout_offline_launcher.py diag --smoke --no-hud-on-start --capture-preview-evidence --max-control-steps 60 --run-dir /tmp/vr-layout-native-fixture-v4
"$core" /tmp/vr_layout_record_launcher.py record --smoke --injected-actions --injected-count 3 --max-control-steps 6 --run-dir /tmp/vr-layout-record/run --recording-dir /tmp/vr-layout-record/episode
```

The retained offline launcher adds XRCore/xr_utils to the offline Kit extension
set and substitutes the bounded fixture for S2 session/decision-loop entry only.
It does not change the production scheduler or camera/panel builders. Its native
controller tests use unittest because pytest is absent in the Isaac environment.
The record observer forwards original step calls and checks render flags, product
inventory and backdrop visibility. Repetitions need new private output directories.
Earlier attempts/guard failures are retained in checks.json; no guard was weakened
and no user CloudXR session was taken over. A later caller-only guard skips absent
left-controller samples instead of treating absence as a physical L3 release; its
final source is covered by core checks, while native source hashes remain exact.

Scoped core command uses the existing reconciled environment, `uv run --no-sync`,
`UV_PROJECT_ENVIRONMENT` set to that environment, `UV_CACHE_DIR=/tmp/vla-vr-ui-uv-cache`,
`HF_HOME=/tmp/vr-zed-ffft-hf` and the assigned PIPER-X source PYTHONPATH:

```sh
python -m pytest -q tests/test_isaac_s2_upstream.py tests/test_isaac_vr_config.py tests/test_isaac_vr_preview_layout.py tests/test_isaac_s2_processor.py tests/test_isaac_vr_recording.py tests/test_isaac_vr_capture.py tests/test_isaac_vr_camera_rendering.py
```

Result: 110 passed, 28 skipped (native dependencies); the three selected native
cases above cover this task's mapping/wall checks in the actual SDK. The pure
layout regression exercises 40 toggles/held presses without replacing camera or
image-source owners and checks independent panel teardown.

Every retained file is indexed as frozen evidence; checks/core output are artifacts
bound to the supplemental S2 command-test evidence. README is navigation.
MANIFEST membership stays at 110 reviewed normative inputs; no evidence file is
added automatically. Physical Quest layout/visibility/readability/comfort, full
CloudXR controller-loop execution and wall disappearance in the user's old RUN
are not independently qualified. The definite RECORD hide was removed; the new
candidate's USD wall visibility is measured. Current S2/D1 remain unresolved.
