// Per-process diagnostic using public CUDA12.8/CUPTI headers; no symbol interposer.
// Runtime callback COPIES SCALARS ONLY. CUDA driver calls occur outside callbacks.
// Keep this DSO and source-owning bounded queue anchored through Kit close.
#include <cuda.h>
#include <cuda_runtime_api.h>
#include <cupti.h>
// cupti.h includes generated_cuda_runtime_api_meta.h (no separate include guard).
#include <dlfcn.h>
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <mutex>

struct Receipt {
    std::uint64_t event, context, source, width, height, pitch;
    int matched_calls, copy_result, fence_status;
};
struct Scope {
    bool active=false, awaiting_exit=false;
    int entries=0, error=0;
    std::uint32_t correlation=0;
    CUcontext entry_context=nullptr;
    Receipt receipt{};
};
static thread_local Scope scope;
static std::atomic<std::uint64_t> actual_callbacks{0};
struct Driver {
    decltype(&cuCtxPushCurrent) push=nullptr;
    decltype(&cuCtxPopCurrent) pop=nullptr;
    decltype(&cuEventCreate) create=nullptr;
    decltype(&cuEventRecord) record=nullptr;
    decltype(&cuEventQuery) query=nullptr;
    decltype(&cuEventDestroy) destroy=nullptr;
    bool available=false;
};
static Driver driver;
static CUpti_SubscriberHandle subscriber=nullptr;
static int subscription_status=-1;
static std::once_flag init_flag;

static void CUPTIAPI capture(void*, CUpti_CallbackDomain domain,
                            CUpti_CallbackId id, const void* raw) {
    if (!scope.active || domain!=CUPTI_CB_DOMAIN_RUNTIME_API
        || id!=CUPTI_RUNTIME_TRACE_CBID_cudaMemcpy2DToArray_v3020 || !raw) return;
    // These are documented public callback and generated API parameter types.
    const auto& data=*static_cast<const CUpti_CallbackData*>(raw);
    if (!data.functionParams) { scope.error=-8; return; }
    const auto& p=*static_cast<const cudaMemcpy2DToArray_v3020_params*>(data.functionParams);
    auto& r=scope.receipt;
    if (reinterpret_cast<std::uintptr_t>(p.src)!=r.source) return;
    if (p.width!=r.width || p.height!=r.height || p.spitch!=r.pitch
        || (p.kind!=cudaMemcpyDeviceToDevice && p.kind!=cudaMemcpyDefault)) scope.error=-3;
    if (data.callbackSite==CUPTI_API_ENTER) {
        ++scope.entries;
        if (scope.awaiting_exit || scope.entries!=1) scope.error=-3;
        scope.awaiting_exit=true;
        scope.correlation=data.correlationId;
        scope.entry_context=data.context;  // May be null before runtime init.
    } else if (data.callbackSite==CUPTI_API_EXIT) {
        ++r.matched_calls;
        ++actual_callbacks;
        if (!scope.awaiting_exit || data.correlationId!=scope.correlation
            || r.matched_calls!=1) scope.error=-8;
        scope.awaiting_exit=false;
        if (!data.functionReturnValue) { scope.error=-8; return; }
        r.copy_result=static_cast<int>(*static_cast<const cudaError_t*>(data.functionReturnValue));
        if (r.copy_result!=static_cast<int>(cudaSuccess)) scope.error=-4;
        if (!data.context || (scope.entry_context && scope.entry_context!=data.context)) scope.error=-6;
        r.context=reinterpret_cast<std::uintptr_t>(data.context);
    } else scope.error=-8;
    // NO CUDA/CUPTI calls, allocations, logging or retained callback pointers.
}

