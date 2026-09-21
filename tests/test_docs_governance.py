"""Governance checks use disposable Git repositories, never Isaac or external data."""

from pathlib import Path
import subprocess

import pytest
import yaml

from tools import lint_docs as docs
from tools.validate_resolved_contract import validate_gates


def git(root, *args):
    return (
        subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)
        .decode()
        .strip()
    )


def write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def entry(path, kind="reference", status="current", mutable=True):
    return dict(path=path, kind=kind, status=status, owner="test.documentation", mutable=mutable)


def save(root, entries):
    write(root, docs.INDEX, yaml.safe_dump(dict(version=1, documents=entries), sort_keys=False))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "tests@example.invalid")
    git(tmp_path, "config", "user.name", "Governance test")
    git(tmp_path, "config", "commit.gpgsign", "false")
    write(tmp_path, "docs/operations/VR.md", "# VR\n[old](../project/old.md)\n[[gate:S2]]\n")
    write(tmp_path, "docs/project/old.md", "# Frozen run\noriginal bytes\n")
    write(tmp_path, "configs/gate_rules.yaml", "S2: {}\n")
    write(
        tmp_path,
        "configs/resolved_contract.yaml",
        "execution_profiles: {isaac_vr: {}}\ntaxonomy: {source_classes: [human_vr]}\n",
    )
    git(
        tmp_path,
        "add",
        "docs/operations/VR.md",
        "docs/project/old.md",
        "configs/gate_rules.yaml",
        "configs/resolved_contract.yaml",
    )
    git(tmp_path, "commit", "-qm", "pre-governance")
    baseline = git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setattr(docs, "LEGACY_PLACEMENT_BASE", baseline)
    entries = [
        entry(docs.INDEX),
        entry("docs/operations/VR.md", "operations"),
        entry("docs/project/old.md", "evidence", "historical", False),
    ]
    save(tmp_path, entries)
    git(tmp_path, "add", docs.INDEX)
    return tmp_path, entries, baseline


def errors(repo, base=None):
    return docs.check(repo[0], base)[0]


def trusted(repo):
    root, _, _ = repo
    git(root, "commit", "-qm", "governance baseline")
    return git(root, "rev-parse", "HEAD")


def test_no_base_is_not_checked(repo):
    found, notes = docs.check(repo[0])
    assert not found
    assert any("PRESERVATION: NOT CHECKED" in n for n in notes)
    assert not any("PRESERVATION: PASS" in n for n in notes)
    assert any("INTEGRITY DEBT: UNRESOLVED" in n for n in notes)


def test_repository_coverage_is_part_of_normal_offline_tests():
    found, _ = docs.check(Path(__file__).resolve().parents[1])
    assert found == []


def test_trusted_index_positive(repo):
    found, notes = docs.check(repo[0], trusted(repo))
    assert not found
    assert any("PRESERVATION: PASS" in n for n in notes)


def test_missing_entry(repo):
    root, entries, _ = repo
    save(root, entries[:-1])
    assert any("missing index entry" in e for e in errors(repo))


@pytest.mark.parametrize("suffix", ["version: 1\n", "extra:\n  key: 1\n  key: 2\n"])
def test_duplicate_yaml_keys(repo, suffix):
    root, _, _ = repo
    path = root / docs.INDEX
    path.write_text(path.read_text() + suffix)
    assert any("duplicate YAML key" in e for e in errors(repo))


def test_duplicate_index_path(repo):
    root, entries, _ = repo
    save(root, entries + [entries[1]])
    assert any("duplicate index path" in e for e in errors(repo))


@pytest.mark.parametrize("exists", [False, True])
def test_missing_or_untracked_indexed_path(repo, exists):
    root, entries, _ = repo
    name = "docs/reference/new.md"
    save(root, entries + [entry(name)])
    if exists:
        write(root, name, "# Untracked\n")
    assert any("not tracked" in e for e in errors(repo))
    if not exists:
        assert any("indexed path missing" in e for e in errors(repo))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("kind", "report_of_reports", "invalid kind"),
        ("status", "accepted", "invalid status"),
        ("mutable", "false", "mutable must be boolean"),
        ("path", "../escape.md", "invalid index path"),
        ("path", "/tmp/out.md", "invalid index path"),
        ("path", "docs//duplicate.md", "invalid index path"),
        ("path", "docs/./duplicate.md", "invalid index path"),
        ("path", "docs/back\\slash.md", "invalid index path"),
        ("path", ".worktrees/other/README.md", "invalid index path"),
    ],
)
def test_bad_index_values(repo, field, value, message):
    root, entries, _ = repo
    entries[1][field] = value
    save(root, entries)
    assert any(message in e for e in errors(repo))


def test_historical_must_be_immutable(repo):
    root, entries, _ = repo
    entries[2]["mutable"] = True
    save(root, entries)
    assert any("historical must be immutable" in e for e in errors(repo))


