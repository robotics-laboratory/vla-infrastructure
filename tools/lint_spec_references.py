#!/usr/bin/env python3
from __future__ import annotations
import re
from pathlib import Path
import yaml

GATE_RE = re.compile(r"\[\[gate:([A-Za-z0-9_]+)\]\]")
PROFILE_RE = re.compile(r"\[\[profile:([A-Za-z0-9_]+)\]\]")
SOURCE_RE = re.compile(r"\[\[source:([A-Za-z0-9_]+)\]\]")


def check_references(
    text: str, name: str, gates: set[str], profiles: set[str], sources: set[str]
) -> list[str]:
    errors: list[str] = []
    # Mentions explaining why v5.2 bans old magic placeholders are allowed only in README/NORMATIVE/MIGRATION.
    if name not in {"README.md", "NORMATIVE_MODEL.md", "MIGRATION_V4_3_V5_1_TO_V5_2.md"}:
        if "DECIDE/PIN" in text or "MIGRATE/PRESERVE" in text:
            errors.append(f"{name}: legacy magic placeholder text forbidden")

    for st in re.findall(r"\bstatus\.[A-Za-z0-9_]+", text):
        errors.append(f"{name}: stale/unknown status reference {st}")
    for x in GATE_RE.findall(text):
        if x not in gates:
            errors.append(f"{name}: unknown gate {x}")
    for x in PROFILE_RE.findall(text):
        if x not in profiles:
            errors.append(f"{name}: unknown profile {x}")
    for x in SOURCE_RE.findall(text):
        if x not in sources:
            errors.append(f"{name}: unknown source {x}")
    return errors


def main():
    root = Path(__file__).resolve().parent.parent
    c = yaml.safe_load((root / "configs/resolved_contract.yaml").read_text(encoding="utf-8"))
    r = yaml.safe_load((root / "configs/gate_rules.yaml").read_text(encoding="utf-8"))
    gates = set(r)
    profiles = set(c["execution_profiles"])
    sources = set(c["taxonomy"]["source_classes"])
    errors = []
    spec_paths = [*root.glob("*.md"), *(root / "docs").glob("*.md")]
    for p in sorted(spec_paths):
        errors.extend(
            check_references(p.read_text(encoding="utf-8"), p.name, gates, profiles, sources)
        )
    if errors:
        print("SPEC REFERENCE LINT FAILED")
        [print("-", e) for e in errors]
        return 1
    print("SPEC REFERENCE LINT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
