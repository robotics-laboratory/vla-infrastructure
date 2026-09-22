"""Fail-closed Kit preflight for the pinned NVIDIA Episode Recorder API."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from types import ModuleType
from typing import Any


EXTENSION_NAME = "isaacsim.replicator.episode_recorder"
EXPECTED_VERSION = "0.1.6"
EXPECTED_SCHEMA_VERSION = 2
REQUIRED_SYMBOLS = (
    "ArticulationRecordable",
    "CameraRecordable",
    "ChannelDescriptor",
    "EpisodeReplayer",
    "Recordable",
    "ReplayPolicy",
    "RigidBodyRecordable",
    "SCHEMA_VERSION",
    "SessionReader",
    "SessionStorage",
    "SimTimeRecordable",
    "build_manifest",
    "export_stage_snapshot",
    "register_recordable",
)


@dataclass(frozen=True)
class EpisodeRecorderPreflight:
    """Auditable identity of the enabled extension and imported Python API."""

    extension_id: str
    version: str
    schema_version: int
    required_symbols: tuple[str, ...]


def validate_episode_recorder_api(
    extension_manager: Any,
    module: ModuleType | Any,
) -> EpisodeRecorderPreflight:
    """Validate injected Kit extension metadata and the imported public API."""
    extension_id = extension_manager.get_enabled_extension_id(EXTENSION_NAME)
    if not extension_id:
        raise RuntimeError(f"required Kit extension is not enabled: {EXTENSION_NAME}")

    metadata = extension_manager.get_extension_dict(extension_id)
    try:
        version = metadata["package"]["version"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            f"Kit extension metadata has no package.version: {extension_id}"
        ) from exc
    if version != EXPECTED_VERSION:
        raise RuntimeError(
            f"unsupported {EXTENSION_NAME} version {version!r}; "
            f"expected exactly {EXPECTED_VERSION!r}"
        )

    missing = tuple(name for name in REQUIRED_SYMBOLS if not hasattr(module, name))
    if missing:
        raise RuntimeError(
            f"{EXTENSION_NAME} {version} is missing required public symbols: "
            f"{', '.join(missing)}"
        )
    schema_version = getattr(module, "SCHEMA_VERSION")
    if schema_version != EXPECTED_SCHEMA_VERSION:
        raise RuntimeError(
            f"unsupported Episode Recorder HDF schema {schema_version!r}; "
            f"expected {EXPECTED_SCHEMA_VERSION}"
        )

    return EpisodeRecorderPreflight(
        extension_id=str(extension_id),
        version=str(version),
        schema_version=int(schema_version),
        required_symbols=REQUIRED_SYMBOLS,
    )


def preflight_episode_recorder(
    *,
    extension_manager: Any | None = None,
    module: ModuleType | Any | None = None,
) -> EpisodeRecorderPreflight:
    """Resolve Kit dependencies lazily and enforce the pinned recorder contract."""
    if extension_manager is None:
        import omni.kit.app

        extension_manager = omni.kit.app.get_app().get_extension_manager()
    if module is None:
        module = importlib.import_module(EXTENSION_NAME)
    return validate_episode_recorder_api(extension_manager, module)
