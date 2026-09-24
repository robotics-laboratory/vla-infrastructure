# VR RECORD runtime optimization audit

Bounded experiment on `experiment/vr-record-runtime-optimization-audit`, starting
from `90e40ded79725d78b249245ab69ea93d024ef8e5`. The maintained entrypoint
for this bundle is [REPORT.md](REPORT.md). Raw per-process launches, timing rows,
native HDF recordings and setup failures live under
`/data/ebulochkin/vla-runtime/evidence/20260924_vr_record_runtime_optimization_audit/`.

The experiment keeps native 120 Hz physics, four integrations per logical control,
F,F,F,T rendering, disabled dataset RenderProducts and preview panels, active XR,
and native state/action HDF. All selectors are process-local and opt-in through
`tools/camera_audit/launch.py`. No production default or gate selection is changed.

The [source audit](source_audit.json), [environment](environment.json),
[results](results.json), and [provenance](provenance.json) separate requested
settings, effective readbacks, retained timings, and exclusions. The no-client XR
workload does not establish Quest presentation or operator usability.
