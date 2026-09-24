"""Normalize and diff exact OLD/CURRENT effective USD and PhysX snapshots."""

from __future__ import annotations

import json
import math
from pathlib import Path


def _normalize(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def _compare(left, right, path, differences):
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            _compare(left.get(key, "<missing>"), right.get(key, "<missing>"),
                     f"{path}/{key}", differences)
    elif isinstance(left, list) and isinstance(right, list):
        if path.endswith("/api_schemas"):
            added = sorted(set(right) - set(left))
            removed = sorted(set(left) - set(right))
            if added or removed:
                differences.append({"path": path, "added": added, "removed": removed})
            return
        if len(left) != len(right):
            differences.append({"path": path + "/length", "old": len(left), "current": len(right)})
        for index, (a, b) in enumerate(zip(left, right)):
            _compare(a, b, f"{path}/{index}", differences)
    elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if not math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-9):
            differences.append({"path": path, "old": left, "current": right})
    elif left != right:
        differences.append({"path": path, "old": left, "current": right})


def main():
    output = Path(__file__).resolve().parent
    old = _normalize(json.loads((output / "runtime-old.json").read_text()))
    current = _normalize(json.loads((output / "runtime-current.json").read_text()))
    (output / "runtime-old.json").write_text(json.dumps(old, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (output / "runtime-current.json").write_text(json.dumps(current, indent=2, sort_keys=True, allow_nan=False) + "\n")
    differences = []
    _compare(old, current, "", differences)
    (output / "runtime-diff.json").write_text(json.dumps({"difference_count": len(differences),
        "differences": differences}, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
