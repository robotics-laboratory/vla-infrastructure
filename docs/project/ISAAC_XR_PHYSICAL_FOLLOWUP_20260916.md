# Isaac XR physical follow-up — 2026-09-16

This report follows the physical Quest run saved under `xr_fixes/20260916/physical_report/`. It is experimental S2 evidence and does not change a production gate or D0 contract.

| Issue | Physical evidence / root cause | Fix status | Retest |
|---|---|---|---|
| R3 freezes teleop | R3 scheduled at log line 875. Every later status through step 2880 is `session_inactive`; no navigation-applied event follows. The HMD pose was incorrectly required to equal the view-prim pose. | Fixed in first follow-up commit: accept the next XR transform after rendered app updates, then rebase again if it changes later. | R3 once and repeatedly while looking away/moving head; verify one held frame and no jump. |
| Camera preview recursion | User observed camera panels in camera pixels. The optional post-update Replicator source made the preview depend on the XR composition. | Fixed in second follow-up commit: force the manager's existing Isaac Lab Camera RGBA fallback and do not attach the extra annotator. | Both feeds visible together; no nested panels. |
| Wrist camera pose | User observed downward, inverted view away from gripper direction. Config attached identity `world` camera pose (+X optical axis) to a gripper whose approach axis is local +Z. | Fixed in third follow-up commit: optical +X maps to gripper +Z, up +Z maps to gripper +X; a real-Kit sweep selected a 6 cm parent-X offset. | Gripper extended; view forward along approach axis with only the finger tips at the lower edge and upright. |
| Sensitivity | Six binary Y toggles appear at steps 2394–2477; precise is physically too slow. | Fixed in fourth follow-up commit: each controller's horizontal thumbstick continuously controls only its arm from 2× through the previous 4× center speed to 6×. | Move each thumbstick independently through left/center/right and compare both hands. |
| Preview height | User reports panels obscure robots. The previous head-locked center was 0.18 m below the viewer anchor. | Fixed in fifth follow-up commit: use the upstream positive image-up direction and place the center 0.18 m above the viewer anchor. | Panels above gaze without obscuring robot workspace. |

## R3 follow-up

`XRCore.schedule_teleport_to_view` changes the space-origin mapping; it does not define a contract that the returned virtual HMD matrix must numerically equal the target view-prim matrix. The first implementation therefore waited forever in the observed run. The follow-up holds the request frame only. Four normal rendered physics/app updates occur before the next control sample, whose current `physical_to_virtual_world` transform becomes the new reference. If Kit applies the teleport later, the existing navigation-change detector produces a second safe zero-motion rebase.

The controller coordinate transform, synchronous upstream execution and missing-transform hold remain unchanged. Thirty-three pinned unit tests pass, including immediate resume, delayed transform application, repeated/no-op R3 and four navigation yaws for both hands. Physical Quest retest is still required.

## Wrist camera pose follow-up

Isaac Lab's `world` camera convention defines the camera optical axis as local +X and image-up as local +Z. PIPER-X approaches through the gripper's local +Z axis, so the previous identity rotation necessarily looked across the gripper and produced the reported downward/inverted result. The experimental demo rotation `(0.70710678, 0, 0.70710678, 0)` in XYZW maps camera +X to gripper +Z and camera +Z to gripper +X.

The archived real-Kit sweep compares the original pose, both possible image-up signs, and three positions. The selected `(0.06, 0, 0)` parent-frame position is upright and leaves only the finger tips at the lower edge. The non-XR S1 camera contract remains unchanged. A physical Quest check is still needed because the no-client images establish render geometry, not headset comfort.

## Per-hand speed slider follow-up

The demo pipeline keeps the same 22-value S2 action prefix. Its fifth state value per arm now comes from that controller's upstream `THUMBSTICK_X` field. The pure processor clamps the value to `[-1, 1]` and maps it piecewise-linearly: left gives 2× translation/rotation, center preserves the previous normal 4× speed, and right gives 6×. Each hand has separate state, and changing speed does not discard a controller delta. The stock non-demo configuration retains its independent click-toggle mapping and gains.

