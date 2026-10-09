# Actual Nsight capture analysis: corrected trace

Research diagnosis only: no connected Quest, no IK, no physical qualification or dataset admission. The corrected parent-run capture passed 60 warmup and 120 measured control ticks. Its wall rate was **32.9646 Hz**, mean **30.3356 ms**, p95 **33.0939 ms**, maximum **198.0963 ms**. The comparable untraced GPU receipt was 39.309 Hz / 25.4395 ms, but different duration and contention prevent treating the difference as an isolated tracing-overhead measurement.

The actual trace supports prioritizing GPU PhysX completion/dispatch and repeated Fabric publication. Explicit Hydra wait-idle, packet polling and NVENC CPU API calls are smaller measured costs. Inclusive nested scopes must **not be added together**.

| Main-thread scope | Instances/control | Inclusive ms/control |
|---|---:|---:|
| `fetchResults::waitForCompletion` | 4 | **9.8144** |
| `fetchResults::updateRenderTransforms` | 4 | 3.6011 |
| `FabricManager::update` | **5** | **4.3987** |
| `sim_render` | 1 | 9.7030 |
| `hydraRenderingThread` | 1 | 7.2516 |
| `RtxHydraEngine::updatePreUsd` | 1 | 4.0167 |
| `pullUpdatesFromFabric` | 1 | 2.5114 |
| `/app/hydraEngine/waitIdle` | 1 | **0.5106** |
| Python `get_annotator_data` | 3 | 0.4989 |
| Custom `state_D2H` | 2 | 0.4468 |

Every individual control contains exactly five Fabric scopes, four transform-update scopes and four blocking physics-completion scopes. The three non-rendering substeps contain 360 Fabric updates totaling **329.9115 ms / 120 = 2.7493 ms/control**. The fourth/rendering substep contains two updates per control, totaling 197.9302 ms. This quantifies the work targeted by the boundary experiment; it does not promise a speedup because catch-up work and scheduling can change.

The 198.0902 ms NVTX outlier at control 160 contains a 175.4347 ms `sim_render`, versus 9.6459 ms combined physics-completion waits. An approximately 166.7 ms main-thread futex and native Hydra scopes coincide. The trace locates the stall in rendering, but does not prove profiler flushing, external contention, or another native event caused it. The outlier remains in deadline/throughput statistics. Hydra CPU scopes are not GPU RTX execution durations.

## CUDA dispatch and synchronization

There are **144,600 kernels = 1,205/control**, and **138,000 `cuLaunchKernel` calls = 1,150/control**. Summed device kernel intervals total 904.9864 ms, or 7.5416 ms/control. Stream overlap means this sum is neither a critical path nor GPU utilization.

Largest kernel sums: `artiSolveInternalConstraintsTGS1T` 212.0283 ms; `artiSolveInternalTendonAndMimicJointConstraints1T` 179.2393 ms; `stepArticulation1TTGS` 74.9904 ms; `artiPropagateRigidImpulsesAndSolveSelfConstraintsTGS1T` 72.7895 ms. The first two occur 8,640 times each, or 18 instances/native integration. Stream 31 holds 94,560 kernels and 714.2549 ms summed work. This supports testing CPU physics for the small articulated scene and inspecting native TGS/tendon/mimic work. Solver changes require physics validation; timing alone does not authorize reducing accuracy.

Main-thread API durations per control: `cuStreamSynchronize` 0.4091 ms, `cudaStreamSynchronize` 0.1857 ms, `cuEventSynchronize` 0.0733 ms. These calls may contain waits and are nested in broader scopes. Their scale is much smaller than native fetch completion. GPU Boolean/`.item()` checks and `.cpu().numpy()` copies in the separate IK path remain synchronization risks; IK was disabled here and cannot explain this capture.