@pytest.mark.parametrize("cycle", [True, False])
def test_bad_supersession(repo, cycle):
    root, entries, _ = repo
    entries[2]["superseded_by"] = entries[1]["path"] if cycle else "docs/reference/missing.md"
    if cycle:
        entries[1]["superseded_by"] = entries[2]["path"]
    save(root, entries)
    assert any(
        ("supersession cycle" if cycle else "missing superseded_by") in e for e in errors(repo)
    )


@pytest.mark.parametrize(
    "link",
    [
        "[missing](absent.md)",
        "![missing](absent.png)",
        "[missing][ref]\n\n[ref]: absent.md",
        "[ref][]\n\n[ref]: absent.md",
        "[ref]\n\n[ref]: absent.md",
        "[missing](\n absent.md\n)",
        "[wrapped\nlabel](absent.md)",
    ],
)
def test_broken_local_links_and_images(repo, link):
    write(repo[0], "docs/operations/VR.md", "# VR\n" + link)
    assert any("missing/unsafe local target" in e for e in errors(repo))


def test_history_link_allowed_but_explicit_authority_rejected(repo):
    root = repo[0]
    assert not errors(repo)
    write(root, "docs/operations/VR.md", "# VR\n## Sources of truth\n[old](../project/old.md)\n")
    assert any("authoritative reference" in e for e in errors(repo))
    write(
        root,
        "docs/operations/VR.md",
        "# VR\n## Sources of truth\n[contract](../../configs/resolved_contract.yaml)\n## History\n[old](../project/old.md)\n",
    )
    assert not errors(repo)


def test_reference_authority_is_at_use_not_definition(repo):
    write(
        repo[0],
        "docs/operations/VR.md",
        "# VR\n## Sources of truth\n[proof][old]\n## History\n[old]: ../project/old.md\n",
    )
    assert any("authoritative reference" in e for e in errors(repo))


@pytest.mark.parametrize("token", ["[[gate:UNKNOWN]]", "[[profile:unknown]]", "[[source:unknown]]"])
def test_nested_current_spec_tokens(repo, token):
    write(repo[0], "docs/operations/VR.md", "# VR\n" + token)
    assert any("unknown" in e for e in errors(repo))


def test_spec_tokens_in_grandfathered_nested_project_current_doc(repo, monkeypatch):
    root, entries, _ = repo
    path = "docs/project/nested/CURRENT.md"
    write(root, path, "# Maintained instructions\n")
    save(root, entries + [entry(path, "operations")])
    git(root, "add", path, docs.INDEX)
    git(root, "commit", "-qm", "existing nested owner")
    monkeypatch.setattr(docs, "LEGACY_PLACEMENT_BASE", git(root, "rev-parse", "HEAD"))
    assert not errors(repo)
    write(root, path, "[[gate:UNKNOWN]]\n")
    assert any("unknown gate" in e for e in errors(repo))


def test_local_navigation_does_not_follow_external_symlinks(repo, tmp_path):
    root = repo[0]
    external = tmp_path.parent / (tmp_path.name + "-external")
    external.mkdir()
    (external / "proof.md").write_text("external bytes")
    (root / "external").symlink_to(external, target_is_directory=True)
    write(root, "docs/operations/VR.md", "[proof](../../external/proof.md)\n")
    assert any("missing/unsafe local target" in e for e in errors(repo))


def test_historical_tokens_are_not_checked_against_current_registry(repo):
    base = trusted(repo)
    write(repo[0], "docs/project/old.md", "[[gate:OLD_GATE]]\n")
    assert not errors(repo)  # No preservation claim without --base.
    assert errors(repo, base)


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("docs/project/new.md", "evidence"),
        ("docs/project/new/sub/report.md", "experiment"),
        ("docs/operations/wrong.md", "experiment"),
        ("docs/evidence/UNKNOWN/run/report.md", "evidence"),
        ("docs/experiments/loose.md", "experiment"),
    ],
)
def test_index_cannot_legalize_forbidden_new_path(repo, path, kind):
    root, entries, _ = repo
    write(root, path, "# New\n")
    save(root, entries + [entry(path, kind)])
    git(root, "add", path)
    assert any("forbidden new documentation placement" in e for e in errors(repo))


def test_valid_new_bundle_and_markdown_destinations(repo):
    root, entries, _ = repo
    paths = ["docs/evidence/S2/20260921_test/a (1).png", "docs/evidence/S2/20260921_test/REPORT.md"]
    write(root, paths[0], "image fixture")
    write(root, paths[1], '# Test\n![image](<a (1).png> "title")\n[encoded](a%20(1).png)\n')
    save(root, entries + [entry(p, "evidence") for p in paths])
    git(root, "add", *paths)
    assert not errors(repo)


@pytest.mark.parametrize(
    "action", ["edit", "delete", "drop", "drop_delete", "relax", "status", "staged"]
)
def test_trusted_historical_protection_cannot_be_relaxed(repo, action):
    root, entries, _ = repo
    base = trusted(repo)
    path = entries[2]["path"]
    if action in {"edit", "relax", "staged"}:
        write(root, path, "altered evidence\n")
    if action in {"delete", "drop_delete"}:
        (root / path).unlink()
        git(root, "add", path)
    if action in {"drop", "drop_delete"}:
        entries.pop()
    if action == "relax":
        entries[2].update(status="current", mutable=True)
    if action == "status":
        entries[2]["status"] = "current"
    if action == "staged":
        git(root, "add", path)
        write(root, path, "# Frozen run\noriginal bytes\n")
    save(root, entries)
    assert any("immutable" in e for e in errors(repo, base))


