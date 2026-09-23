# Live camera temporal and cost audit

Experiment only, owner `vr.performance`. See [REPORT](REPORT.md).
Source branch SHA: `0f67ad49c8d129e5f2420f1f685088baf0d4d792`.
No canonical selection, environment pins, or gate acceptance changes.

The isolated launcher is `tools/camera_audit/launch.py`. Raw runs, including failed
setups, are retained under `/data/ebulochkin/vla-runtime/evidence/20260924_live_camera_temporal_cost_audit`.
Each launch retains argv, source hashes, effective configuration, stdout/stderr,
GPU samples and all measured controls; content probes additionally retain pixels.
