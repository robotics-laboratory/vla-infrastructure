# XR overhead audit: installed Isaac 6.1 / Kit 110.3 / IsaacTeleop 1.4.98rc1 / CloudXR 6.2.1

Research date: 2026-10-09. Checkout `/home/ebulochkin/vla_infrastructure`, branch `research/live-camera-recording-30hz`, HEAD `d5566834d29ef8bb56e4fb62bb324e23e0869100`. No GPU/XR app launch, SDK install/mutation, physical action, contract change or gate qualification. This is read-only source analysis plus a `/tmp` experimental upload adapter. Existing untracked `deep_research/` belongs to the root agent.

## Главные выводы

1. Самая дешёвая XR мера — уменьшить **только eye workload** и подтвердить новое handshake resolution при сохранении всех трёх dataset cameras 960×600. Текущий публичный Quest3 профиль — 2048×1792 на глаз, 72 Hz, AV1, 25 Mbps, WebXR framebufferScaleFactor=1.5, fixedFoveation=.666. Hosted client `/client/release-1.4.x/bundle.js` действительно содержит CloudXR.js **6.3.0**, хотя установленный server runtime — **6.2.1**. Следовательно, browser release series не является неизменяемым dependency pin.
2. Реальный pacing knob установленной 6.2.1 — `max-fps` (из 6.2.0); native binary содержит env alias `NV_MAX_FPS`. Начать A/B 0→45→50 при сохранённом headset refresh72/90. Это pacing/rate-adaptation hint для медленного приложения, а не ускоритель рендеринга и не гарантированная команда «замедлить лишь XR».
3. Три CPU preview copies сейчас синхронны (`copy_(image, non_blocking=False)`), затем raw buffer upload + SceneUI capture. Сам bandwidth около207 MB/s при30 FPS — небольшой для GPU; опаснее **три serialization points** на критическом render/control пути. Native GPU `ByteImageProvider.set_bytes_data_from_gpu` уже существует. Подготовлен upload-only adapter `/tmp/live30_xr_gpu_preview.py`, сохраняющий cached source, existing partition checks, panel layout/lifetime, on-demand invalidation, и не создающий render products.
4. `PIPELINED` установлен и upstream-owned; это не будущая возможность. Но одна конфигурационная строка нарушит текущую provenance: проект специально принудительно SYNC, `XrInputReceipt.resolve()` принимает только current-frame synchronous receipt. Pipelined result может повторяться; повторить relative delta означает повторить intent. Пока нужен отдельный receipt/output pairing adapter, direct switch исключён из безопасных флагов.
5. Native OpenXR quad fastpath текущего IsaacCapture требует **обновления/новой композиции**, а не локального флага. Installed `QuadLayerConfig` не содержит `openxr_composition`/`alpha_blend`. Release notes называют раннее имя `use_openxr_quad_layer`, но actual v1.4.145 source использует `openxr_composition=true`. Native-only projection-drop выгоден для camera/UI-only XR; наличие 3D Piper projection оставляет projection work. Второй OpenXR session/VizSession нельзя просто запускать рядом с Kit session.
6. Ни один публичный источник не устанавливает >30 wall-Hz actions **и каждой из трёх fresh 960×600 cameras** при данном scene + activeXR + connectedQuest3. 90FPS CloudXR marketing, theoretical NVENC throughput, no-client screening и browser reprojection не являются таким доказательством.

## Exact version/source audit

Installed environment paths below use `SP=/data/vla-infrastructure/isaac61_production/env/lib/python3.12/site-packages`, `LAB=/data/vla-infrastructure/isaac61_production/IsaacLab`. Hash ledger: `/tmp/live30-xr-sources.json`.

