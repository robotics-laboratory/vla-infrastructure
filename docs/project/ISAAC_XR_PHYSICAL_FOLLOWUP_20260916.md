# Isaac XR physical follow-up — 2026-09-16

This report follows the physical Quest run saved under `xr_fixes/20260916/physical_report/`. It is experimental S2 evidence and does not change a production gate or D0 contract.

| Issue | Physical evidence / root cause | Fix status | Retest |
|---|---|---|---|
| R3 freezes teleop | R3 scheduled at log line 875. Every later status through step 2880 is `session_inactive`; no navigation-applied event follows. The HMD pose was incorrectly required to equal the view-prim pose. | Fixed in first follow-up commit: accept the next XR transform after rendered app updates, then rebase again if it changes later. | R3 once and repeatedly while looking away/moving head; verify one held frame and no jump. |
| Camera preview recursion | User observed camera panels in camera pixels. | Pending separate commit. | Both feeds visible together; no nested panels. |
| Wrist camera pose | User observed downward, inverted view away from gripper direction. Config attaches identity `world` camera pose to a gripper whose approach axis is local +Z. | Pending separate commit. | Gripper extended; view forward along approach axis with part of both fingers visible and upright. |
| Sensitivity | Six binary Y toggles appear at steps 2394–2477; precise is physically too slow. | Pending per-hand thumbstick-X slider commit. | Move each thumbstick independently through left/center/right and compare both hands. |
| Preview height | User reports panels obscure robots. Current center offset is -0.18 m. | Pending separate layout commit. | Panels above gaze without obscuring robot workspace. |

## R3 follow-up

`XRCore.schedule_teleport_to_view` changes the space-origin mapping; it does not define a contract that the returned virtual HMD matrix must numerically equal the target view-prim matrix. The first implementation therefore waited forever in the observed run. The follow-up holds the request frame only. Four normal rendered physics/app updates occur before the next control sample, whose current `physical_to_virtual_world` transform becomes the new reference. If Kit applies the teleport later, the existing navigation-change detector produces a second safe zero-motion rebase.

The controller coordinate transform, synchronous upstream execution and missing-transform hold remain unchanged. Thirty-three pinned unit tests pass, including immediate resume, delayed transform application, repeated/no-op R3 and four navigation yaws for both hands. Physical Quest retest is still required.

## Upstream audit

CAPABILITY / GATE: experimental Isaac S2 Quest teleoperation; no gate acceptance.
PINNED UPSTREAM CANDIDATES: Isaac Lab 913ac53f / 16.4.0, Isaac Sim 6.0.1.0, IsaacTeleop 1.4.98rc1, isaaclab_teleop 0.8.0, CloudXR 6.2.1.
WHAT UPSTREAM ALREADY OWNS: XR frame scheduling, teleport scheduling, current physical-to-virtual transform, controller acquisition and retargeter reset.
EXACT REMAINING GAP: choose a non-blocking application boundary because the API exposes scheduling but no public completion event in the pinned version.
PROCESSOR / CONFIG / ADAPTER REQUIRED: one boolean in the existing navigation-aware device; no new protocol or framework.
ENVIRONMENT IMPACT: none.
WHY NO PROJECT FRAMEWORK IS NEEDED: the change stays at the existing upstream lifecycle seam.