static void init() {
    void* lib=dlopen("libcuda.so.1",RTLD_NOW|RTLD_LOCAL);
    if (!lib) { subscription_status=-5; return; }
#define LOAD(field, symbol) driver.field=reinterpret_cast<decltype(driver.field)>(dlsym(lib,symbol))
    LOAD(push,"cuCtxPushCurrent_v2"); LOAD(pop,"cuCtxPopCurrent_v2");
    LOAD(create,"cuEventCreate"); LOAD(record,"cuEventRecord");
    LOAD(query,"cuEventQuery"); LOAD(destroy,"cuEventDestroy_v2");
#undef LOAD
    driver.available=driver.push && driver.pop && driver.create && driver.record
        && driver.query && driver.destroy;
    if (!driver.available) { subscription_status=-5; return; }
    // Explicit library path required: no implicit competing CUPTI version choice.
    const char* path=std::getenv("VLA_CUPTI_LIBRARY");
    if (!path || !*path) { subscription_status=-9; return; }
    void* cupti=dlopen(path,RTLD_NOW|RTLD_LOCAL);
    if (!cupti) { subscription_status=-9; return; }
    auto subscribe=reinterpret_cast<decltype(&cuptiSubscribe)>(dlsym(cupti,"cuptiSubscribe"));
    auto enable=reinterpret_cast<decltype(&cuptiEnableCallback)>(dlsym(cupti,"cuptiEnableCallback"));
    auto unsubscribe=reinterpret_cast<decltype(&cuptiUnsubscribe)>(dlsym(cupti,"cuptiUnsubscribe"));
    if (!subscribe || !enable || !unsubscribe) { subscription_status=-9; return; }
    auto status=subscribe(&subscriber,capture,nullptr);
    subscription_status=static_cast<int>(status);
    if (status!=CUPTI_SUCCESS) return; // Including exclusive-subscriber error39.
    status=enable(1,subscriber,CUPTI_CB_DOMAIN_RUNTIME_API,
                  CUPTI_RUNTIME_TRACE_CBID_cudaMemcpy2DToArray_v3020);
    subscription_status=static_cast<int>(status);
    if (status!=CUPTI_SUCCESS) { unsubscribe(subscriber); subscriber=nullptr; }
    // Libraries/subscriber stay owned for process lifetime; no destructor calls.
}
// Optional early owned subscription before Kit initializes its memory tracker.
// Resolves driver functions and subscribes only: no source or CUDA context calls.
extern "C" int vla_copy_probe_init() {
    std::call_once(init_flag,init);
    if (subscription_status!=0 || !driver.available)
        return subscription_status>0 ? -1000-subscription_status : subscription_status;
    return 0;
}
extern "C" int vla_copy_probe_begin(std::uint64_t source, std::uint64_t width,
                                    std::uint64_t height, std::uint64_t pitch) {
    if (scope.active || !source || !width || !height || pitch<width) return -1;
    std::call_once(init_flag,init);
    if (subscription_status!=0 || !driver.available)
        return subscription_status>0 ? -1000-subscription_status : subscription_status;
    scope=Scope{};
    scope.receipt={0,0,source,width,height,pitch,0,-1,-2};
    scope.active=true;
    return 0;
}
extern "C" int vla_copy_probe_end(Receipt* out) {
    if (!scope.active || !out) return -1;
    scope.active=false; // Already outside provider/runtime callback.
    auto& r=scope.receipt;
    if (scope.error || scope.entries!=1 || scope.awaiting_exit
        || r.matched_calls!=1 || r.copy_result!=0 || !r.context) {
        r.fence_status=scope.error ? scope.error : -8;
        *out=r; return -2;
    }
    auto context=reinterpret_cast<CUcontext>(static_cast<std::uintptr_t>(r.context));
    auto status=driver.push(context);
    if (status!=CUDA_SUCCESS) { r.fence_status=static_cast<int>(status); *out=r; return -2; }
    CUevent event=nullptr;
    status=driver.create(&event,CU_EVENT_DISABLE_TIMING);
    if (status==CUDA_SUCCESS) {
        r.event=reinterpret_cast<std::uintptr_t>(event);
        status=driver.record(event,CU_STREAM_LEGACY);
    }
    r.fence_status=static_cast<int>(status);
    CUcontext popped=nullptr;
    auto restore=driver.pop(&popped);
    if (restore!=CUDA_SUCCESS || popped!=context) r.fence_status=-7;
    *out=r;
    return r.fence_status==0 && r.event ? 0 : -2;
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
extern "C" int vla_copy_probe_query(std::uint64_t event,std::uint64_t context) {
    return visit_event(event,context,false);
}
extern "C" int vla_copy_probe_release(std::uint64_t event,std::uint64_t context) {
    return visit_event(event,context,true);
}
// Compatibility metrics: this route counts ACTUAL matched EXIT callbacks, not lookups.
extern "C" std::uint64_t vla_copy_probe_intercepted_lookups() { return actual_callbacks.load(); }
extern "C" std::uint64_t vla_copy_probe_competing_bindings() { return 0; }
extern "C" std::uint64_t vla_copy_probe_receipt_size() { return sizeof(Receipt); }
extern "C" int vla_copy_probe_cupti_status() { return subscription_status; }
