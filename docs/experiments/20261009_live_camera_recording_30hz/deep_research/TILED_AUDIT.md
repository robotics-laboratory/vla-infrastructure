# Isaac Sim 6.1: native three-camera atlas, GPU crops and renderer alternatives

Read-only audit and CPU-only helper validation, accessed 2026-10-09. Assigned checkout `/home/ebulochkin/vla_infrastructure`, branch `research/live-camera-recording-30hz`, HEAD `d5566834d29ef8bb56e4fb62bb324e23e0869100`; pre-existing untracked `deep_research/`. No GPU run, package installation, SDK write, physical action or gate qualification. Temporary deliverables are `/tmp/live30-tiled-probe.py`, this memo and `/tmp/live30-deep-tiled.json`. Sources already discussed in `live30-deep-render.md` and `live30-deep-media.md` are referenced only where needed for the new exact-layout/probe conclusions.

## Decision for root's next serialized experiment

Test **one native atlas against three independent render products** on the same Piper scene and moving per-camera witnesses. Use a fresh diagnostic process for each configuration. Three sensors do not imply three render products: the native API accepts existing USD cameras and renders an atlas, retaining distinct camera intrinsics and mounts. However, savings from fewer renderer products can be offset by padding, gathering and encoder costs; the installed source explicitly says tiled rendering is most performant for many low-resolution sensors. Three 960×600 cameras are therefore a measured candidate, not a promised optimization.

The parent-reported 73.72 wall Hz full CPU PhysX plus three native compressed polls was not executed or independently qualified by this audit. Use that concrete pipeline as the first comparison. Tiling is worthwhile if it improves the **complete control + rendering + encode + write + drain** result with the same XR composition, fidelity and witness checks.

Public [6.1 API reference](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/py/source/extensions/isaacsim.sensors.experimental.rtx/docs/index.html) establishes the authoring/runtime split and `get_data(annotator, tiled=True, out=...)`. The local installed source resolves its exact layout and constructor side effects. An older migration guide shows `(W,H)` in examples; **do not copy that order into this installed API**: native sensor resolution is `(600,960)`, Replicator tile resolution is `(960,600)`.

## Exact three-view geometry and optics

Installed `TiledCameraSensor._initialize_sensor` computes rows `round(sqrt(3))=2`, columns `(3+2−1)//2=2`. Kit110.3 Replicator independently computes two columns and two rows. Thus RGBA8 native output is **(1200,1920,4)**, row pitch **7680 bytes**, and allocation **9,216,000 bytes**. Three packed RGBA images total 6,912,000 bytes. The fourth tile contributes 33.3% extra atlas area; it is not a fourth camera and must not enter role counts or dataset crops.

Row-major tile offsets in bytes from an owned contiguous atlas are `0`, `3840`, and `4,608,000`; the unused tile starts at `4,611,840`. For a 960×600 subview, use row stride 7680, pixel stride 4, channel stride 1. There are two important ordering authorities: the actual `sensor.camera.paths` and render product's USD `camera` relationship. Read and compare them; map roles by observed path identity rather than assuming a regex preserves left/right/scene construction order. The new helper retains an explicit role→path map and derives indices from actual relationship targets.

Heterogeneous focal lengths, principal points, distortion schemas, per-camera transforms and rigid mount parents remain camera-prim properties. A single shared tile resolution does **not** require identical camera calibration. There are constructor hazards:

* Passing a path list causes `SensorRuntime` to create `Camera(paths)` with `reset_xform_op_properties=True`. Pass a pre-wrapped `Camera(paths, reset_xform_op_properties=False)` for existing vendor mounts.
* Native `TiledCameraSensor` calls `enforce_square_pixels(..., modes="horizontal")` for **every camera**, updating vertical aperture if it disagrees with the output aspect ratio. It does not overwrite all focal lengths with the last camera's values, but it can still change calibrated vertical FOV. The helper rejects that mutation before constructing the sensor and checks a full camera attribute/schema/local-transform signature afterward.
* For genuine nonsquare-pixel calibration, use direct `rep.create.render_product_tiled(existing_paths, tile_resolution=(960,600))`: that path avoids the Camera wrapper and aperture enforcement. Test distortion projection and image parity against three products; no source-only claim of identical lens behavior.
* Tiled dimensions are shared session configuration. Replicator documents that a single tiled resolution is allowed per session. Do not introduce another differently sized tiled batch while XR/previews already own a tiled product.

The helper refuses camera render products already bound to any of the three cameras, to avoid accidentally rendering both the old three products and the new atlas. `reject_existing_products=False` is available for deliberate overlap diagnostics, but those timings must be identified as such. It creates products in the USD session layer; no geometry/mount change is performed by the helper.

## GPU extraction and encoding choices

Native `get_data("rgba", tiled=True)` returns the native atlas alias without a detile kernel. `out=owned_gpu_array` performs a GPU copy into the supplied atlas. Default `tiled=False` launches `_wk_reshape_tiled_image` to gather into `(3,600,960,4)`; use that upstream kernel if contiguous per-camera inputs are required. RGB uses the RGBA annotator but slices alpha away, producing a potentially strided three-channel view. For direct packed ABGR input, request **RGBA** and preserve four channels.

