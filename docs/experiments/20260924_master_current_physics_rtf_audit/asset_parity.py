"""Hash generated USD payloads from the isolated experiment state roots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


URDF = "103af50b99b17e4ff962b7f563459672ad89556661de79cbd30c1792fea92a6f"
STATE = Path("/tmp/vr-physics-rtf-20260924")


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(name):
    root = STATE / name / "assets/converted" / URDF
    if not root.is_dir():
        raise FileNotFoundError(root)
    return {str(path.relative_to(root)): _sha(path) for path in root.rglob("*")
            if path.is_file() and path.suffix in {".usda", ".usd"}}


def main():
    old, current = _inventory("old"), _inventory("current")
    paths = sorted(set(old) | set(current))
    result = {"composed_urdf_sha256": URDF,
              "conversion_root_old": str(STATE / "old/assets/converted" / URDF),
              "conversion_root_current": str(STATE / "current/assets/converted" / URDF),
              "usd_payload_sha256": {"old": old, "current": current},
              "converter_asset_hash": {name: (STATE / name / "assets/converted" / URDF / ".asset_hash").read_text().strip()
                                       for name in ("old", "current")},
              "materialized_urdf_sha256": {name: _sha(STATE / name / "assets/piper_x_gate_c.urdf")
                                             for name in ("old", "current")},
              "missing_or_different_payloads": [path for path in paths if old.get(path) != current.get(path)]}
    Path(__file__).with_name("asset-parity.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
