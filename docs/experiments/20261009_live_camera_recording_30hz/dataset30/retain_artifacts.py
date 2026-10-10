"""Retain completed CPU attempts and hash the durable experiment bundle."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil


PREFIXES = (
    "live30-paced-",
    "live30-lerobot-audit",
    "live30-standalone-guard",
    "live30-final-dataset-",
)
CACHES = {"__pycache__", ".pytest_cache", ".ruff_cache", "hf", "hf-datasets", "hf-cache"}


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transient(path):
    return bool(CACHES.intersection(path.parts)) or path.name.endswith("-hf-cache")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    inventory = args.root / "retention-inventory.json"
    if inventory.exists():
        raise FileExistsError("Existing retention inventory is frozen; use a new bundle")
    audit = args.root / "cpu-audits"
    audit.mkdir(exist_ok=True)
    copied = []
    for source in sorted(Path("/tmp").iterdir()):
        if (
            not source.name.startswith(PREFIXES)
            or source.name == "live30-paced-cache"
            or transient(source)
        ):
            continue
        files = sorted(source.rglob("*")) if source.is_dir() else [source]
        for file in files:
            if not file.is_file() or transient(file.relative_to(Path("/tmp"))):
                continue
            if file.is_symlink():
                raise ValueError(f"Unexpected evidence symlink: {file}")
            destination = audit / file.relative_to(Path("/tmp"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            expected = sha(file)
            if not destination.exists():
                shutil.copyfile(file, destination)
            if sha(destination) != expected or sha(file) != expected:
                raise ValueError(f"Evidence changed or retention collision: {file}")
            copied.append(dict(source=str(file), destination=str(destination), sha256=expected))
    script = audit / "retain_artifacts-tested-source.py"
    if script.exists() and sha(script) != sha(Path(__file__)):
        raise ValueError("Retained generator source differs")
    if not script.exists():
        shutil.copyfile(Path(__file__), script)
    files = [
        dict(path=f.relative_to(args.root).as_posix(), bytes=f.stat().st_size, sha256=sha(f))
        for f in sorted(args.root.rglob("*"))
        if f.is_file() and not transient(f) and f.name != "retention-inventory.json"
    ]
    inventory.write_text(json.dumps(dict(files=files, copies=copied), indent=2) + "\n")
    receipt = dict(
        schema="live30_dataset_retention_v1",
        root=str(args.root),
        inventory=str(inventory),
        inventory_sha256=sha(inventory),
        file_count=len(files),
        total_bytes=sum(f["bytes"] for f in files),
        verified_copies=len(copied),
        source_sha256=sha(Path(__file__)),
        command=["retain_artifacts.py", "--root", str(args.root), "--receipt", str(args.receipt)],
        excluded="HF caches and Python/test caches are not proof; owned successful PNG staging was removed by materialization",
        dataset_admissible=False,
        gate_bindings=[],
    )
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
