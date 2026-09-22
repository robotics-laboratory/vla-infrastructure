from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.isaac_episode_recorder_preflight import (
    EXPECTED_SCHEMA_VERSION,
    EXPECTED_VERSION,
    EXTENSION_NAME,
    REQUIRED_SYMBOLS,
    preflight_episode_recorder,
    validate_episode_recorder_api,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeExtensionManager:
    def __init__(self, *, extension_id="recorder-0.1.6", version=EXPECTED_VERSION):
        self.extension_id = extension_id
        self.version = version

    def get_enabled_extension_id(self, name):
        assert name == EXTENSION_NAME
        return self.extension_id

    def get_extension_dict(self, extension_id):
        assert extension_id == self.extension_id
        return {"package": {"version": self.version}}


def recorder_module(**overrides):
    values = {name: object() for name in REQUIRED_SYMBOLS}
    values["SCHEMA_VERSION"] = EXPECTED_SCHEMA_VERSION
    values.update(overrides)
    return SimpleNamespace(**values)


def test_preflight_accepts_exact_enabled_api_with_injected_dependencies():
    result = preflight_episode_recorder(
        extension_manager=FakeExtensionManager(),
        module=recorder_module(),
    )

    assert result.extension_id == "recorder-0.1.6"
    assert result.version == EXPECTED_VERSION
    assert result.schema_version == EXPECTED_SCHEMA_VERSION
    assert result.required_symbols == REQUIRED_SYMBOLS


def test_preflight_rejects_disabled_extension():
    with pytest.raises(RuntimeError, match="not enabled"):
        validate_episode_recorder_api(
            FakeExtensionManager(extension_id=""),
            recorder_module(),
        )


def test_preflight_rejects_any_other_extension_version():
    with pytest.raises(RuntimeError, match="expected exactly '0.1.6'"):
        validate_episode_recorder_api(
            FakeExtensionManager(version="0.1.7"),
            recorder_module(),
        )


def test_preflight_rejects_missing_public_symbol():
    module = recorder_module()
    del module.EpisodeReplayer

    with pytest.raises(RuntimeError, match="EpisodeReplayer"):
        validate_episode_recorder_api(FakeExtensionManager(), module)


def test_preflight_rejects_other_hdf_schema():
    with pytest.raises(RuntimeError, match="HDF schema 3"):
        validate_episode_recorder_api(
            FakeExtensionManager(),
            recorder_module(SCHEMA_VERSION=3),
        )


def test_run_s1_preflights_only_record_and_replay_after_app_launcher():
    source = (ROOT / "tools/run_isaac_s1.py").read_text(encoding="utf-8")
    launcher = source.index("app_launcher = AppLauncher(args_cli)")
    preflight = source.index("preflight_episode_recorder()")
    torch_import = source.index("import torch  # noqa: E402")

    assert launcher < preflight < torch_import
    assert "if args_cli.s2_record or args_cli.s2_replay_hdf5 is not None:" in source[
        launcher:preflight
    ]
