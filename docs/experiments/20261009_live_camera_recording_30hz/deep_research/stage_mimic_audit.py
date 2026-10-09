"""Read raw USD multiple-apply schemas; unregistered APIs are not omitted."""

import hashlib
import json
from pathlib import Path
from pxr import Usd

stage_path = Path("/data/ebulochkin/vla-runtime/live30-20261009/piper-inputs/stage_snapshot.usd")
stage = Usd.Stage.Open(str(stage_path))
rows = []
for prim in stage.Traverse():
    raw = prim.GetMetadata("apiSchemas")
    for name in raw.GetAppliedItems() if raw else []:
        if not str(name).startswith("PhysxMimicJointAPI:") and str(name) != "NewtonMimicAPI":
            continue
        axis = str(name).split(":")[1] if ":" in str(name) else None
        prefix = "physxMimicJoint:" + axis + ":" if axis else "newton:"

        def attr(key):
            return prim.GetAttribute(prefix + key).Get()

        rows.append(
            dict(
                path=str(prim.GetPath()),
                schema=str(name),
                axis=axis,
                registered_applied_schemas=list(prim.GetAppliedSchemas()),
                reference_joint=list(
                    map(
                        str,
                        prim.GetRelationship(
                            prefix + ("referenceJoint" if axis else "mimicJoint")
                        ).GetTargets(),
                    )
                ),
                gearing=attr("gearing") if axis else None,
                offset=attr("offset") if axis else None,
                coef0=attr("mimicCoef0") or 0.0 if not axis else None,
                coef1=attr("mimicCoef1") if not axis else None,
            )
        )
result = dict(
    stage=str(stage_path),
    stage_sha256=hashlib.sha256(stage_path.read_bytes()).hexdigest(),
    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    count=len(rows),
    mimics=rows,
    conclusion="Raw metadata preserves unknown API schemas that GetAppliedSchemas omits without extension registration",
)
Path("/tmp/live30-stage-mimic-audit-all.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