Device copy intervals sum to 97.4969 ms D2H, 9.7750 ms H2D and 4.1685 ms D2D. **360 D2H copies of 4,608,256 bytes** dominate: 1,658,972,160 bytes and 87.9766 ms, or 0.7331 ms/control summed device-copy time. Size equals `960*600*8+256`, suggesting capacity-sized native encoder staging. The trace alone does not identify buffer ownership. Used H.264 packet length can differ from transfer allocation capacity; source confirmation is required.

## Vulkan, NVENC and scheduler limitations

`nvEncEncodePicture`: 360 calls totaling25.0301 ms, or0.2086 ms/control; map-input3.0315 ms total; stream setup0.4935 ms. These are CPU API durations, **not NVENC hardware completion**. Diagnostics explicitly say GPU video acceleration tracing is unsupported and no GPU video accelerator events were collected.

`vkQueueSubmit`: 2,880 calls /29.1196 ms total. `vkWaitForFences`: 220 calls /0.4830 ms total. There are561 `VULKAN_WORKLOAD` records across contexts1 and2, but their coarse batched intervals overlap heavily, with aggregate durations exceeding capture wall time many times. The Vulkan GPU-marker summary is empty. This does not establish absent GPU rendering; it prevents fine RTX/PhysX overlap attribution or GPU render-utilization estimates.

Main-thread futex totals1,527.8621 ms. Large cross-thread futex totals include idle workers. Background `Rate limit sleep` spans nearly the capture on other threads, not the control thread; it does not prove control-loop pacing. CPU scheduling/perf sampling was disabled/unavailable; Nsight warns inferred thread activity is inaccurate. The host has one NUMA node; no NUMA advantage is established. Process-only thread/affinity experiments remain possible, with no measured benefit claimed.

## Source-bound Fabric experiment

Pinned `SimulationContext.step` calls the physics manager then optionally renders. Pinned `PhysxManager.step` directly calls native `simulate` then blocking `fetch_results`; `forward` updates articulation kinematics and Fabric. Installed Fabric settings expose `/physics/fabricEnabled` plus transformation/joint/velocity switches. Binding docstrings expose `update`, `force_update`, attach/detach, save-to-USD and a pre-initialization kinematic-transform switch. No selective automatic-fetch-callback disable API was found. `force_update` means update without a preceding simulation step; it does not establish bypass of the enabled-state gate.

Core `SimulationManager.step(update_fabric=False)` is a different implementation and is not substituted. Attach/detach belongs to stage lifecycle/resume synchronization and is not proposed per integration. Persistent transformation-update disabling can leave camera poses stale.

`/tmp/live30-fabric-boundary.py` is a 72-line, process-local experimental adapter. `install(env)` returns `(receipt, restore)`. Exact SHA256 guards cover installed SimulationContext, PhysxManager, native Fabric binding binary, binding API markdown and settings source. It requires120 Hz, render span4, initial render phase0, Fabric enabled and the expected manager. Within `_advance(4)` only, it sets Fabric false during the first three `sim.step(render=False)` calls, restores true before the fourth `sim.step(render=True)`, checks native physics count+4 and FFFT flags, and restores settings in all `finally` paths. Other repeats pass through. Exact instance attributes are restored by the returned function. No SDK or driver changes.

CPU fake-object checks PASS for actual installed hashes, FFFT gating, counters, original return preservation, injected exception propagation, settings and instance-attribute restoration. See `/tmp/live30-fabric-boundary-cpu-check.stdout.log`. **Native gating, catch-up, current joint/contact data and rendered camera poses remain unqualified until runtime checks pass.** Expected experiment receipt is3 disabled steps and1 enabled boundary step per group; a trace must prove native Fabric scopes fall5→2. Pixel/body pose and source identity must still match the fourth-step boundary. This is a testable hypothesis, not a source-proven publication guarantee.

## Actual commands and retained receipts

Original corrected trace: `/data/ebulochkin/vla-runtime/live30-deep-20261009/full-gpu-nsight-registered-trace.nsys-rep`. Original receipt/performance: sibling `full-gpu-nsight-registered/result.json` and `performance.jsonl`. Launcher log/args: `.log` and `.launch.json`. Capture range spans3,651.0272 ms and120 control ranges. All CPU analysis outputs were written under `/tmp`:

