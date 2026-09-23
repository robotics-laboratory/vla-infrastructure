"""Reuse the frozen native witness assay, retain pixels, tighten classification."""

from collections import Counter
import json
import os
from pathlib import Path

import numpy as np

ROLES = ("left_wrist", "right_wrist", "scene")


def classify(errors, separation):
    """Reject poor absolute matches as well as ambiguous nearest references."""
    if set(errors) != {"0", "-1", "-2", "-3"} or separation < 10:
        return "unresolved"
    ordered = sorted(errors, key=errors.get)
    best, second = (errors[key] for key in ordered[:2])
    if not np.isfinite(list(errors.values())).all():
        return "unresolved"
    if best > separation * 0.4 or second - best < max(5.0, separation * 0.25):
        return "unresolved"
    return int(ordered[0])


def run(env, out: Path, count, counters, drawables):
    import deferred_probe

    os.environ["VR_BAKEOFF_CANDIDATE"] = (
        "LIVE-MIN120-BATCHED" if os.environ["CAMERA_AUDIT_BATCH"] == "1" else "LIVE-MIN120-DEFERRED"
    )
    images = out / "images"
    images.mkdir()
    capture = env.camera.capture
    previous_freeze = capture.freeze
    sequence = []

    def freeze():
        payload = previous_freeze()
        name = f"{len(sequence):06d}.npz"
        np.savez(images / name, **payload)
        sequence.append(
            {
                "file": name,
                "physics": env.sim.get_physics_step_count(),
                "render_generation": env.sim.render_generation,
                "counters": dict(counters),
                "drawables": dict(drawables),
            }
        )
        return payload

    capture.freeze = freeze
    error = None
    try:
        deferred_probe.qualify(env, out, count, characterize=True, priming_renders=2)
    except Exception as exc:
        error = repr(exc)
    finally:
        capture.freeze = previous_freeze
        (out / "image-sequence.json").write_text(json.dumps(sequence, indent=2))
    path = out / "deferred-phase.json"
    if not path.exists():
        (out / "oracle-summary.json").write_text(json.dumps({"failure": error, "count": 0}))
        raise RuntimeError(error)
    raw = json.loads(path.read_text())
    # Historical helper has hard-coded renderer labels: never use those labels
    # as effective configuration. The separately retained Carb readbacks own it.
    raw["result"]["runtime"] = {
        "physics_hz": 120,
        "control_hz": 30,
        "settings": "../settings-after.json",
        "scope": "diagnostic native stimulus; no dataset admission",
    }
    path.write_text(json.dumps(raw, indent=2))
    refs = raw["result"]["characterization"]["reference_features"]
    separations = {}
    for role in ROLES:
        values = list(refs[role].values())
        separations[role] = min(
            float(np.linalg.norm(np.asarray(a) - b))
            for i, a in enumerate(values)
            for b in values[i + 1 :]
        )
    rows = raw["rows"]
    for row in rows:
        row["strict_offsets"] = {
            role: classify(row["views"][role]["characterization_errors"], separations[role])
            for role in ROLES
        }
    summary = {
        "failure": error,
        "count": len(rows),
        "reference_separations": separations,
        "histograms": {
            r: dict(Counter(str(row["strict_offsets"][r]) for row in rows)) for r in ROLES
        },
    }
    for name, predicate in {
        "all_N": lambda v: all(x == 0 for x in v),
        "all_N_minus_1": lambda v: all(x == -1 for x in v),
        "any_N_minus_2_or_3": lambda v: any(x in (-2, -3) for x in v),
        "unresolved": lambda v: "unresolved" in v,
        "cross_view_disagreement": lambda v: len(set(v) - {"unresolved"}) > 1,
    }.items():
        summary[name] = sum(predicate(list(row["strict_offsets"].values())) for row in rows)
    (out / "classifications.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (out / "oracle-summary.json").write_text(json.dumps(summary, indent=2))