The new helper allocates owned CUDA arrays once, obtains later native fetches with `tiled=True,out=...`, and provides pointer/pitch views through `cuda_views()`. It checks that incoming arrays are CUDA Warp uint8 and rejects host payloads. It uses one conservative `wp.synchronize_device` per distinct device to complete the owned copy. This is a baseline; replacing it with producer/copy events and a bounded owned-buffer ring is a separately measured optimization. Capture sequence is explicitly a fetch sequence; it is not a native renderer source-frame ID.

Three encoding paths should be kept distinct:

1. **Atlas → one stock compressed LdrColor session.** Helper `mode="tiled",payload="h264"` attaches one compressed annotator to the atlas RP; no raw GPU/CPU acquisition is requested. Output is one 1920×1200 stream. Decode and crop its first three tiles into the semantic camera roles later. This candidate is available within the installed environment; runtime encoder support and frame phase still require the serialized probe. It encodes the unused fourth tile and may exhibit cross-tile compression effects. It does not produce three independent streams.
2. **Owned atlas → three pitched CUDA subviews → three PyNvVideoCodec sessions.** API accepts GPU input and ABGR, but the exact Python binding's arbitrary-pitch behavior is untested. [PyNvVideoCodec encoder API](https://docs.nvidia.com/video-technologies/pynvvideocodec/pynvc-api-reference/encoder.html) describes GPU input; exact downloaded 2.2.3 samples are the authority for its runtime calling protocol, because the web signatures and packet-return descriptions differ from that wheel. Crucially, `AppFrame.cuda()` returns an **object with `__cuda_array_interface__`**, not a raw dictionary. The previous `/tmp/live30-pynv223-adapter.py` returns a dictionary and needs correction before a GPU trial; parent was informed. The new `CudaSubview.cuda()` returns itself with that interface. No encoder is constructed here. The earlier environment audit found PyNvVideoCodec absent from the declared environment; pitched three-session encoding therefore remains an environment-reviewed follow-up, while stock atlas compression requires no such package.
3. **Atlas → GPU detile/copy → three contiguous input buffers.** This preserves no raw host staging and is the conservative fallback if pitched input is rejected. NVIDIA's [NvEncoderCuda reference source](https://raw.githubusercontent.com/NVIDIA/video-sdk-samples/master/Samples/NvCodec/NvEncoder/NvEncoderCuda.cpp) accepts independent source pitch and copies width×height via CUDA_MEMCPY2D into encoder-owned buffers. It establishes an upstream D2D crop path, not exact PyNvVideoCodec behavior or zero-copy registration. Reuse the upstream detile kernel or SDK crop copy instead of implementing a renderer.

CUDA contexts and device ordinals must match the actual atlas device. An integer pointer from another device/context is not a valid encoder input merely because the shape is correct. Retain the atlas allocation until all three sessions consume their inputs; `release(capture)` only means the caller has finished consumption. Never enqueue a mutable alias then reuse it while a worker is still pending. Persist all actual copies and synchronization in the timing/metadata receipt. [NVENC programming guide](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html) remains the contract for input resource ownership and session capabilities.

## Frame witness, batch and subframe semantics

The helper subscribes to `GLOBAL_EVENT_DRAWABLE_CHANGED` and records frame number, device mask and optional subframe count from the event's result handle. This is an observer only. [HydraTexture 1.6.2 API](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.hydra_texture/1.6.2/omni.kit.hydra_texture/omni.kit.hydra_texture.IHydraTexture.html) documents render-completion metadata. Its presence improves diagnosis, but a latest event copied alongside a polled annotator still does not independently prove which source state its pixels depict.

Bind moving source witnesses to each camera crop; a scene-only cube may be invisible to wrist cameras. Decode **every crop**, recover source ticks, require monotonically advancing source IDs, establish bounded lag and bind RGB to saved state/action history at its recovered producer generation. Identical image hashes of a static scene are allowed and prove neither freshness nor staleness. Configuration signatures should include renderer mode/shading mode, temporal effects, camera optics/mounts/tick rates, RP relationship targets/resolution/AOVs, XR eye settings, exact source hashes, device routing and scheduler mode.

More Replicator `rt_subframes` renders the same paused simulation state for quality/settling. Installed `orchestrator.step` says simulation is paused during those subframes, and its setting is bounded below by `/omni/replicator/RTSubframes`. Consequently `rt_subframes=1` cannot undo a larger global minimum. Subframes do not turn one action state into multiple fresh observations. Batch view rendering reduces products/dispatch; it does not reduce the required three distinct camera projection results. For a like-for-like trial, retain the same FFFT/control scene and first compare the minimal subframe setting, then separately quantify extra settling needed after reset/material changes.

## Multi-GPU, instancing, AOVs and fidelity