@pytest.mark.parametrize("action", ["unchanged", "edit", "unfreeze", "drop_delete"])
def test_base_without_index_requires_review_without_trusting_current_classification(repo, action):
    root, entries, baseline = repo
    path = entries[2]["path"]
    if action in {"edit", "unfreeze"}:
        write(root, path, "changed historical bytes\n")
    if action == "unfreeze":
        entries[2].update(status="current", mutable=True)
    if action == "drop_delete":
        entries.pop()
        (root / path).unlink()
        git(root, "add", path)
        write(root, entries[1]["path"], "# Current guide without a dangling link\n")
    save(root, entries)
    found, notes = docs.check(root, baseline)
    assert not found
    assert "HISTORICAL PRESERVATION: BOOTSTRAP REVIEW REQUIRED" in notes
    assert "base has no trusted docs/INDEX.yaml" in notes
    assert not any("PRESERVATION: PASS" in n for n in notes)


def test_any_base_without_index_requires_review(repo):
    root, _, _ = repo
    trusted(repo)
    git(root, "rm", docs.INDEX)
    git(root, "commit", "-qm", "remove index")
    no_index = git(root, "rev-parse", "HEAD")
    save(root, repo[1])
    git(root, "add", docs.INDEX)
    found, notes = docs.check(root, no_index)
    assert not found
    assert "HISTORICAL PRESERVATION: BOOTSTRAP REVIEW REQUIRED" in notes
    assert not any("PRESERVATION: PASS" in n for n in notes)


@pytest.mark.parametrize("base_kind", ["none", "bootstrap", "trusted"])
@pytest.mark.parametrize("issue", ["index", "placement", "link", "spec"])
def test_static_checks_run_regardless_of_preservation_mode(repo, base_kind, issue):
    root, entries, baseline = repo
    base = (
        trusted(repo) if base_kind == "trusted" else baseline if base_kind == "bootstrap" else None
    )
    if issue == "index":
        save(root, entries[:-1])
        message = "missing index entry"
    elif issue == "placement":
        path = "docs/project/new.md"
        write(root, path, "# New loose report\n")
        git(root, "add", path)
        save(root, entries + [entry(path, "evidence")])
        message = "forbidden new documentation placement"
    else:
        write(
            root, entries[1]["path"], "[broken](missing.md)" if issue == "link" else "[[gate:BAD]]"
        )
        message = "missing/unsafe local target" if issue == "link" else "unknown gate"
    assert any(message in e for e in errors(repo, base))


def test_current_immutable_base_entry_is_also_protected(repo):
    root, entries, _ = repo
    entries[2]["status"] = "current"
    save(root, entries)
    git(root, "add", docs.INDEX)
    base = trusted(repo)
    entries[2]["mutable"] = True
    save(root, entries)
    write(root, entries[2]["path"], "changed immutable bytes\n")
    found = errors(repo, base)
    assert any("cannot remove or relax" in e for e in found)
    assert any("immutable bytes" in e for e in found)


def test_read_only_and_untracked_caches_ignored(repo):
    root = repo[0]
    write(root, ".worktrees/other/docs/not-indexed.md", "# Other checkout\n")
    write(root, ".cache/untracked.md", "# Cache\n")
    before = git(root, "status", "--porcelain")
    index = (root / docs.INDEX).read_bytes()
    assert not errors(repo, repo[2])
    assert git(root, "status", "--porcelain") == before
    assert (root / docs.INDEX).read_bytes() == index


@pytest.mark.parametrize("field", ["evidence_ids", "artifact_ids"])
@pytest.mark.parametrize(
    "state",
    [
        "unresolved",
        "resolved",
        "configured",
        "smoke_validated",
        "artifact_validated",
        "human_verified",
        "blocked",
        "accepted",
    ],
)
def test_unknown_gate_references_fail_in_every_state(field, state):
    contract = dict(
        gates={"S2": dict(state=state, evidence_ids=[], artifact_ids=[])}, evidence={}, artifacts={}
    )
    contract["gates"]["S2"][field] = ["unknown"]
    found = validate_gates(contract, {"S2": {}})
    assert any("unknown" in e for e in found)


def test_unresolved_gate_does_not_require_acceptance_evidence():
    contract = dict(
        gates={"S2": dict(state="unresolved", evidence_ids=[], artifact_ids=[])},
        evidence={},
        artifacts={},
    )
    rules = {"S2": dict(required_evidence_kinds=["human_gate"], required_artifact_kinds=["log"])}
    assert validate_gates(contract, rules) == []
    contract["gates"]["S2"]["state"] = "accepted"
    assert any("missing PASS evidence" in e for e in validate_gates(contract, rules))
