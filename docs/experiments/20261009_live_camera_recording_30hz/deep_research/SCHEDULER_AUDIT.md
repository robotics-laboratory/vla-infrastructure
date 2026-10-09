# Scheduler and profiling audit: Piper live camera recording

2026-10-09; checkout `/home/ebulochkin/vla_infrastructure`, branch `research/live-camera-recording-30hz`, HEAD `d5566834d29ef8bb56e4fb62bb324e23e0869100`. Read-only SDK/host inspection, public primary-source research and a temporary instrumentation observer. No GPU execution, physical action, installation, SDK edit, global driver change or gate claim. The parent owns GPU execution and the existing untracked research bundle. Kind: scoped experiment research, owner: data.collection.live_camera_performance, destination: parent bundle after review. No independent gate/evidence registration implied.

## Decision supported by actual receipts

The actual bounded synthetic runs below exclude Quest and IK, use Minimal rendering and native H264 packet polling, and explicitly state camera-source alignment is unproven. They are not the same configuration as active Quest. They identify where to profile, not final throughput qualification.

| Receipt under `/data/ebulochkin/vla-runtime/live30-deep-20261009/` | wall mean / p95 | wall Hz | summed sim_step mean | target writes mean | robot updates mean |
|---|---:|---:|---:|---:|---:|
| `full-gpu-poll-r6/result.json` | 25.43948 / 32.09790 ms | 39.30898 | 19.18865 ms | 0.74061 ms | 0.65264 ms |
| `full-cpu-poll-contention/result.json` | 13.56474 / 18.86420 ms | 73.72054 | 8.51637 ms | 0.74420 ms | 0.41075 ms |

Both include 120 warmup + 300 measured controls, 299 measured start-to-start intervals. CPU and GPU were separate runs under external contention, so the 11.87474 ms difference is observational, not an isolated causal backend speedup. Retain source hashes, launch receipts and contention state for any comparison.

GPU requires at least 5.43948 ms mean reduction to reach the 20 ms/50 Hz screening budget. Its two bookkeeping buckets together are only 1.39325 ms, so even their impossible complete elimination leaves 24.04623 ms. Recording commit + successor capture averages 3.29942 ms; eliminating the writer alone cannot establish 50 Hz either. `sim_step` contains physics + fourth-substep rendering; it must be split before attributing 19.18865 ms to PhysX. Camera update is 0.00416 ms because this probe does not use live canonical Camera extraction, while packet polling is inside `simulation_advance`. None of these numbers proves canonical camera cost.

Critical reporting detail: logger `target_hz=50` makes its `wall_rtf=20ms/wall_mean`. This is the screening ratio, not physical simulation RTF: each control still advances four 1/120-second integrations = 33.33333 ms. Actual simulated-time RTF is approximately 1.31030 for GPU and 2.45735 for CPU. Preserve the original receipt; annotate the distinction instead of editing recorded data.

## Tools are already installed

Host `/usr/local/bin/nsys`: `NVIDIA Nsight Systems version 2025.6.3.541-256337736014v0`. Its own help supports CUDA, NVTX, OS runtime, Vulkan and NvVideo API tracing; this version does not list `openxr` trace, although newer public docs do. Do not use latest-only switches without local verification.

Installed Isaac Sim tree contains `skills/profile-isaac-sim/SKILL.md`, `libcarb.profiler-nvtx.plugin.so`, CPU/GPU/mux/Tracy profiler plugins, and Tracy extension `omni.kit.profiler.tracy-1.2.1+lx64` with `capture`, `csvexport`, GUI and trace import binaries. NVIDIA catalog fallback was checked after `npx` was unavailable; no profiling-specific catalog skill matched. The installed profiling skill is the applicable source. Its benchmark flags apply to its standalone benchmark scripts, not the custom Piper full-scene harness. The skill's interactive per-iteration approval workflow is overridden by the parent's existing research authorization.

`nsys status --environment` actually reports CPU process-tree/system-wide profiling FAIL: perf_event_open and trigger unavailable; `/proc/sys/kernel/perf_event_paranoid=4`. Initial capture uses no CPU sampling/context switches. No privilege/global sysctl change is necessary for API traces. Docker socket inspection was denied in the sandbox; no escalation attempted. A host `nsys profile docker exec ...` traces the Docker client, not the already-running Kit process. Profile the actual Python/Kit command in its namespace, mounting the existing Nsight installation read-only if needed; do not install a second copy merely to cross namespaces.

