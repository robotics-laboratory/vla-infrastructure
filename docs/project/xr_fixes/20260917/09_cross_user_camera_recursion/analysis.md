# Cross-user XR camera recursion investigation — 2026-09-17

This is experimental S2 diagnostic evidence. It does not accept or change a gate.

## Established facts

- The project worktree and `origin/experiment/robosyn-vr-demo` both resolved to `d8f2021da7224c7de1c85c7301bd3f917934c424` during the investigation.
- The colleague's physical run `20260916T204052251704Z-dual_cube_to_matching_plates-hud-on` loaded the project source from `/home/blackfire/vla-infrastructure` and reported `source=isaac_lab_camera_rgba` for both feeds. The disabled feed-owned Replicator annotator is therefore not the recursion source in that run.
- Its pre-XR left/right RGB standard deviations (`36.0939`, `36.1857`) match the last known-good run `20260916T181126505688Z-dual_cube_to_matching_plates-hud-on` within the logged precision. The camera buffers are valid before the physical XR session starts.
- The Kit extension sets are equal except for `omni.usd.metrics.assembler.ui-110.1.1`; camera, RTX, OpenXR, SceneUI and Replicator versions match.
- Pinned Isaac Lab `913ac53f` already contains upstream commit `6f35c455`, `Fixes XR and external camera bug with async rendering`. The OpenXR experience sets `omni.replicator.asyncRendering=false` as required for external cameras.
- The last known-good run used the old installation and persistent profile below `/data/ebulochkin/envs/isaac-s1-candidate-b`. The colleague ran after the environment was recreated below `/data/vla-infrastructure` and after `d8f2021` introduced fresh per-UID XDG and Kit portable roots. Thus the launch text matched, but runtime state did not.
- A bounded cold-profile smoke for UID 1006 reached RTX camera and articulation initialization but did not reach demo binding before it was interrupted. It produced no camera boundary artifact and is not physical evidence.

## Remaining causal split

The existing logs sample camera pixels only before XR becomes visible. They cannot distinguish:

1. `camera.data.output["rgba"]` becomes contaminated after XR/SceneUI starts; this is an Isaac RTX/render scheduling defect or race.
2. The camera tensor remains clean and the nested image is introduced after upload by SceneUI, CloudXR runtime or the client compositor.

The runtime now saves bounded PPM pairs directly from `feed.image` and `feed.upload_image`, including the first publication after every display-visible edge and scheduled publications 1, 30, 120, 300, 600 and 1200. `manifest.json` records the RGBA SHA-256 values and byte equality. Files are written incrementally under each run's `camera_feed_diagnostics/`, so they survive a killed run without `result.json`.

Interpretation is deterministic:

- recursive `*-source.ppm`: Isaac camera/render scheduling path;
- clean source and upload PPMs while Quest shows recursion: SceneUI/CloudXR/client composition path;
- differing source/upload SHA-256: CPU staging corruption.

## Upstream audit

CAPABILITY / GATE: experimental Isaac S2 XR camera presentation diagnostic; no gate acceptance.

PINNED UPSTREAM CANDIDATES: Isaac Lab `913ac53f`, Isaac Sim `6.0.1.0`, isaaclab_teleop `0.8.0`, IsaacTeleop `1.4.98rc1`, CloudXR `6.2.1`.

WHAT UPSTREAM ALREADY OWNS: Isaac RTX camera rendering, `Camera.data.output["rgba"]`, external-camera async policy, SceneUI panel lifecycle, raw image provider and OpenXR/CloudXR composition.

EXACT REMAINING GAP: persisted evidence at the camera-source/upload boundary after the physical XR session becomes visible.

PROCESSOR / CONFIG / ADAPTER REQUIRED: one bounded observer on the existing manager publication boundary; no alternate source, renderer, protocol or panel implementation.

ENVIRONMENT IMPACT: none; the observer writes at most a bounded set of PPM/JSON artifacts and does not alter render or publication cadence.

WHY NO PROJECT FRAMEWORK IS NEEDED: the pinned feed record already exposes the exact source and upload tensors required to isolate the fault domain.

