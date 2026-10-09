"""CPU-only, read-only analysis of the already-recorded live30 trace."""

import csv
import hashlib
import json
import pathlib
import sqlite3

ROOT = pathlib.Path("/data/ebulochkin/vla-runtime/live30-deep-20261009")
SQLITE = pathlib.Path("/tmp/live30-nsight-registered.sqlite")
OUT = pathlib.Path("/tmp/live30-nsight-analysis.json")
prior = json.loads(OUT.read_text())
initial = {k: v for k, v in prior.items() if k != "corrected_capture"}
db = sqlite3.connect(f"file:{SQLITE}?mode=ro", uri=True)
db.row_factory = sqlite3.Row


def query(sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


name = "coalesce(n.text,s.value)"
ranges = query(f"""SELECT {name} name,n.start,n.end,n.globalTid
  FROM NVTX_EVENTS n LEFT JOIN StringIds s ON s.id=n.textId
  WHERE {name}='live30_capture' AND n.end IS NOT NULL""")
assert len(ranges) == 1, ranges
window = ranges[0]
tid = window["globalTid"]
controls = query(f"""SELECT {name} name,n.start,n.end FROM NVTX_EVENTS n
  LEFT JOIN StringIds s ON s.id=n.textId WHERE {name} LIKE 'control:%'
  AND n.end IS NOT NULL ORDER BY n.start""")
assert len(controls) == 120
nframes = len(controls)


def aggregate(table, field="nameId", main=False, limit=30):
    where = "WHERE n.globalTid=?" if main else ""
    return query(
        f"""SELECT s.value name,count(*) count,
      sum(n.end-n.start)/1e6 sum_ms,avg(n.end-n.start)/1e6 mean_ms,
      max(n.end-n.start)/1e6 max_ms FROM {table} n
      JOIN StringIds s ON s.id=n.{field} {where}
      GROUP BY s.value ORDER BY sum(n.end-n.start) DESC LIMIT {limit}""",
        (tid,) if main else (),
    )


nvtx = query(
    f"""SELECT {name} name,count(*) count,
  sum(n.end-n.start)/1e6 sum_ms,avg(n.end-n.start)/1e6 mean_ms,
  max(n.end-n.start)/1e6 max_ms FROM NVTX_EVENTS n
  LEFT JOIN StringIds s ON s.id=n.textId WHERE n.globalTid=?
  AND n.end IS NOT NULL GROUP BY {name} ORDER BY sum(n.end-n.start) DESC""",
    (tid,),
)
selected_names = [
    "fetchResults::waitForCompletion",
    "fetchResults::updateRenderTransforms",
    "fetchResults::transformationUpdateCallback",
    "FabricManager::update",
    "DirectGpuHelper::updateRigidBodies",
    "sim_render",
    "AppUpdate",
    "/app/hydraEngine/waitIdle",
    "sim_step:render=False",
    "sim_step:render=True",
    "state_D2H",
    "get_annotator_data",
    "RtxHydraEngine::updatePreUsd",
    "pullUpdatesFromFabric",
    "postSync",
    "hydraRenderingThread",
]
selected = [
    r
    for r in nvtx
    if r["name"] in selected_names
    or any(
        x in (r["name"] or "")
        for x in [
            "waitIdle",
            "pullUpdatesFromFabric",
            "updatePreUsd",
            "hydraRenderingThread",
            "get_annotator_data",
        ]
    )
]
for r in selected:
    r["sum_ms_per_control"] = r["sum_ms"] / nframes
fabric_events = query(
    f"""SELECT {name} name,n.start,n.end FROM NVTX_EVENTS n
 LEFT JOIN StringIds s ON s.id=n.textId WHERE n.globalTid=?
 AND {name} IN ('FabricManager::update','fetchResults::updateRenderTransforms',
 'fetchResults::waitForCompletion','sim_render') AND n.end IS NOT NULL""",
    (tid,),
)
for ctl in controls:
    ctl["duration_ms"] = (ctl["end"] - ctl["start"]) / 1e6
    contained = [r for r in fabric_events if ctl["start"] <= r["start"] and r["end"] <= ctl["end"]]
    ctl["native_counts"] = {
        nm: sum(r["name"] == nm for r in contained)
        for nm in [
            "FabricManager::update",
            "fetchResults::updateRenderTransforms",
            "fetchResults::waitForCompletion",
            "sim_render",
        ]
    }
    ctl["native_sum_ms"] = {
        nm: sum(r["end"] - r["start"] for r in contained if r["name"] == nm) / 1e6
        for nm in ctl["native_counts"]
    }
copies = query("""SELECT e.label copy_kind,n.bytes bytes_per_copy,count(*) count,
 sum(n.bytes) total_bytes,sum(n.end-n.start)/1e6 sum_ms FROM CUPTI_ACTIVITY_KIND_MEMCPY n
 JOIN ENUM_CUDA_MEMCPY_OPER e ON e.id=n.copyKind GROUP BY n.copyKind,n.bytes
 ORDER BY sum(n.end-n.start) DESC""")
counts = {
    t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    for t in [
        "CUPTI_ACTIVITY_KIND_KERNEL",
        "CUPTI_ACTIVITY_KIND_RUNTIME",
        "CUPTI_ACTIVITY_KIND_MEMCPY",
        "CUPTI_ACTIVITY_KIND_MEMSET",
        "NVTX_EVENTS",
        "VULKAN_API",
        "VULKAN_WORKLOAD",
        "NVVIDEO_ENCODER_API",
        "OSRT_API",
    ]
}
kernel_total = query("""SELECT count(*) count,sum(end-start)/1e6 sum_ms
 FROM CUPTI_ACTIVITY_KIND_KERNEL""")[0]
vulkan = query("""SELECT gpu,contextId,count(*) count,min(start) start,max(end) end,
 sum(end-start)/1e6 sum_ms FROM VULKAN_WORKLOAD GROUP BY gpu,contextId""")
sources = []
for p in [
    ROOT / "full-gpu-nsight-registered-trace.nsys-rep",
    SQLITE,
    ROOT / "full-gpu-nsight-registered/result.json",
    ROOT / "full-gpu-nsight-registered/performance.jsonl",
    ROOT / "full-gpu-nsight-registered.log",
    ROOT / "full-gpu-nsight-registered.launch.json",
    pathlib.Path(__file__),
]:
    if p.exists():
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        sources.append({"path": str(p), "bytes": p.stat().st_size, "sha256": h.hexdigest()})
csv_reports = {}
for p in sorted(pathlib.Path("/tmp").glob("live30-nsight-registered_*.csv")):
    with p.open() as f:
        csv_reports[p.stem] = list(csv.DictReader(f))
actual = {
    "status": "trace_exported_and_analyzed",
    "capture_window": window,
    "duration_ms": (window["end"] - window["start"]) / 1e6,
    "control_count": nframes,
    "main_global_tid": tid,
    "table_counts": counts,
    "runtime_result": json.loads((ROOT / "full-gpu-nsight-registered/result.json").read_text()),
    "sources": sources,
    "cuda_api_all_threads": aggregate("CUPTI_ACTIVITY_KIND_RUNTIME"),
    "cuda_api_main_thread": aggregate("CUPTI_ACTIVITY_KIND_RUNTIME", main=True),
    "cuda_kernel_top": aggregate("CUPTI_ACTIVITY_KIND_KERNEL", "demangledName"),
    "cuda_kernel_total": kernel_total,
    "cuda_streams": query("""SELECT deviceId,contextId,streamId,count(*) count,
 sum(end-start)/1e6 sum_ms FROM CUPTI_ACTIVITY_KIND_KERNEL GROUP BY deviceId,contextId,streamId
 ORDER BY sum(end-start) DESC"""),
    "memory_copies_by_kind_and_size": copies,
    "native_main_thread_selected": selected,
    "native_main_thread_top": nvtx[:80],
    "controls": controls,
    "main_osrt": aggregate("OSRT_API", main=True),
    "nvvideo_api": aggregate("NVVIDEO_ENCODER_API"),
    "vulkan_api": aggregate("VULKAN_API"),
    "vulkan_workload_groups": vulkan,
    "diagnostics": query("SELECT * FROM DIAGNOSTIC_EVENT"),
    "nsys_csv_reports": csv_reports,
    "commands": [
        {
            "command": "nsys export --type=sqlite --output=/tmp/live30-nsight-registered.sqlite "
            + str(ROOT / "full-gpu-nsight-registered-trace.nsys-rep"),
            "exit_code": 0,
            "observed_stdout_excerpt": "Exported 1782858 events; export reached 100%",
            "receipt_note": "Excerpt transcribed from actual tool output; complete original progress was not redirected.",
        },
        {
            "command": "nsys stats --report cuda_api_sum,cuda_gpu_kern_sum,cuda_gpu_mem_time_sum,nvtx_sum,osrt_sum,vulkan_api_sum,vulkan_gpu_marker_sum,nvvideo_api_sum --format csv --output /tmp/live30-nsight-registered /tmp/live30-nsight-registered.sqlite",
            "exit_code": 0,
            "outputs": list(csv_reports),
        },
        {
            "command": "python /tmp/live30-nsight-analyze.py",
            "output": "/tmp/live30-nsight-analysis.json",
        },
    ],
    "interpretation_limits": [
        "All native NVTX sums are inclusive and overlapping; never add them to obtain a critical path.",
        "Cross-thread OSRT sums include idle worker waits, not solely control-thread blocking.",
        "CUDA device sums overlap streams and do not establish elapsed device utilization.",
        "Vulkan workload intervals are coarse batches with extensive overlap; no fine RTX GPU marker attribution.",
        "GPU video accelerator trace is unsupported: API durations do not measure NVENC hardware occupancy.",
        "No CPU scheduling/perf sampling; legacy CUDA instrumentation and potentially incomplete event warnings.",
        "No XR, no IK in this capture. It does not measure connected Quest overhead.",
        "Tracing run differs in duration/conditions from untraced receipt; the throughput difference is not an isolated overhead measurement.",
    ],
}
initial["corrected_capture"] = actual
OUT.write_text(json.dumps(initial, indent=2) + "\n")
print(
    json.dumps(
        {
            "output": str(OUT),
            "controls": nframes,
            "capture_ms": actual["duration_ms"],
            "fabric_count_distribution": {
                str(k): sum(c["native_counts"]["FabricManager::update"] == k for c in controls)
                for k in sorted({c["native_counts"]["FabricManager::update"] for c in controls})
            },
            "kernel_count": kernel_total["count"],
            "kernel_summed_ms": kernel_total["sum_ms"],
            "largest_control": max(controls, key=lambda x: x["duration_ms"]),
        },
        indent=2,
    )
)
