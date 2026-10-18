"""Runtime composition and launch provenance checks without importing Kit."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess

import pytest
import yaml

from tools.isaac_vr_runtime_profiles import MASTER_COMMIT, RUNTIME_NAMES, load_runtime_profile


@pytest.fixture
def launcher(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools"))
    return importlib.import_module("launch_isaac_vr")


def test_explicit_profiles_preserve_experiment_distinctions():
    profiles = {name: load_runtime_profile(name) for name in RUNTIME_NAMES}
    assert not profiles["selected"]["native"]
    assert profiles["master"]["provenance"]["commit"] == MASTER_COMMIT
    for name, overview in zip(RUNTIME_NAMES[2:], range(5, 9)):
        profile = profiles[name]
        assert profile["native"] and profile["device"] == "cpu"
        assert profile["overview"] == overview
        assert profile["media"]["capture"] == "callback"
        assert not profile["media"]["witness"]
    sync, event, proof, live = [profiles[name] for name in RUNTIME_NAMES[2:]]
    assert sync["media"]["preview_transport"] == "cuda" and not sync["early_subscribe"]
    assert event["early_subscribe"] and not event["media"]["source_proof"]
    assert proof["media"]["source_proof"] and proof["media"]["bind_sources"]
    assert not proof["media"]["identity_only"]
    assert all(live["media"][key] for key in (
        "source_proof", "bind_sources", "proof_compact", "proof_clock_only",
        "attribute_probe", "attribute_only", "identity_only", "cache_helpers",
    ))
    live["media"]["identity_only"] = False
    assert load_runtime_profile("native-live")["media"]["identity_only"]
    with pytest.raises(ValueError, match="Unknown VR runtime"):
        load_runtime_profile("imaginary")


def test_listing_never_verifies_or_starts_kit(launcher, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("listing must not inspect the installed stack or start a child")
    monkeypatch.setattr(launcher, "verify_stack", forbidden)
    monkeypatch.setattr(launcher.subprocess, "Popen", forbidden)
    assert launcher.main(["--list-runtimes"]) == 0
    assert [row["name"] for row in json.loads(capsys.readouterr().out)] == list(RUNTIME_NAMES)


@pytest.mark.parametrize("mode", ["run", "diag", "record"])
@pytest.mark.parametrize("name", RUNTIME_NAMES[2:])
def test_native_dry_run_routes_shared_child_and_records_sources(
    launcher, tmp_path, monkeypatch, mode, name,
):
    monkeypatch.setattr(launcher, "verify_stack", lambda _: launcher.STACKS["isaac61"])
    monkeypatch.setattr(launcher, "configure_cloudxr", lambda *a, **kw: None)
    monkeypatch.setattr(launcher, "_git_output", lambda *a: "")
    run = tmp_path / "run"
    assert launcher.main([
        mode, "--runtime", name, "--dry-run", "--run-dir", str(run),
        "--state-root", str(run / "host"),
    ]) == 0
    manifest = json.loads((run / "run_manifest.json").read_text())
    runtime = yaml.safe_load((run / "runtime.yaml").read_text())
    profile = load_runtime_profile(name)
    assert manifest["runtime_profile"] == runtime["vr_runtime_profile"] == profile
    assert manifest["launch"]["runtime"] == name
    command = manifest["launch"]["command"]
    assert command[command.index("--vr-runtime-variant") + 1] == name
    assert command[command.index("--device") + 1] == "cpu"
    assert command[command.index("--s2-mode") + 1] == ("diagnostic" if mode == "diag" else "run")
    assert command[1] == str(launcher.ROOT / "tools/run_isaac_s1.py")
    assert launcher.EPISODE_RECORDER_EXTENSION in command[command.index("--kit_args") + 1]
    assert "--demo-hud-on-start" in command
    assert ("--s2-record" in command) == (mode == "record")
    hashes = manifest["repository"]["source_sha256"]
    assert "tools/isaac_vr_runtime_profiles.py" in hashes
    assert "tools/isaac_vr_native_media.py" in hashes
    assert "tools/isaac_vr_live_gpu.py" in hashes
    assert not (run / "stdout.log").exists()


@pytest.mark.parametrize("options", [
    ["--stack", "legacy"],
    ["replay", "--recording", "/tmp/session.hdf5"],
    ["diag", "--profile", "robosyn_asset_lab"],
    ["diag", "--capture-preview-evidence"],
    ["diag", "--scene-preview", "/tmp/scene.png"],
    ["record", "--smoke"],
    ["record", "--injected-actions"],
    ["record", "--recording-benchmark"],
    ["record", "--audit-clutch"],
    ["--baseline-checkout", "/tmp/baseline"],
])
def test_native_rejects_incompatible_lifecycles_early(launcher, options):
    with pytest.raises(SystemExit):
        launcher.parse_args([*options, "--runtime", "native-live"])


def test_native_preview_and_no_client_smoke_options(launcher):
    assert launcher.parse_args(["record", "--runtime", "native-live"]).hud_on_start
    assert not launcher.parse_args([
        "record", "--runtime", "native-live", "--no-hud-on-start",
    ]).hud_on_start
    for mode in ("run", "diag"):
        assert launcher.parse_args([mode, "--runtime", "native-event", "--xr-smoke"]).runtime == "native-event"
    selected = launcher.parse_args([])
    assert selected.runtime == "selected" and selected.hud_on_start
    assert not launcher.parse_args(["record"]).hud_on_start


@pytest.mark.parametrize("runtime", RUNTIME_NAMES[2:])
@pytest.mark.parametrize("mode", ("run", "diag", "record"))
def test_native_plain_smoke_recommends_xr_before_bootstrap(launcher, runtime, mode, capsys):
    with pytest.raises(SystemExit):
        launcher.parse_args([mode, "--runtime", runtime, "--smoke"])
    assert "use --xr-smoke" in capsys.readouterr().err
    assert launcher.parse_args([mode, "--smoke"]).runtime == "selected"


def test_runtime_state_defaults_are_distinct_and_explicit_override_wins(launcher, tmp_path):
    defaults = [launcher.parse_args(["--runtime", name]).state_root for name in RUNTIME_NAMES[1:]]
    assert len(set(defaults)) == 5 and all(path.is_absolute() for path in defaults)
    assert all(not path.is_relative_to(launcher.ROOT) for path in defaults)
    assert "master-" + launcher.MASTER_COMMIT[:12] in defaults[0].name
    assert launcher.parse_args([]).state_root is None
    for name in RUNTIME_NAMES:
        assert launcher.parse_args(["--runtime", name, "--state-root", str(tmp_path)]).state_root == tmp_path


@pytest.mark.parametrize("style", ["separate", "equals"])
def test_master_dispatches_original_cli_to_exact_source(launcher, tmp_path, monkeypatch, style):
    checkout = tmp_path / "baseline"
    checkout.mkdir()
    def git_output(command, **kwargs):
        assert command[:3] == ["git", "-C", str(checkout)]
        return {"--show-toplevel": str(checkout), "HEAD": MASTER_COMMIT,
                "--untracked-files=all": ""}[command[-1]]
    monkeypatch.setattr(launcher.subprocess, "check_output", git_output)
    launches = []
    monkeypatch.setattr(launcher.subprocess, "call", lambda command, **kwargs: launches.append((command, kwargs)) or 0)
    monkeypatch.setattr(launcher, "verify_stack", lambda _: pytest.fail("current source stack must not be used"))
    selectors = (["--runtime", "master", "--baseline-checkout", str(checkout)] if style == "separate"
                 else ["--runtime=master", f"--baseline-checkout={checkout}"])
    state = str(tmp_path / "explicit-state")
    assert launcher.main(["record", *selectors, "--no-hud-on-start", "--state-root", state]) == 0
    assert launches == [([str(checkout / "run-vr"), "record", "--no-hud-on-start", "--state-root", state], {"cwd": checkout})]


@pytest.mark.parametrize("bad", ["commit", "dirty", "subdirectory"])
def test_master_rejects_changed_source(launcher, tmp_path, monkeypatch, bad):
    def git_output(command, **kwargs):
        return {"--show-toplevel": str(tmp_path.parent if bad == "subdirectory" else tmp_path),
                "HEAD": "0" * 40 if bad == "commit" else MASTER_COMMIT,
                "--untracked-files=all": "?? changed.py" if bad == "dirty" else ""}[command[-1]]
    monkeypatch.setattr(launcher.subprocess, "check_output", git_output)
    monkeypatch.setattr(launcher.subprocess, "call", lambda *a, **kw: pytest.fail("changed baseline must not launch"))
    with pytest.raises(RuntimeError, match="checkout root|exact commit|clean checkout"):
        launcher.main(["--runtime", "master", "--baseline-checkout", str(tmp_path), "--dry-run"])


@pytest.fixture
def local_baseline_repo(launcher, tmp_path, monkeypatch):
    """Exercise actual worktree creation with a tiny locally pinned source."""
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*options):
        return subprocess.check_output(["git", "-C", str(repo), *options], text=True).strip()
    git("init", "--quiet")
    (repo / ".gitignore").write_text(".worktrees/\n")
    entrypoint = repo / "run-vr"
    entrypoint.write_text('#!/bin/sh\nprintf "exact-baseline:%s\\n" "$*"\n')
    entrypoint.chmod(0o755)
    git("add", ".gitignore", "run-vr")
    git("-c", "user.name=Runtime Tests", "-c", "user.email=runtime@example.invalid", "commit", "--quiet", "-m", "Pinned baseline")
    commit = git("rev-parse", "HEAD")
    monkeypatch.setattr(launcher, "ROOT", repo)
    monkeypatch.setattr(launcher, "MASTER_COMMIT", commit)
    return repo, commit, git


def test_master_prepares_only_default_pinned_local_worktree(launcher, local_baseline_repo, capfd):
    repo, commit, git = local_baseline_repo
    assert launcher.main(["record", "--runtime", "master"]) == 0
    checkout = repo / ".worktrees/runtime-baseline-master"
    assert subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip() == commit
    assert git("status", "--porcelain=v1", "--untracked-files=all") == ""
    assert "exact-baseline:record" in capfd.readouterr().out
    # Reuse stays exact; unexpected contents are rejected without cleanup.
    (checkout / "untracked").write_text("operator work")
    with pytest.raises(RuntimeError, match="clean checkout"):
        launcher.main(["--runtime", "master"])
    assert (checkout / "untracked").read_text() == "operator work"


def test_master_absent_dry_run_and_list_leave_repo_unchanged(launcher, local_baseline_repo, capsys):
    repo, commit, git = local_baseline_repo
    worktrees_before = git("worktree", "list", "--porcelain")
    assert launcher.main(["--runtime", "master", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "worktree add --detach" in output and commit in output
    assert "VR master command:" in output
    assert "--state-root /data/" in output and f"master-{commit[:12]}" in output
    assert not (repo / ".worktrees").exists()
    assert launcher.main(["--runtime", "master", "--list-runtimes"]) == 0
    assert git("worktree", "list", "--porcelain") == worktrees_before
    assert not (repo / ".worktrees").exists()


def test_master_existing_dry_run_does_not_launch_or_write(launcher, local_baseline_repo, monkeypatch):
    repo, commit, git = local_baseline_repo
    checkout = repo / ".worktrees/runtime-baseline-master"
    git("worktree", "add", "--detach", str(checkout), commit)
    before = git("worktree", "list", "--porcelain")
    monkeypatch.setattr(launcher.subprocess, "call", lambda *a, **kw: pytest.fail("master dry-run cannot launch child"))
    assert launcher.main(["--runtime", "master", "--dry-run"]) == 0
    assert git("worktree", "list", "--porcelain") == before
    assert subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain=v1"], text=True) == ""


def test_master_missing_explicit_checkout_is_never_created(launcher, local_baseline_repo, tmp_path):
    repo, _, git = local_baseline_repo
    checkout = tmp_path / "explicit"
    before = git("worktree", "list", "--porcelain")
    for options in ([], ["--dry-run"]):
        with pytest.raises(RuntimeError, match="Explicit.*does not exist"):
            launcher.main(["--runtime", "master", "--baseline-checkout", str(checkout), *options])
    assert not checkout.exists() and not (repo / ".worktrees").exists()
    assert git("worktree", "list", "--porcelain") == before


def test_master_missing_local_commit_never_fetches_or_creates(launcher, local_baseline_repo, monkeypatch):
    repo, _, _ = local_baseline_repo
    monkeypatch.setattr(launcher, "MASTER_COMMIT", "0" * 40)
    monkeypatch.setattr(launcher.subprocess, "check_call", lambda *a, **kw: pytest.fail("no worktree without pinned commit"))
    with pytest.raises(RuntimeError, match="unavailable locally; no fetch"):
        launcher.main(["--runtime", "master"])
    assert not (repo / ".worktrees").exists()