[RTX multi-GPU guidance](https://docs.omniverse.nvidia.com/materials-and-rendering/latest/rtx-renderer_pt.html) describes image-space distribution and primary-GPU aggregation/denoising; it improves pixel rendering, not physics/animation, and may choose one GPU at low resolution. These observations limit a small three-camera trial; they do not establish that routing each RP to a separate GPU is faster.

The installed `SimulationApp` exposes `active_gpu` as physical renderer index and `active_cuda_gpus` as CUDA indices honoring CUDA_VISIBLE_DEVICES; they cannot be combined. Physics GPU is separate. Its source hashes belong in the ledger because the local package may contain prior approved changes, rather than being byte-identical stock. Replicator's public `render_product_tiled` has no device-mask parameter, and its installed HydraTexture wrapper does not forward arbitrary engine_options. A lower-level HydraTexture test creates an engine with `device_mask=1`; implementing per-product routing requires a separate lower-level experiment and explicit mapping of renderer mask to CUDA encode context. Do not mutate an opaque resource or infer NVIDIA-SMI ordinal equivalence.

Instancing can reduce geometry memory/traversal preparation but cannot remove three camera rays/view transforms. Keep the imported Piper and vendor mounts unchanged for this audit; a geometry-instancing conversion is not a clean tiling ablation. Request only RGBA/LdrColor for RGB experiments. Depth, normals, segmentation and other AOVs can add graph/renderer work. Conversely, turning off rendering and leaving only depth AOVs does not satisfy the RGB goal.

[RTX Minimal documentation](https://docs.omniverse.nvidia.com/materials-and-rendering/latest/rtx-renderer_minimal.html), updated 2026-10-08, explicitly removes indirect light transport, uses only the first distant light and hard shadows, and optionally ambient lighting. The **installed numeric mapping** is `0=No Rendering`, `1=Constant Diffuse`, `2=Texture Diffuse`, `3=Diffuse/Glossy/Emission`. Thus the parent's mode 2 retains diffuse texture appearance; it omits glossy/emission evaluation. Record those quality changes and compare color/occlusion/task cues to [RTX Real-Time 2.0](https://docs.omniverse.nvidia.com/materials-and-rendering/latest/rtx-renderer_rt.html) before selecting it for training data. A throughput win does not make the render distribution equivalent to the selected VR composition.

OptiX is a programmable **ray-tracing** engine, not a turnkey rasterized replacement for Omniverse's USD scene/material/sensor pipeline. NVIDIA's [OptiX overview](https://developer.nvidia.com/rtx/ray-tracing/optix?ncid=em-nurt-245273-vt33) and [SDK download page](https://developer.nvidia.com/designworks/optix/download) establish that it requires application shaders/scene integration; current 9.1 page requires R590, while the media audit lists host R580. Do not choose current OptiX by name and assume compatibility. Writing a new USD→OptiX or Vulkan renderer would recreate substantial camera/material/geometry synchronization responsibilities and violate the reuse ladder without a demonstrated gap. Native Minimal is the immediate supported low-light-transport candidate; a stock raster Hydra engine would need separately demonstrated sensor/AOV/MDL/XR compatibility, which this audit did not find.

## Probe usage and qualification limits

Import after application startup, using the existing diagnostic camera prim paths:

```python
import importlib.util
spec = importlib.util.spec_from_file_location("live30_tiled", "/tmp/live30-tiled-probe.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
probe = module.ThreeCameraProbe({
    "left_wrist": left_camera_path, "right_wrist": right_camera_path,
    "scene": scene_camera_path}, mode="sensor", payload="rgba")
# Existing scene/control loop owns app/physics pumping and producer history.
capture = probe.capture(producer_metadata=actual_boundary_metadata)
if capture is not None:
    gpu_views = probe.cuda_views(capture)
    # Consume in matching CUDA context; keep all inputs alive until consumption.
    probe.release(capture)
probe.close()
```

Separate processes should test: separate/h264 baseline; tiled/h264 single atlas; sensor/rgba (native owned out buffer); tiled/rgba (unchanged optics path); separate/rgba. Native sensor/raw does not establish encoder throughput. No-Quest ~50 Hz is screening; active Quest3 strictly >30 action Hz and fresh RGB Hz per camera remains the qualification target. All failed attempts, empty warm-up/post-warm-up payloads, producer phase, queue/drain time, decode counts and camera roles need retained records.

Mandatory implementation audit: capability is diagnostic comparison, no gate state changed; candidates are pinned installed TiledCameraSensor, Replicator and compressed LdrColor; upstream owns rendering, tiling, extraction and encoding; remaining gap is measured role ordering/lifetime/source alignment; adapter is 269 LOC and confined to one experiment; no environment change; no project framework or recorder replacement. CPU `compile`, import, CAI metadata protocol, and `git diff --check` passed. Ordinary `py_compile` hit a pre-existing `/tmp/__pycache__` ownership failure; in-memory compile avoided writing there. No GPU claim follows from those checks. Repo documentation registration and trusted-base lint are the parent's integration responsibility; these temporary files are not gate evidence.
