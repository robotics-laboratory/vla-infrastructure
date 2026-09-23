# Live camera temporal and cost audit

Experiment only, owner `vr.performance`. See [REPORT](REPORT.md).
Source branch SHA: `0f67ad49c8d129e5f2420f1f685088baf0d4d792`.
No canonical selection, environment pins, or gate acceptance changes.

The isolated launcher is `tools/camera_audit/launch.py`. Raw runs, including failed
setups, are retained under `/data/ebulochkin/vla-runtime/evidence/20260924_live_camera_temporal_cost_audit`.
Each launch retains argv, source hashes, effective configuration, stdout/stderr,
GPU samples and all measured controls; content probes additionally retain pixels.


The completed [report](REPORT.md), [matched distributions](pooled.json),
[per-run results](results.json), [temporal histograms](temporal-results.json),
[cohort checks](cohort-check.json) and [provenance](provenance.json) are frozen
experiment evidence. No raw RGB/HDF payload is committed.

Use fresh output directories for each independent process. Primary diagnostic
commands (append `--batch` for the upstream three-view owner):

```sh
python tools/camera_audit/launch.py --mode xr-smoke --cost c0 --warmup 300 --measured 3000 --output /data/ebulochkin/vla-runtime/evidence/camera-audit-new-c0 --state-root /data/ebulochkin/vla-runtime/isaac-isaac61
python tools/camera_audit/launch.py --mode xr-smoke --cost c3 --warmup 300 --measured 300 --output /data/ebulochkin/vla-runtime/evidence/camera-audit-new-c3 --state-root /data/ebulochkin/vla-runtime/isaac-isaac61
python tools/camera_audit/launch.py --mode xr-smoke --temporal t6-prime-extraction --cost c3 --batch --warmup 300 --measured 3000 --output /data/ebulochkin/vla-runtime/evidence/camera-audit-new-prime --state-root /data/ebulochkin/vla-runtime/isaac-isaac61
```

The current C3 path is temporally invalid and its short timings are diagnostic.
The report gives physical Quest follow-up commands. The pinned simulator Python
can reproduce tables/figures without Kit startup:

```sh
MPLCONFIGDIR=/tmp/camera-audit-mpl /data/vla-infrastructure/isaac61_production/env/bin/python tools/camera_audit/summarize.py /data/ebulochkin/vla-runtime/evidence/20260924_live_camera_temporal_cost_audit /tmp/camera-audit-reproduced
```

`control-distributions.csv` retains every measured control used by the figures.
Temporal content assays and timing workloads are separate and explicitly labelled.
Historical results are not pooled into any current-branch figure.
