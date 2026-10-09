# OVRTX GPU consumer: integration and actual ownership

Prepared132→138line helper, AST-only; author did NOT run GPU. It reuses exact corrected `pynv223_adapter.py`, does not replace encoder architecture. Copy helper AND sibling `live30-ovrtx-gpu-consumer.preimages.json`; if renaming them, update MANIFEST filename. Existing SDK/adapter byte hashes guarded; requires OVRTX0.5.1.385782, Warp1.16.0, PyNv2.2.3.

Integration in `SnapshotRenderer.capture(self,snapshot,*,consumer=None)`:

```python
# Existing CPU branch stays the default.
if consumer is None:
    with frame.render_vars[self.render_var].map(device=ovrtx.Device.CPU) as mapping:
        view = np.from_dlpack(mapping)
        image = view.copy()
        del view
    if image.shape[:2] != (self.height,self.width):
        raise RuntimeError(...)
    images.append(image)
else:
    info = consumer(role,frame.render_vars[self.render_var],source_id=snapshot.source_id)
    images.append(None)
    consumer_receipts.append(info)
```

Initialize `consumer_receipts=[]` before loop; include this list in returned metadata. Rename timing bucket readback_ms to output_consumer_ms in GPU mode (or explicitly attach output_mode); its CPU-host submission duration is NOT measured pure GPU latency. Preserve sequential scene apply→publication→renderer.step completion; do NOT turn this into a concurrent ovstage mutation pipeline.

In driver instantiate GPUConsumer only AFTER renderer/stage initialization (OVRTX runtime-first ordering). Three sessions use same explicit non-null Warp stream and CUDA primary context. Pass consumer to capture. When GPU mode, skip inline `witness.decode(image)` and `.npy` saving for None images. Keep every source snapshot row/camera capture metadata and per-consumer receipts. After loop, `consumer.finish()` BEFORE mirror.close/renderer.detach/destroy, including exception cleanup. Save consumer.receipt after finish; include drain time in sustained workload accounting. Decode all3H264 files offline using softwareffmpeg and existing geometric witness decoder; compare decodedrow androle against exactHDF/request ledger. Warmup frames were encoded too, so decoder starts at row0, not row30.

Producer order, based on actual installedsource:

1. OVRTX render_var.map(Device.CUDA,sync_stream=consumer_stream) inserts wait on renderer ProducerDone. `_src/types.py:833` map; `:552` wait_event.
2. `_src/dlpack.py:656` explicitly IGNORES __dlpack__(stream). Therefore wp.from_dlpack alone is NOT sufficient synchronization. Explicit map wait is essential.
3. Warp `_src/dlpack.py:460` imports mapped memory without copy; dtypeuint8/shape600x960x4/contiguous/samedevice guarded. `ScopedStream(...sync_enter=False,sync_exit=False)` prevents unrelated cross-stream waits; explicit source dependency already exists. `wp.clone` context.py:9202 allocates independent memory and enqueues copy on selectedstream. A clone_done event is recorded and retained with ownedframe.
4. `PyNvEncoder.cpp:684` copies suppliedCUDAframe into encoder-owned input using m_CUstream. NvEncoderCuda.cpp:136 uses cuMemcpy2DAsync whenstreamnonnull. `PyNvEncoder.cpp:308` constructs NvCUStream; PyNvEncoder.hpp:35–61 makes input/outputstream equal suppliedstream and calls SetIOCudaStreams. This establishes copy→NVENC CUDA input processing order. No conversion to a different unknown defaultstream.
5. Warp mappedview is deleted aftercloneenqueue; mapping stays alive until unmap(stream=consumer_stream). OVRTX types.py:584 unmap preserves sync hint; `:651` destructor passes it to nativeunmap after consumer capsules gone. This permits asynchronous GPU source read, not immediate unsafe release.
6. `CudaRGBAFrame.owner` owns clone; `clone_done` event attached. PacketEncoder.pending is keyed by LOCAL encoder ordinal and retainsframe until outputpacketACK. Underlying NvEncoder_130.cpp:697 overwrites inputTimeStamp with localcounter. SourceTag ledger is metadata only. Consumer checks pending<8 beforenewallocation;3×8×960×600×4 gives55.296MB max retainedsourcepixels, plusrenderer/encoder allocations. This is bounded ownedqueue, NOT preallocated zero-allocationring; optimization later must preserve ACK lifetime.
7. Success path has no CPU/devicewide synchronization. Error cleanup and finaldrain synchronize only selectedstream; emergency references retainowners even if PacketEncoder.finish clears its pending duringfailure. Renderer must stay alive until consumer finished, or it may force-unmap outstandingnativebuffers.

Unmap streamhint may itself have implementation cost; measure unmap_host_ms. It is currently afterEncoder.submit, so its stream boundary includes submittedNVENC work. If that dominates, a separate reviewed ablation can unmap immediatelyaftercloneenqueue with clone_done event, beforeNVENCsubmission, sinceNVENC reads ownedclone. Do NOT merely drop hint. The C++ native scheduling cost of unmap is not inferred from Python wrapper.

CUDA_DEVICE_MAX_CONNECTIONS1 must be processenvironment BEFORE first CUDA context. Official OVRTX Linuxdoc describes Vulkan scheduling bubbles under CUDA stream waits; lowering connections fixes measuredupstreamcases but reduces CUDAstreamparallelism. Run unset/1 matchedA/B. https://nvidia-omniverse.github.io/ovrtx/core/cuda_vulkan_scheduling.html . This is a classification/hypothesis until currentGPU comparison, not an asserted speedup.

CPUmap16.334ms in priorprobe includes possibleGPUcompletionwaiting/formatstaging; it is not evidence of16ms PCIeDMA. GPUclone+NVENC may move waiting to encoder submission or renderer.step. Compare whole measuredworker+drain, all3decodedcounts, allopticalsourcephases, queuebound and roleidentity. Faster enqueuing alone does not establish50Hz completedframes or activeQuest>30.