Thirty-six processor/upstream/config tests pass. They cover both controller fields, independent −1/+1 and fractional positions, clamping, the unchanged 22-value prefix, and the existing production toggle behavior. A 16-step real-Kit no-client smoke passes with both upstream pipelines in slider mode and 16/16 advancing bimanual camera frames. With no physical controllers attached, that smoke observes the centered 4× value; the full range remains a physical Quest retest item.

## Upstream audit — speed slider

CAPABILITY / GATE: experimental demo-only S2 motion scaling; no gate acceptance.
PINNED UPSTREAM CANDIDATES: IsaacTeleop 1.4.98rc1 `ControllersSource` and `ControllerInputIndex.THUMBSTICK_X`; existing Isaac Lab / CloudXR pins are unchanged.
WHAT UPSTREAM ALREADY OWNS: per-controller thumbstick acquisition, OpenXR controller routing, transformed controller stream and fixed retargeting graph.
EXACT REMAINING GAP: map each upstream horizontal axis to the existing per-arm PIPER-X delta gain.
PROCESSOR / CONFIG / ADAPTER REQUIRED: one existing state scalar per arm, demo config, and a bounded pure piecewise-linear processor mapping; action width remains 22 plus the three existing demo buttons.
ENVIRONMENT IMPACT: none.
WHY NO PROJECT FRAMEWORK IS NEEDED: the existing `ControllerStateRetargeter` and pure S2 processor already provide the required public boundaries.

## Preview height follow-up

Pinned `XrCameraFeedLayoutCfg.center_offset_m` defines horizontal and vertical center in metres, and its panel-local +Y is image-up. The old `(0, -0.18)` center therefore put both head-locked panels below the viewer. The experimental layout now uses `(0, +0.18)`. The measured panel height is about 0.31 m, so its lower edge is about 2.5 cm above the viewer center at the configured 0.65 m distance. Panel size, gap, texture update path and camera rendering remain unchanged.

The pinned upstream layout probe resolves both panel offsets to Y `+0.18`; a real-Kit no-client smoke validates the configured session and panel creation. Physical Quest placement and comfort still require the user's retest.

## Upstream audit — preview height

CAPABILITY / GATE: experimental demo-only XR camera layout; no gate acceptance.
PINNED UPSTREAM CANDIDATES: Isaac Lab 913ac53f / isaaclab_teleop 0.8.0 `XrCameraFeedLayoutCfg`, `_layout_feed_cfgs`, and head-locked SceneUI presenter.
WHAT UPSTREAM ALREADY OWNS: head pose following, horizontal packing, metres-to-panel pose conversion and SceneUI lifetime.
EXACT REMAINING GAP: choose a vertical center that does not cover the robot workspace.
PROCESSOR / CONFIG / ADAPTER REQUIRED: one config value only; no runtime adapter.
ENVIRONMENT IMPACT: none.
WHY NO PROJECT FRAMEWORK IS NEEDED: upstream layout semantics directly express the requested placement.

## Upstream audit

CAPABILITY / GATE: experimental Isaac S2 Quest teleoperation; no gate acceptance.
PINNED UPSTREAM CANDIDATES: Isaac Lab 913ac53f / 16.4.0, Isaac Sim 6.0.1.0, IsaacTeleop 1.4.98rc1, isaaclab_teleop 0.8.0, CloudXR 6.2.1.
WHAT UPSTREAM ALREADY OWNS: XR frame scheduling, teleport scheduling, current physical-to-virtual transform, controller acquisition and retargeter reset.
EXACT REMAINING GAP: choose a non-blocking application boundary because the API exposes scheduling but no public completion event in the pinned version.
PROCESSOR / CONFIG / ADAPTER REQUIRED: one boolean in the existing navigation-aware device; no new protocol or framework.
ENVIRONMENT IMPACT: none.
WHY NO PROJECT FRAMEWORK IS NEEDED: the change stays at the existing upstream lifecycle seam.