```sh
nsys export --type=sqlite --output=/tmp/live30-nsight-registered.sqlite /data/ebulochkin/vla-runtime/live30-deep-20261009/full-gpu-nsight-registered-trace.nsys-rep
nsys stats --report cuda_api_sum,cuda_gpu_kern_sum,cuda_gpu_mem_time_sum,nvtx_sum,osrt_sum,vulkan_api_sum,vulkan_gpu_marker_sum,nvvideo_api_sum --format csv --output /tmp/live30-nsight-registered /tmp/live30-nsight-registered.sqlite
python /tmp/live30-nsight-analyze.py
```

Commands exited0. Export reported1,782,858 events; its progress excerpt is transcribed in JSON, not represented as a complete redirected raw log. Statistics stdout is retained at `/tmp/live30-nsight-stats-command.stdout.log`; analyzer stdout at `/tmp/live30-nsight-analysis-command.stdout.log`; all individual CSVs at `/tmp/live30-nsight-registered_*.csv`. `/tmp/live30-nsight-analysis.json` contains SHA256s, original runtime JSON, full diagnostic events, per-control native counts/durations, top API/kernel summaries and CSV contents. Analyzer source is `/tmp/live30-nsight-analyze.py` and uses SQLite read-only mode.

Nsight used legacy CUDA software instrumentation and warns potentially incomplete main-process NVTX/CUDA/OSRT/Vulkan events. A child process has no CUDA/NVTX events. No CPU scheduling information and no GPU video accelerator timeline were collected. The observer counts and native per-control invariants support the bounded findings above, not an exact all-engine critical path. No connected Quest or IK overhead is measured here. This analysis agent executed no GPU operations.

## Preserved initial failure

Initial run: `/data/ebulochkin/vla-runtime/live30-deep-20261009/full-gpu-nsight`, started2026-10-09T13:41:36Z, finished13:41:54Z. GPU execution belongs to root. This analyzing agent performed only read-only source/log inspection and wrote outputs under `/tmp`.

## Initial capture failed

The application result is PASS and its `profiler` receipt records180 control starts and expected wrappers:720 writes/updates per robot,540 nonrender sim steps,180 render sim steps,180 renders. The recorded workload was120 measured controls after60 warmup, no XR/IK, CUDA physics, Minimal rendering,3×960×600 native H264 packet polling. Runtime wall mean26.14141ms, p9529.13520ms, max85.25947ms; these are instrumented host timings, not GPU timing.

The Nsight log ends:

```text
Processing events...
Generated:
        No reports were generated
```

Expected `full-gpu-nsight-trace.nsys-rep` is absent. There is consequently no captured CUDA/Vulkan/NVENC/Kit timeline to analyze. Do not report trace statistics as zero or use the successful runtime result as proof of profiling success.

Likely cause is a confirmed command omission: ordinary NVTX strings are not capture triggers under Nsight's registered-only default. Installed Torch `torch/cuda/nvtx.py:34` calls `_nvtx.rangePushA(msg)`, and the observer uses that API. The initial launch specifies `--capture-range=nvtx --nvtx-capture=live30_capture` without the required matching environment override. [NVIDIA NVTX capture rule](https://docs.nvidia.com/nsight-systems/UserGuide/index.html#profiling-from-the-cli).

Correction for a new preserved run:

```text
--env-var=NSYS_NVTX_PROFILER_REGISTER_ONLY=0
--nvtx-capture=live30_capture@*
```

The first recommended command omitted the environment option; that omission is now corrected in the scheduler audit. The corrected run described above succeeded. The initial failure is preserved as a profiling failure, not an application workload failure.

## Analysis provenance and limitations

`/tmp/live30-nsight-analysis.json` retains the initial runtime JSON, exact source/log/launch digests and failure alongside the corrected analysis. No command ran against a nonexistent trace. No kernel/driver policy changes were performed.
