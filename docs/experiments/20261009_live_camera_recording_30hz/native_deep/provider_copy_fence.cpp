// Diagnostic scoped interposer. Compile-only by author; GPU execution belongs to root.
// Uses published CUDA12.8 headers and Linux libdl; no proprietary object-layout ABI.
// Caller retains each source before begin and keeps it until query+release success.
// Missing/extra interception or any status error => retain all sources until Kit close.
// Caller MUST bound its live-event/source queue before begin (e.g. max12), failing
// closed or using finite retained-all fallback on exhaustion. No blocking CUDA fence.
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <cuda.h>
#include <cuda_runtime_api.h>
#include <dlfcn.h>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <mutex>

using Copy = decltype(&cudaMemcpy2DToArray);
using Dlsym = void* (*)(void*, const char*) noexcept;
static Dlsym next_dlsym() {
    static auto fn = reinterpret_cast<Dlsym>(dlvsym(RTLD_NEXT, "dlsym", "GLIBC_2.2.5"));
    return fn;
}
static std::atomic<Copy> original_copy{nullptr};
static std::atomic<std::uint64_t> intercepted_lookups{0};
static std::atomic<std::uint64_t> competing_bindings{0};

struct Receipt {
    std::uint64_t event, context, source, width, height, pitch;
    int matched_calls, copy_result, fence_status;
};
struct Scope { bool active=false; Receipt receipt{}; };
static thread_local Scope scope;
struct Driver {
    decltype(&cuCtxGetCurrent) current=nullptr;
    decltype(&cuCtxPushCurrent) push=nullptr;
    decltype(&cuCtxPopCurrent) pop=nullptr;
    decltype(&cuEventCreate) create=nullptr;
    decltype(&cuEventRecord) record=nullptr;
    decltype(&cuEventQuery) query=nullptr;
    decltype(&cuEventDestroy) destroy=nullptr;
    bool available=false;
};
static Driver driver;
static std::once_flag init_flag;
static void init_driver() {
    void* lib = dlopen("libcuda.so.1", RTLD_NOW|RTLD_LOCAL);
    auto lookup = next_dlsym();
    if (!lib || !lookup) return;
#define LOAD(field, symbol) driver.field = reinterpret_cast<decltype(driver.field)>(lookup(lib, symbol))
    LOAD(current, "cuCtxGetCurrent"); LOAD(push, "cuCtxPushCurrent_v2");
    LOAD(pop, "cuCtxPopCurrent_v2"); LOAD(create, "cuEventCreate");
    LOAD(record, "cuEventRecord"); LOAD(query, "cuEventQuery");
    LOAD(destroy, "cuEventDestroy_v2");
#undef LOAD
    driver.available = driver.current && driver.push && driver.pop && driver.create
        && driver.record && driver.query && driver.destroy;
}
extern "C" cudaError_t CUDARTAPI cudaMemcpy2DToArray(cudaArray_t dst, size_t x,
    size_t y, const void* src, size_t pitch, size_t width, size_t height, cudaMemcpyKind kind) {
    auto real = original_copy.load();
    if (!real) {
        auto lookup = next_dlsym();
        if (lookup) real = reinterpret_cast<Copy>(lookup(RTLD_NEXT, "cudaMemcpy2DToArray"));
        if (real && real != &cudaMemcpy2DToArray) original_copy.store(real);
    }
    if (!real || real == &cudaMemcpy2DToArray) return cudaErrorUnknown;
    const bool selected = scope.active && reinterpret_cast<std::uintptr_t>(src)==scope.receipt.source;
    CUcontext before=nullptr, after=nullptr;
    CUresult pre = CUDA_ERROR_NOT_INITIALIZED;
    if (selected && driver.available) pre=driver.current(&before);
    const auto result=real(dst,x,y,src,pitch,width,height,kind);
    if (!selected) return result;  // All unrelated CUDA calls remain unchanged.
    auto& r=scope.receipt;
    ++r.matched_calls; r.copy_result=static_cast<int>(result);
    // Do not change the original CUDA return value when diagnostic recording fails.
    if (r.matched_calls!=1 || width!=r.width || height!=r.height || pitch!=r.pitch
        || (kind!=cudaMemcpyDeviceToDevice && kind!=cudaMemcpyDefault)) { r.fence_status=-3; return result; }
    if (result!=cudaSuccess) { r.fence_status=-4; return result; }
    if (!driver.available || pre!=CUDA_SUCCESS || !before) { r.fence_status=-5; return result; }
    auto status=driver.current(&after);
    if (status!=CUDA_SUCCESS || before!=after) { r.fence_status=-6; return result; }
    r.context=reinterpret_cast<std::uintptr_t>(after);
    CUevent event=nullptr;
    status=driver.create(&event,CU_EVENT_DISABLE_TIMING);
    if (status!=CUDA_SUCCESS) { r.fence_status=static_cast<int>(status); return result; }
    r.event=reinterpret_cast<std::uintptr_t>(event);
    // The wrapped symbol is LEGACY cudaMemcpy2DToArray, not _ptds/Async.
    // Trace confirms null/default stream. Explicit published LEGACY constant
    // removes any compile-time default-stream macro ambiguity.
    status=driver.record(event,CU_STREAM_LEGACY);
    r.fence_status=static_cast<int>(status);
    return result;
}
extern "C" void* dlsym(void* handle, const char* symbol) noexcept {
    auto lookup=next_dlsym();
    if (!lookup) return nullptr;
    // RTLD_NEXT uses the return address of its caller. A verified tail jump
    // preserves the SDK caller for forwarding. Do not intercept RTLD_NEXT.
    if (handle==RTLD_NEXT || std::strcmp(symbol,"cudaMemcpy2DToArray")!=0)
        return lookup(handle,symbol);
    void* result=lookup(handle,symbol);
    if (result
        && result!=reinterpret_cast<void*>(&cudaMemcpy2DToArray)) {
        auto candidate=reinterpret_cast<Copy>(result);
        Copy previous=nullptr;
        if (original_copy.compare_exchange_strong(previous,candidate) || previous==candidate) {
            ++intercepted_lookups;
            return reinterpret_cast<void*>(&cudaMemcpy2DToArray);
        }
        // Never silently route another libcudart instance through the first one.
        ++competing_bindings;
    }
    return result;
}
extern "C" int vla_copy_probe_begin(std::uint64_t source, std::uint64_t width,
                                    std::uint64_t height, std::uint64_t pitch) {
    if (scope.active || !source || !width || !height || pitch<width) return -1;
    std::call_once(init_flag,init_driver);
    if (!driver.available) return -5;
    scope.receipt={0,0,source,width,height,pitch,0,-1,-2};
    scope.active=true;
    return 0;
}
extern "C" int vla_copy_probe_end(Receipt* out) {
    if (!scope.active || !out) return -1;
    *out=scope.receipt; scope.active=false;
    return out->matched_calls==1 && out->fence_status==0 && out->event ? 0 : -2;
}
static int visit_event(std::uint64_t event_value, std::uint64_t context_value, bool release) {
    if (!driver.available || !event_value || !context_value) return -1;
    auto context=reinterpret_cast<CUcontext>(static_cast<std::uintptr_t>(context_value));
    auto event=reinterpret_cast<CUevent>(static_cast<std::uintptr_t>(event_value));
    auto status=driver.push(context);
    if (status!=CUDA_SUCCESS) return static_cast<int>(status);
    status=driver.query(event);
    if (release && status==CUDA_SUCCESS) status=driver.destroy(event);
    CUcontext popped=nullptr;
    auto restore=driver.pop(&popped);
    if (restore!=CUDA_SUCCESS || popped!=context) return -7;
    return static_cast<int>(status);
}
extern "C" int vla_copy_probe_query(std::uint64_t event, std::uint64_t context) {
    return visit_event(event,context,false);
}
extern "C" int vla_copy_probe_release(std::uint64_t event, std::uint64_t context) {
    return visit_event(event,context,true);  // Refuses to destroy pending event.
}
extern "C" std::uint64_t vla_copy_probe_intercepted_lookups() { return intercepted_lookups.load(); }
extern "C" std::uint64_t vla_copy_probe_competing_bindings() { return competing_bindings.load(); }

extern "C" std::uint64_t vla_copy_probe_receipt_size() { return sizeof(Receipt); }