| Boundary | Installed fact | Current public divergence / scope |
|---|---|---|
| Python package | `SP/isaacteleop-1.4.98rc1.dist-info/METADATA`; package1.4.98rc1 | Public `release/1.4.x` resolves to **v1.4.145**, commit `5bbe49d4c92746076196216c3f74e08ae509809a`, commit date2026-09-13 |
| Retarget worker | `SP/isaacteleop/teleop_session_manager/async_retarget_runner.py` SHA `a6e21b7ce67c5bd0d1603940ff40b190252449a09a1aca2c510fcb6999ada9ae` | **Byte-identical** to current pinned public source; config/session files differ (documentation/import rename), so source package equality is not claimed |
| CloudXR native | `SP/isaacteleop/cloudxr/native/libcloudxr.so`; selected project pin6.2.1 | Public client package.json6.3.0 and actual hosted bundle SDK_VERSION6.3.0; later native runtime features are not inferred on6.2.1 |
| Kit XR | `omni.kit.xr.core-109.1.0+00c488ae.lx64.r.cp312`; `omni.kit.xr.system.openxr-109.1.0+...`; Kit110.3 | Spatial docs explicitly apply to Kit109.0.3+ / CloudXR6; docs sometimes show conflicting hierarchy examples; installed XRSettings token resolution is the correct implementation anchor |
| Televiz | Installed `viz/_viz.pyi` has ProjectionLayer + QuadLayer, generate_mipmaps, stereo, get_oxr_handles | Installed stub and native binary lack native quad composition switch; current v1.4.145 has `openxr_composition=true` and `alpha_blend=false` |

Public source snapshot and per-file hashes: `/tmp/live30-xr-upstream/manifest.json`; public doc/forum snapshots: `/tmp/live30-xr-public/manifest.json`. The failed first raw source fetches/404 guesses are retained in the manifest, then corrected paths were fetched.

## CloudXR 6.2.1: pacing and eye burden

