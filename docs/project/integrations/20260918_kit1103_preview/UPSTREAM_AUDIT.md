# Integration audit

CAPABILITY / GATE: reversible preview isolation integration and Linux-user-independent launch; no human gate acceptance claimed.
PINNED UPSTREAM CANDIDATES: Isaac Sim6.1.0.0 / Kit110.3.0; Isaac Lab ae37b028ea415c91ea2bc32609efcd759ed2b974; teleop0.9.0 / IsaacTeleop1.4.98rc1. Legacy913ac53f / Sim6.0.1.0 remains selectable.
WHAT UPSTREAM ALREADY OWNS: RTX Scene Partitions, Camera, XRSceneView and UiContainer, CloudXR per-user install/session and teleop/IK.
EXACT REMAINING GAP: author each SceneUI draw-system partition plus explicit sensor tokens before rendering; rebind after show/recreation; validate lifecycle; select exact environment/config without private home paths or shared mutable caches.
PROCESSOR / CONFIG / ADAPTER REQUIRED: small USD authoring/assertion helper and launcher/config changes. The /ui-only shortcut failed the pixel detector at frame4 and was discarded. No action-label or controller semantics change.
ENVIRONMENT IMPACT: reuse isolated target SDK; independent shared code checkout /data/vla-infrastructure/robosyn-kit1103; each UID owns caches/assets/output and CloudXR. Never borrow another user's IPC or stop their runtime.
WHY NO PROJECT FRAMEWORK IS NEEDED: compose the existing demo and NVIDIA mechanisms. No custom XR protocol, renderer or new environment per component.

User explicitly authorized integration with rollback on2026-09-18; prior qualification's no-production-change restriction is superseded for this integration. Physical acceptance remains unclaimed.

Sources: https://docs.omniverse.nvidia.com/materials-and-rendering/latest/cameras.html#scene-partitions ; https://docs.omniverse.nvidia.com/dev-guide/latest/release-notes/110_3.html ; https://nvidia.github.io/IsaacTeleop/release/1.4.x/references/cloudxr.html . Installed XRSceneView.get_base_path and UiContainer show/hide are used through Python bindings; no native ABI access added.
