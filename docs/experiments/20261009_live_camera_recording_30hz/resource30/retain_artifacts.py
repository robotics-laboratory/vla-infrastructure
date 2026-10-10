"""Freeze an external resource-assay inventory; exclude disposable caches only."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

CACHES = {"cache", "hf", "hf-datasets", "__pycache__", ".pytest_cache", ".ruff_cache"}


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    inventory = args.root / "retention-inventory.json"
    if inventory.exists() or args.receipt.exists():
        raise FileExistsError("Preserve frozen inventory; use a new bundle")
    shutil.copyfile(__file__, args.root / "retention-tested-source.py")
    files = []
    links = []
    for path in sorted(args.root.rglob("*")):
        relative = path.relative_to(args.root)
        if CACHES.intersection(relative.parts) or path.name.startswith(".recording-assay"):
            continue
        if path.is_symlink():
            target = path.resolve(strict=True)
            expected = Path(
                "/data/ebulochkin/vla-runtime/live30-dataset-20261010/dataset-reach03/videos"
            )
            if relative.parts[:2] != ("cpu-qa", "negative-actual") or target != expected:
                raise ValueError(f"Unexpected retained symlink: {path}")
            links.append(
                dict(
                    path=relative.as_posix(),
                    target=str(target),
                    files=[
                        dict(path=p.relative_to(target).as_posix(), sha256=sha(p))
                        for p in sorted(target.rglob("*"))
                        if p.is_file()
                    ],
                )
            )
            continue
        if path.is_file():
            files.append(
                dict(path=relative.as_posix(), bytes=path.stat().st_size, sha256=sha(path))
            )
    inventory.write_text(json.dumps(dict(files=files, diagnostic_links=links), indent=2) + "\n")
    receipt = dict(
        schema="resource30_retention_v1",
        root=str(args.root),
        inventory=str(inventory),
        inventory_sha256=sha(inventory),
        files=len(files),
        total_bytes=sum(f["bytes"] for f in files),
        source_sha256=sha(Path(__file__)),
        exclusions=sorted(CACHES),
        diagnostic_video_links=len(links),
        prior_inputs_retained_at="/data/ebulochkin/vla-runtime/live30-dataset-20261010",
        dataset_admissible=False,
        gate_bindings=[],
    )
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