## Minimum useful capture

At Kit startup append these actual Carbonite settings:

```text
--/app/profilerBackend=nvtx
--/app/profileFromStart=true
```

The installed native NVTX backend can emit Kit zones to Nsight. See [Kit 110.3 profiler documentation](https://docs.omniverse.nvidia.com/kit/docs/kit-manual/110.3.0/guide/profiling.html). Avoid automatic Python-call tracing for the first capture: its instrumentation can expand files and perturb latency substantially.

For the existing Nsight version, launch the real process with:

```sh
NSYS_NVTX_PROFILER_REGISTER_ONLY=0 nsys profile --trace=cuda,nvtx,osrt,vulkan,nvvideo \
  --sample=none --cpuctxsw=none --vulkan-gpu-workload=batch \
  --cuda-graph-trace=graph --cuda-event-trace=false \
  --gpu-metrics-devices=none --gpu-video-devices=none \
  --capture-range=nvtx '--nvtx-capture=live30_capture@*' \
  --capture-range-end=stop --kill=none --force-overwrite=false \
  -o /data/PRIVATE_NEW_RUN/profile REAL_PYTHON REAL_PIPER_PROBE ARGS
```

`REAL_*` are explicit substitution points, not executable example paths. Output directory must be private/new. NVTX-controlled profiling stops collection while the application drains/finalizes normally. Batch Vulkan tracing is enough for the first overlap/wait diagnosis; individual workloads, CUDA event-completion tracing, Python GIL/sampling and CUDA backtraces are follow-up captures only if needed. Do not add `torch.cuda.synchronize()` at stage boundaries: it changes overlap and turns unrelated pending work into the apparent cost of whichever boundary waits first. This configuration is confirmed by installed CLI help, not executed here.

The separate `/tmp/live30-deep-profiler.py` uses the already installed `torch.cuda.nvtx`, not a new `nvtx` dependency. In the initialized benchmark, after creating `perf`, the final experimental `env._advance` wrapper and optional IK object:

```python
spec = importlib.util.spec_from_file_location("live30_profiler", "/tmp/live30-deep-profiler.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
observer = module.install(env, perf, warmup=args.warmup, frames=args.frames, ik=ik)
# Run existing transitions unchanged.
# In finally, before restoring other runtime adapters:
receipt["profile_observer"] = observer.receipt()
observer.restore()
```

The observer starts `live30_capture` on the first `perf.begin_step` after warmup and closes it after the requested frame count. It marks full controls, existing named stages, sim.render, render/nonrender sim.step, both robot writes/updates, camera boundary, state readback and optional IK. It wraps only Python object instances, preserves return values and prior attributes, and adds no tensor inspection, GPU fence, render pump or control-state mutation. Installation is transactional. It assumes paired serial begin/end calls in this synthetic harness; an incomplete/reentrant control raises instead of producing misleading ranges. Install after other wrappers, restore before them. AST and CPU fake-NVTX checks PASS; real GPU runtime/overhead untested.

Post-process using report names confirmed by installed `nsys stats --help-reports`:

```sh
nsys stats --report cuda_api_sum,cuda_gpu_kern_sum,cuda_gpu_mem_time_sum,nvtx_sum,osrt_sum,vulkan_api_sum,vulkan_gpu_marker_sum,nvvideo_api_sum /data/PRIVATE_NEW_RUN/profile.nsys-rep
```

Aggregate totals are not additive critical-path costs. Inspect the timeline and source control ranges. In particular, `nvvideo` traces CPU NVENC API calls such as encode and bitstream lock; it does not itself prove hardware encode occupancy. The optional `--gpu-video-devices` feature is system-wide. Driver 580.159.03 exceeds the documented old GSP restriction threshold, so disabling firmware to profile would be unjustified. Hardware counter/video support and permissions remain untested. [Nsight Systems guide](https://docs.nvidia.com/nsight-systems/UserGuide/index.html).

## How to interpret the trace

| Observed pattern | Next concrete test | What would falsify the hypothesis |
|---|---|---|
| Long `vkWaitForFences` / queue idle on main thread with graphics preceding it | Inspect Hydra waitIdle and source-ready fences, count actual render products, isolate fourth render step | GPU is actually saturated during the entire interval; flag removal only shifts the same wait to readback |
| Vulkan queue bubbles while outstanding CUDA stream/event waits exist | New process A/B `CUDA_DEVICE_MAX_CONNECTIONS=1`, same source/scene/XR/media settings | Queue bubbles or wall time unchanged; CUDA stream concurrency reduction worsens physics |
| Main thread blocks at tiny D2H / `_local_scalar_dense` while GPU finishes earlier submissions | Consolidate device validation/state/IK transfers into one source-bound packed readback | Small transfers not on critical path or packed readback saves little |
| CPU write/submit gap precedes idle GPU, native task waits/mutexes dominate | P-core affinity and startup worker-count A/B; then narrow Python sampling | GPU busy, no CPU starvation, or restricting workers increases waits |
| `nvEncLockBitstream` occupies control/render thread | Move packet output lock/drain to persistent output worker with ownership fences | Existing lock already runs off critical path or output queue steadily grows |
| RTX/dataset/XR graphics full occupancy while NVENC API lightweight | Lower only XR eye cost or improve dataset renderer scheduling/fidelity experiment | Lowering eye work has no wall benefit, or overhead is `xrWaitFrame`/input wait rather than rendering |

NVENC uses a dedicated engine but can share memory bandwidth and input conversion/copy scheduling with graphics. PhysX CUDA and RTX Vulkan are still one-device workloads. Therefore nominal engine independence is not measured overlap, and summed CUDA kernel time is not GPU frame cost. Packet generation throughput must be measured with the simultaneous graphics workload. Keep the external Jupyter GPU allocation/workload described by the parent visible in receipts; this agent cannot see those processes in its PID namespace and did not infer whether they were compute-active from VRAM allocation alone.

The documented Linux OVRTX CUDA/Vulkan scheduling interaction is unusually relevant: outstanding CUDA waits can cause graphics scheduling gaps. Its process-start `CUDA_DEVICE_MAX_CONNECTIONS=1` workaround serializes CUDA hardware queues and is a hypothesis for Kit, not a proven Kit fix. Set before the first CUDA context and restart to roll back. The alternative CPU-side event wait sacrifices overlap. [OVRTX scheduling source](https://nvidia-omniverse.github.io/ovrtx/core/cuda_vulkan_scheduling.html). Existing physics audit already covers the same candidate; this audit adds the trace criteria that distinguish it from generic utilization claims.

## CPU scheduling: pinned source overrides generic handbook defaults

Observed CPU is i7-13700K, 24 logical CPUs, one NUMA node. `lscpu -e` shows CPUs 0–15 as eight HT cores with 5.3–5.4 GHz maximum and CPUs 16–23 as eight single-thread cores with 4.2 GHz maximum. Calling them P/E cores is an inference from this topology and processor specification; current clocks were not sampled. Process allowed CPUs are 0–23, memory node 0. NUMA placement offers no alternate node here. Governors read `powersave` for CPU0 and CPU16; that is not proof that active cores stay slow.

Pinned `isaacsim.simulation_app/simulation_app.py:122,178,489–499` defaults `limit_cpu_threads=16`, then appends both Carbonite/TBB thread flags and sets PXR_WORK_THREAD_LIMIT / OPENBLAS_NUM_THREADS. The code uses `os.cpu_count()` despite the comment saying physical cores. The online handbook's generic default32 is not this installed pin. Inspect actual runtime settings and command order; do not assume `taskset` changes `os.cpu_count()` or that CLI duplicate precedence is known. Choose at process construction, never mutate initialized worker pools.

Reversible screening options, one variable at a time: startup Carbonite/TBB 8 versus16; physics CPU workers0 versus2 versus4; process affinity `taskset -c 0-15` versus all24. A process-wide mask affects XR/encoder/workers too, so P-core-only is not guaranteed faster. Once the thread timeline identifies the control thread, more selective thread affinity could preserve worker throughput. No SCHED_FIFO, governor write, isolation boot parameter or firmware change is needed for first tests.

Carbonite supports startup `threadAffinity` (array length exactly threadCount), `recordTaskCounts` and `resetFiberStack`; all are present in the installed binary. If `useOmniJob=true`, its upstream job pool owns worker count and Carbonite's count is ignored. Disabling task counts / stack reclamation could reduce scheduler bookkeeping but trades debugging/memory behavior and should follow a measured task hotspot. [Carbonite tasking settings](https://docs.omniverse.nvidia.com/kit/docs/carbonite/206.14/docs/tasking/TaskingSettings.html). The exact toolkit and thread controls are confirmed by local hashes in the source manifest.

## AsyncSim is not the async renderer flag

Current pinned PhysicsManager.step calls native `simulate(dt,0)` followed immediately by blocking `fetch_results()` for each of four integrations. Installed PhysX Python binding says `simulate` is asynchronous, while fetch is the completion boundary. Upstream PhysxScene `updateType=asynchronous` is a timeline/stage-update ownership mode; it is documented as most suitable when Python need not run every step. That conflicts with this direct four-substep control loop unless explicitly redesigned. It cannot be assumed to defer these explicit fetch calls or preserve labels/state boundaries. Never enable another timeline physics step concurrently with direct stepping. [Physics performance and async mode](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/latest/dev_guide/guides/physics-performance.html), [PhysX API](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/107.0/extensions/runtime/source/omni.physx/docs/api/python.html).

Current XR experience already sets app.asyncRendering and app.asyncRenderingLowLatency true while Replicator asyncRendering is false for external cameras. A concurrent renderer may consume earlier state; changing a flag requires retained capture source identity and ready/consumed fences. The VR and physics audits cover those semantics; this observer deliberately does not alter them.

## Small-transfer synchronization audit

`tools/isaac_s2_runtime.py:142–180` IK separately performs finite-check bool read and two desired/clipped CPU reads per arm, and pre-action pose seed also copies each arm to CPU. The branch condition on a CUDA boolean synchronizes. `tools/run_isaac_s1.py:310–312,581–590` copies each robot state to CPU separately. The input/native target path creates CPU-to-device tensors from NumPy every action. Source identity checks must remain serial at their declared boundary; an optimization may pack both arms and finite/saturation metadata, use one preallocated transfer and inspect after its completion, without reconstructing actuator output as labels.

Preview frame `.item()` and synchronous RGBA staging were covered by the XR audit. A CUDA `.item()`, `.cpu()`, or NumPy conversion can wait for prior work even when only one scalar moves. Trace caller and synchronization stack before attributing the full wait to PCIe bandwidth. For scale only, three 960×600 RGBA buffers are 6.912 MB per control =345.6 MB/s at50Hz, arithmetic rather than measured bandwidth. Repeated fence latency and graphics ownership are more plausible first hypotheses than exhaustion of bulk transfer bandwidth, but need measurement.

## Separate Tracy capture when native CPU tasks dominate

Start Kit with `--/app/profilerBackend=tracy --/app/profileFromStart=true` and enable `omni.kit.profiler.tracy`. Installed capture syntax:

```sh
/data/vla-infrastructure/isaac61_production/env/lib/python3.12/site-packages/isaacsim/extscache/omni.kit.profiler.tracy-1.2.1+lx64/bin/capture -o /data/PRIVATE_NEW_RUN/tasking.tracy -s 15
```

Attach only after warmup, retain all original application inputs, and use its matching csvexport binary. Local csvexport defaults comma; the installed benchmark wrapper defaults tab. Specify `-s` explicitly and parse accordingly. Use `-e` for self-time, not a sum of parent+child zones. Python `carb.profiler.begin/end` scopes and flow/frame/value markers are installed public bindings. The observer uses torch NVTX, so a Tracy-only pass will need native `carb.profiler` scopes if its extra Python markers are desired. Do not silently claim NVTX scopes appear in Tracy.

## Remaining uncertainty

No actual Nsight/Tracy capture or GPU collector permission test was executed here. Native Vulkan workload attribution, XR frame wait, actual worker/job settings, CUDA event ownership, camera freshness and encoder busy intervals remain unknown. CPU no-XR73.7Hz is promising but cannot be extrapolated to XR-active no-client50Hz or physical Quest>30Hz. Target proof still requires all three native960×600 source-bound camera streams, eligible actions, bounded declared lag, complete disk/drain/decode verification and simultaneous active Quest. No production source/config/evidence/artifact/gate state changed.


Actual profiling completed after adding `NSYS_NVTX_PROFILER_REGISTER_ONLY=0` at process start; Torch uses ordinary rangePushA strings. The original recommendation omitted this and produced no trace. See [actual analysis](NSIGHT_ANALYSIS.md), [Fabric work comparison](fabric_native_comparison.json), and [final report](REPORT.md). The preserved initial failure is not overwritten.