[Runtime management API](https://docs.nvidia.com/cloudxr-sdk/latest/usr_guide/cloudxr_runtime/runtime_mgmt_api.html) documents `max-fps`: int64, default0 automatic, range0–60; use for apps rendering30/45 rather than high-FPS60/90. Properties are configured before service start. `disable-alpha` can remove alpha encoding/bandwidth for opaque content; runtime foveation is streaming-space centre foveation, distinct from application RTX foveation. [6.x release notes](https://docs.nvidia.com/cloudxr-sdk/release/6/release_notes/release_notes.html) place `max-fps` addition in6.2.0. This makes6.2.1 applicable, unlike a source-only6.3 feature.

Installed `cloudxr/runtime.py::run` creates then immediately starts the service, with no explicit property setter calls. Installed `EnvConfig` reads env file + applies values; launcher passes a copied process environment into isolated runtime subprocess. `strings libcloudxr.so` shows `NV_MAX_FPS`, `max-fps`, `applyEnvOptionIfSetAndValid(maxFps)`, `NV_DISABLE_ALPHA`, `NV_CXR_RUNTIME_FOVEATION`, `NV_CXR_RUNTIME_FOVEATION_UNWARPED_WIDTH`, `NV_CXR_RUNTIME_FOVEATION_WARPED_WIDTH`, `NV_CXR_RUNTIME_FOVEATION_INSET`, `NV_ENABLE_POSE_WAIT`, `NV_MAX_POSE_WAIT_DURATION_MS`. These binary strings ground **candidates**, but are not successful runtime readback. Prefer a per-run copied env file or set `NV_MAX_FPS` only in launch environment; preserve the entire resolved env receipt. Existing `cloudxrjs-cloudxr.env` already sets:

```env
NV_DEVICE_PROFILE=auto-webrtc
NV_CXR_ENABLE_PUSH_DEVICES=0
NV_ENABLE_POSE_WAIT=0
```

Do not recommend `NV_ENABLE_POSE_WAIT=0` as a new speedup: it is already selected. Unknown env keys inherited into subprocess can be supported by native runtime even though absent from EnvConfig defaults; explicit env-file value wins.

Browser settings actually available in public release `params.ts`: `perEyeWidth`, `perEyeHeight`, `deviceFrameRate`, `maxStreamingBitrateMbps`, `enableTexSubImage2D`, `codec`. **`deviceProfile` is deliberately omitted** as URL param because selecting a profile bulk-fills multiple controls. Set Quest3 in UI, then explicit dimensions, and record actual final values; URLs can seed those scalar values.

Example exact client trial after selecting Quest3/reset and before connecting:

```text
https://nvidia.github.io/IsaacCapture/client/release-1.4.x/?perEyeWidth=1792&perEyeHeight=1536&deviceFrameRate=72&maxStreamingBitrateMbps=25&enableTexSubImage2D=true
```

Width must be multiple16, height multiple64. This is an operator/client change, not a host launcher setting. Browser configs/localStorage are scoped per application; save client hash and final UI/SDK config. [CloudXR.js performance guide](https://docs.nvidia.com/cloudxr-sdk/latest/usr_guide/cloudxr_js/performance.html) offers2048×1792 balanced and1792×1536 performance reference, plus client framebuffer1.2/foveation1.0 trials. It is general guidance, not measured Piper performance. Current source [Quest profile](https://github.com/NVIDIA/IsaacCapture/blob/5bbe49d4c92746076196216c3f74e08ae509809a/deps/cloudxr/webxr_client/helpers/DeviceProfiles.ts) selects72FPS/25Mbps and comments that older90FPS/150Mbps was unstable in **one wireless production deployment**. This does not prove72 is optimal for our network.

A dimensional estimate, **not measured GPU timings**:

| Pipeline pixel demand | MPixels/s |
|---|---:|
| 3×960×600 at30 fresh FPS | 51.84 |
| 3×960×600 at50 fresh FPS | 86.40 |
| 2×2048×1792 eyes at72 | 528.48 |
| 2×2048×1792 eyes at90 | 660.60 |
| 2×1792×1536 eyes at72 | 396.36 |
| 2×1536×1280 eyes at72 | 283.12 |

Eye settings have potentially larger raw pixel leverage, but warped/quadview rendering, AA, depth pass, encode and reprojection change actual cost. Reduce eye dimensions while **never changing** dataset camera dimensions, mounting, FoV, source geometry or action processor. `max-fps=45` may retain fluid HMD display through runtime reprojection while the app submits45; it cannot turn45 reprojected display frames into45 novel dataset observations.

## Kit XR scheduler / waitIdle / lateLatch

[Spatial core concepts](https://docs.omniverse.nvidia.com/xr/omniverse-spatial-docs/latest/development/core-concepts.html) describes a two-frame Kit XR pipeline, with simulation/USD merge then pose capture/scheduling/render submission. Pose-late updates target XR presentation and do not establish current dataset camera identity. Installed core binary includes XRDisplayScheduler, XRViewportMirrorScheduler, `XR: Prev frame done wait`, `XRCore::waitGraphicsDone`, cross-GPU copy waits, `/app/asyncRendering` and an explicit warning against changing async mode during XR. No public supported `lateLatch` setting for this installed KitXR was located; NVAPI DX11 late-latch docs are Windows-specific and inapplicable to Linux Vulkan Kit.

Three different waits must be distinguished:

- `/app/hydraEngine/waitIdle`: global main-thread GPU completion fence after a frame. [NVIDIA performance troubleshooting](https://nvidia-omniverse.github.io/omniverse-performance/workflows/troubleshooting.html) recommends false for rendering-only pipelines and cautions that same-frame physics/sensor readback may require true.
- `xrWaitFrame`: OpenXR display pacing / predicted pose boundary, upstream-owned by Kit runtime. Deleting it or driving a second session destroys frame protocol ownership.
- `XRSystem::waitIdle` / `OpenXR::waitIdle`: interface/cleanup synchronization, not evidence that all steady-state frames are GPU-fenced.

For bounded image lag, waitIdle=false is a valuable **dependent experiment**, after producer surfaces have immutable snapshots and proper GPU event/fence receipts. Current `ThreeCameraCapture` ties state physics step and render_generation to extraction at one boundary; flag-only removal can associate an earlier actual render with a newer counter. Root should pair it with producer-driven writer/events and scene-state identity, not weaken receipt checks.

XR resolution token supported by installed binary is `profile/persistent/render/resolutionMultiplier`. **Canonical IsaacLab XR experience uses activeProfile=ar, not vr** (hardware identity does not select the Kit profile). Read current active profile; for canonical AR use `XRSettings.get_singleton().set_setting(("profile/persistent/render/resolutionMultiplier", "ar"), .8)` or resolved carb path `/persistent/xr/profile/ar/render/resolutionMultiplier`, snapshot/restore existing value in a disposable state root. The VR extension default is not the effective canonical profile. Foveation tokens are present for `warped`, `quadview/background`, `quadview/inset`, `quadview/stereo`. [XR settings reference](https://docs.omniverse.nvidia.com/xr/omniverse-spatial-docs/latest/server/03-xr-settings.html) covers `.8` resolution and peripheral multiplier/inset; installed extension defaultsVR warped and requestQuadviewMode=true. Runtime readback + actual eye/render-product dimensions must establish whether setting takes effect after reconnect.

Quality preset `performance` disables reflections and reduces sampled-light SPP4→2 versus balanced in installed extension.toml. Because XR renderer settings and several components write global `/rtx` values, do **not** assume `renderQuality` is dataset-isolated just from profile naming. Snapshot dataset RP effective settings and representative pixel receipts before/after, or apply explicit XR RenderProduct policy. Hiding mirror/tooltips/UI is an observational ablation only when it retains XR display, controller tracking and all three camera products; removing scene cameras is outside goal.

## CPU-staged preview and exact reversible adapter

Project `_CpuStagedFeedPresenter.create_image_source` returnsNone: presentation reuses already-produced camera cache rather than upstream separately attached annotator. `prepare_upload_image` reuses CPU buffer; stage copies synchronously; `_CpuRgbaPanel.upload` passes raw buffer capsule into ByteImageProvider, retains tensor, and sets ON_DEMAND widget invalidation. `_FreshVisibleFeedUpdates` avoids hidden/duplicate/throttled uploads and caps30Hz. Thus **no-op GPU bypass must not be counted as writer optimization**: dataset production/recording is separate.

Installed upstream `_KitSceneUiCameraFeedPanel.upload` already supports CUDA pointer upload via `set_bytes_data_from_gpu`. Replacing the entire presenter with native upstream presenter may select another direct annotator/source and lose current anti-recursion/layout repairs. The prepared `/tmp/live30_xr_gpu_preview.py` modifies only upload/staging methods, retains the current panel class and isolation lifecycle, and maintains on-demand invalidation. Example use inside root's temporary probe:

```python
import importlib.util
s = importlib.util.spec_from_file_location("xr_gpu_preview", "/tmp/live30_xr_gpu_preview.py")
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)
# runtime_module is the imported tools/isaac_vr_runtime.py module; feeds not bound yet.
handle = m.install(runtime_module)
try:
    run_existing_probe()
finally:
    # Stop feed callbacks before restoring methods.
    save_receipt(handle.receipt())
    handle.restore()
```

This is **experimental**, because the CPU path's docstring explicitly states CloudXR compatibility. The helper keeps a reference, not a producer ownership fence: same-buffer CUDA producer reuse still depends on upstream provider synchronization. Test for black frames, delayed/partial upload and changing producer values; reject artifacts if any. The real headset test must confirm preview identity/correctness, not only host tensor equality. Native GPU path can still perform a GPU copy into provider texture; call it no-host-roundtrip, not universal zero-copy.

Check scope: syntax compilation and a CPU fake provider smoke confirm identity, upload arguments, widget invalidation, no staging copy, and method restoration. No actual torch CUDA tensor, Kit provider, CloudXR or Quest tested. Log `/tmp/live30-xr-adapter-check.log`. Initial `py_compile` failed because `/tmp/__pycache__` denied writing; rerun using `PYTHONPYCACHEPREFIX=/tmp/live30-xr-pycache` passed. This failure does not implicate GPU adapter logic and is retained in checks ledger.

## PIPELINED is installed, but source receipts must move into output

Installed `TeleopSessionConfig` provides SYNC and PIPELINED; the worker does DeviceIO.update→tracker polling→control graph→main graph→sinks as one serial whole step. First frame seeds synchronously; one worker/one pending request; newer unstarted requests replace older ones. Each app `step()` returns latest-completed result; `last_context` describes returned output, while `last_step_info` reports submitted/returned IDs, age_frames/age_seconds, dropped_submissions, compute_duration, deadline miss, worker exception. Public [step guidance](https://github.com/NVIDIA/IsaacCapture/blob/5bbe49d4c92746076196216c3f74e08ae509809a/docs/source/getting_started/teleop_session.rst) and byte-identical installed `async_retarget_runner.py` establish this behavior.

Installed IsaacLab lifecycle `_resolved_retargeting_execution` defaults to PIPELINED with DeadlinePacing safety_margin=.025. Custom `PiperXIsaacTeleopDevice.__init__` deliberately assigns modeSYNC (tools/isaac_s2_upstream.py:495). Its callback sidechannel `XrInputReceipt` is mutated inside poll/transform; `polled` stamps **session.frame_count**, which belongs to application thread. Current `resolve` requires exactly one update this advance, `ran_synchronously=true`, both IDs equal source frame, then validate forbids reused deviceio generation. Direct pipelining either fails closed or races result metadata.

Minimum remaining adapter, if profiling shows retargeting material on critical path:

1. Carry immutable source receipt **inside the graph output** with worker request identity/context, instead of separately changing a shared receipt. Resolve receipt from the returned result's same `last_context`; no new XR protocol needed.
2. Consume each returned_frame_id once. Repeated results must hold target, not integrate Se3 delta again; source button edges/clutch/reset processed once. Hold frames are not fresh-intent dataset rows.
3. Track session/reference epoch, tracking validity, recenter/reference transform and disconnect; asynchronous output from old reference never applies to new reference. Reset/recenter require barrier and baseline rebase, with no older result permitted after barrier.
4. Record returned_age_s, submitted/returned IDs and drop/coalescing counts. Define bounded source lag separately from image lag. User accepted small image lag, which does not automatically authorize delayed/replayed source intent.
5. Keep IK/preclip dataset_action→native command mapping and obs-before-decision identity. A worker-produced controller input can be used to decide on current obs, but cannot pretend it was produced synchronously at the current boundary.

Do not implement a custom retarget runner: reuse installed worker after provenance adapter. No claimed quantitative gain; Python GIL, small graph cost and CUDA synchronization may limit overlap. First useful trial is retarget-only replay/fake graph with event receipt and repeated-result tests, then root GPU trial. No safe pipelined adapter was written here because the current invariant requires a contract-aware design and lifecycle coverage rather than a launch flag.

## NVENC contention and Televiz alternatives

[Official NVENC application note13.1](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/nvenc-application-note/index.html) explains graphics/CUDA-independent engines, driver balancing of simultaneous sessions, and per-engine throughput limits. [Current matrix](https://developer.nvidia.com/video-encode-decode-support-matrix) lists RTX4090 two NVENC engines and12 concurrent sessions. This current policy is **not a measured capability of pinned driver580.159.03**; old forum guidance said8. The limit is system-wide on consumer boards; encode session **count** differs from encoder **throughput**.

CloudXR eye video and three dataset encoders will share encoder resources, preprocessing/copies and VRAM. Exact number of CloudXR sessions depends on enabled views/alpha/depth/codec; don't assume «XR costs exactly two». At2048×1792 two-eye90 presentation has >12× raw dataset pixel rate, but native stream packing/foveation changes encoded dimensions. For6.2.1 rooted trial gather `nvidia-smi encodersessions` when supported, `nvidia-smi --query-gpu=utilization.encoder,utilization.decoder,utilization.gpu,memory.used --format=csv`, CloudXR stream dimensions/codec/native logs, and dataset per-role packet throughput. Compare writer off/on while holding connectedQuest eye settings; different disconnected runs cannot measure competition.

[Forum dual NVENC report](https://forums.developer.nvidia.com/t/fluctuating-performance-with-two-instances-of-nvenc/247778) reports RTX4090 AV1 single~25FPS versus two combined25–50; input resolution/preset/synchronization insufficiently scoped. It is a contention hypothesis, not evidence of limits here. [CloudXR6.2.1 Windows thread](https://forums.developer.nvidia.com/t/cloudxr6-windows-server-bug/371160) concerns service registration/security rather than Linux throughput. [RTX5090 CloudXR6.2 encoder issue](https://github.com/NVlabs/GR00T-WholeBodyControl/issues/206) cautions that upgrading hardware/runtime without validated combination can regress streaming. Neither establishes Linux4090 bottleneck. These community observations are source leads/negative applicability checks, not authoritative performance rules.

Current [QuadLayer source](https://github.com/NVIDIA/IsaacCapture/blob/5bbe49d4c92746076196216c3f74e08ae509809a/src/viz/layers/cpp/inc/viz/layers/quad_layer.hpp) owns native layer composition; [VizCompositor](https://github.com/NVIDIA/IsaacCapture/blob/5bbe49d4c92746076196216c3f74e08ae509809a/src/viz/session/cpp/viz_compositor.cpp) drops shared projection only if every visible layer is native. This can improve text/panel clarity and allow client reconstruction; the comments give qualitative benefits, not a >30Hz benchmark. Native quads are flat, no depth; mixed 3D scene retains projection. Existing installed Televiz supports GPU array interface but its ProjectionLayer.submit documents one CUDA→CUDA copy per buffer plus blocking cudaStreamSynchronize. «Zero-copy CUDA↔Vulkan» means shared owned storage interop, **not** zero copies from arbitrary Isaac camera producer or zero waits.

Prefer upload-only preview A/B before replacing Kit composition. Any later Televiz route must preserve one OpenXR owner, Kit physical-to-world transform/nav semantics, scene identity and controller-source receipts. A camera-only headset changes user experience substantially and must be explicitly scoped; native layers do not by themselves keep the canonical immersive scene.

## Ordered ablations the root can test

| Priority | Reversible change | Preserves | Required distinguishing receipt |
|---|---|---|---|
| 1 | Client2048×1792→1792×1536; then1536×1280; refresh72 fixed | All3 dataset cameras/source/action graph | Client bundle hash, final config, actual server eye/RP size; per-role fresh frames/s |
| 2 | Runtime env `NV_MAX_FPS=0/45/50` | Scene/camera/label semantics | Native max-fps log/readback, app/control/render/new camera cadence versus client display rate |
| 3 | GPU preview upload-only helper | Existing partitions/source cache/layout/control | GPU-upload call counts/times, same image producer identities, representative Quest visual correctness |
| 4 | Preview hidden but dataset products live | Tracking/actions/all3 camera production | Camera generation/encoded frames unchanged; demonstrates preview cost only |
| 5 | XR resMultiplier .8/.65, warped peripheral/inset choices | Dataset sensor geometry | XRSettings readback, actual XR RP resolution; dataset RP settings/pixels unchanged |
| 6 | Opaque runtime `NV_DISABLE_ALPHA=1` only if XR blend mode opaque | Source images/action semantics | Current mode/encoded alpha streams; no user-visible alpha loss |
| 7 | waitIdle=false + immutable surface/state receipt path | Bound image lag, source identity | Actual GPU event completion/producer frame ID; lag distribution; no inferred same-frame image |
| 8 | Pipelined worker after paired receipt adapter | Source intent once per returned generation | Repeated result/no-reapply tests, reference/reset barrier, bounded source age |
| 9 | Package upgrade/native quad composition | Only after explicit composition audit | Exact ABI/version, one OpenXR owner, physical-to-world correctness; projection work still counted |

For every case measure actions wallHz **and separate counts for every3 fresh live camera**, packet count after drain, novel producer frame IDs, image lag p50/p95/max, loss/coalescing, decision→native command identity. A high render-loop/callback count without novel sensor samples is not success. No-client fixture can screen same loadedXR overhead (~50 wallHz criterion) but **does not** load connectedQuest eye encode/network/decode or prove>30 final. Archive failed cases and exact source hashes, avoid promoting any here.

## Mandatory upstream/reuse and finish disposition

CAPABILITY/GATE: exploratory XR cost reduction for live3-camera acquisition, adjacentS2/D0/D1; no gate state change. PINNED CANDIDATES: KitXR109.1, CloudXR6.2.1, IsaacTeleop1.4.98rc1; public v1.4.145 examined separately. UPSTREAM OWNS: OpenXR/session/worker/renderer/provider/encoder. GAP: preview host copies, version-specific eye pacing, immutable source/output correspondence for async. ADAPTER: only disposable upload-only method adapter; no project framework. ENVIRONMENT: existing SDK untouched. CONTRACT/EVIDENCE/ARTIFACT REGISTRATIONS: none by this specialist; root owns consolidated experiment/index registration. TESTS: compile and CPU fake-provider smoke only. HUMAN EVIDENCE: none. BLOCKERS: actual headset3-view+writer throughput unknown; no public benchmark matching goal. Root continues root-serialized GPU ablations and governance checks on consolidated docs.

## Final canonical startup audit (read-only; important for root ablations)

Installed `IsaacLab/apps/isaaclab.python.xr.openxr.kit` already sets **app.asyncRendering=true**, **app.asyncRenderingLowLatency=true**, and **omni.replicator.asyncRendering=false**. These are three distinct flags. Any startup ablation must pass exact Kit flags before AppLauncher initializes XR (`--/app/asyncRendering=...`, `--/app/asyncRenderingLowLatency=...`, `--/omni/replicator/asyncRendering=false`) through the launcher's Kit argument mechanism, with resolved-settings readback. Do not toggle app async rendering after XR activation. Enabling it is not a new optimization if canonical experience is already loaded. Keep the replicator flag false for external camera rendering as the shipped comment requires. This is installed local source, not an upstream default claim.

Canonical dependencies are `omni.kit.xr.core`, `omni.kit.xr.system.openxr`, `omni.kit.xr.ui.window.profile`, `omni.kit.scene_view.xr`, `omni.kit.scene_view.xr_utils`, plus `omni.fabric.commands`; `_enable_teleop_bridge()` dynamically enables `isaacsim.kit.xr.teleop.bridge`, sets `/persistent/xr/openxr/disableInputBindings=true`, and sets its OpenXR component enabled. The experience explicitly avoids `omni.kit.xr.bundle.generic` (not shipped/offline resolution fails) and removed `omni.kit.xr.profile.ar` (Kit110 replacement is profile window).

The active profile defaults to `ar`, with AR renderQuality=performance and nearPlane=.15. The headless experience inherits the regular XR experience but deliberately does NOT set `/xr/profile/ar/enabled` in the .kit file: `TeleopSessionLifecycle._ensure_xr_ar_profile_enabled()` enables it only after bridge extensions have loaded, then Kit picks it up next loop tick. Early profile enabling bypasses bridge callbacks and invalidates canonical ownership.

A no-client screening case should use this same experience/dependency/bridge/profile path and record profile requested/enabled state, live Kit XR handles, whether OpenXR session is running, CloudXR process state, three actual sensor products and SceneUI feeds. A loaded extension with no valid/running session is a different overhead scope. Do not label absent-client streaming/eye encoding cost as connected-XR cost. Preserve these distinctions in metrics, including whether same-profile initialization waits for form-factor availability.
