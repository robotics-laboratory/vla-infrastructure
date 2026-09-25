"""Fail-closed demo-level admission for verified Isaac VR source segments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence
from uuid import uuid4

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.isaac_vr_lerobot_materialize import (
    CAMERA_ROLES,
    CONVERSION_REVISION,
    MATERIALIZATION_MANIFEST,
    MATERIALIZATION_SCHEMA,
    MaterializationError,
    _validated_image_join,
    verify_materialization_manifest,
    verify_projection_bundle,
)
from tools.isaac_vr_replay import verify_recording_artifact

SCHEMA = "piper_x_isaac_vr_demo_admission_v1"
PHYSICAL_SCHEMA = "piper_x_isaac_vr_physical_qualification_v1"
DEMO_SCHEMA = "piper_x_isaac_vr_human_demo_v2"
SOURCE_PROFILE = "isaac_human_vr_offline_rgb_v2"
ROW_SCHEMA = "piper_x_committed_transition_v3"
CONTRACT = Path(__file__).resolve().parents[1] / "configs/resolved_contract.yaml"


class AdmissionError(ValueError):
    """Invalid or contradictory input; no admission decision can be published."""


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdmissionError(f"unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AdmissionError(f"JSON root is not an object: {path}")
    return value


def _digest_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AdmissionError(reason)


def _physical_qualification(
    path: Path | None, binding: Mapping[str, Any], *, contract_path: Path
) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None:
        return None, ["physical_qualification_missing"]
    path = path.resolve(strict=True)
    record = _json(path)
    _require(record.get("schema") == PHYSICAL_SCHEMA, "unsupported physical qualification schema")
    evidence_id, artifact_id = record.get("evidence_id"), record.get("artifact_id")
    _require(
        isinstance(evidence_id, str) and isinstance(artifact_id, str),
        "physical registry identity missing",
    )
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    evidence = contract["evidence"].get(evidence_id)
    artifact = contract["artifacts"].get(artifact_id)
    registered = (
        isinstance(evidence, dict)
        and evidence.get("kind") == "human_gate"
        and evidence.get("status") == "pass"
        and evidence_id in contract["gates"]["S2"].get("evidence_ids", [])
        and artifact_id in evidence.get("artifact_ids", [])
        and isinstance(artifact, dict)
        and (contract_path.parent.parent / str(artifact.get("path"))).resolve() == path
        and artifact.get("sha256") == _sha(path)
    )
    _require(registered, "physical qualification lacks matching registered S2 human PASS evidence")
    _require(record.get("result") == "pass", "physical qualification record is not PASS")
    if record.get("binding") != dict(binding):
        return {
            "evidence_id": evidence_id,
            "artifact_id": artifact_id,
            "path": str(path),
            "sha256": _sha(path),
        }, ["physical_qualification_incompatible"]
    return {
        "evidence_id": evidence_id,
        "artifact_id": artifact_id,
        "path": str(path),
        "sha256": _sha(path),
    }, []


def evaluate_demo_admission(
    *,
    demo: Path,
    projections: Sequence[Path],
    materializations: Sequence[Path],
    portable_roots: Mapping[str, Path],
    physical_qualification: Path | None = None,
    contract_path: Path = CONTRACT,
) -> dict[str, Any]:
    """Verify every source/output and compute one immutable-ready demo decision."""
    demo = demo.resolve(strict=True)
    metadata = _json(demo)
    _require(metadata.get("schema") == DEMO_SCHEMA, "unsupported saved demo schema")
    demo_id = metadata.get("demo_id")
    _require(
        isinstance(demo_id, str) and bool(demo_id) and demo.stem == demo_id,
        "demo identity/path mismatch",
    )
    _require(
        metadata.get("lifecycle_disposition") == "saved_and_classified", "demo is not classified"
    )
    classification = metadata.get("save_classification")
    outcome = metadata.get("task_outcome")
    _require(classification == "saved", "unsaved demo is not an admission candidate")
    _require(outcome in {"success", "failure", "incomplete"}, "unsupported human task outcome")
    _require(metadata.get("source_profile") == SOURCE_PROFILE, "unsupported current source profile")
    _require(
        metadata.get("source_manifest_schema") == "piper_x_isaac_vr_recording_manifest_v2",
        "unsupported current source manifest",
    )
    _require(metadata.get("committed_row_schema") == ROW_SCHEMA, "unsupported current row schema")
    episodes = metadata.get("technical_episodes")
    _require(isinstance(episodes, list) and bool(episodes), "demo has no technical episodes")
    _require(len(episodes) == len(projections) == len(materializations), "missing or extra segment")
    _require(
        all(isinstance(item, dict) for item in episodes), "invalid technical episode reference"
    )

    sources: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    common: dict[str, Any] | None = None
    source_dirs: set[Path] = set()
    output_dirs: set[Path] = set()
    for index, (episode, projection_path, output_path) in enumerate(
        zip(episodes, projections, materializations)
    ):
        source_dir = Path(episode.get("output_dir", "")).resolve(strict=True)
        _require(source_dir not in source_dirs, "duplicate source segment")
        source_dirs.add(source_dir)
        episode_id = episode.get("episode_id")
        _require(episode_id == f"episode_{index:06d}", "source episode order/identity mismatch")
        source_manifest = _json(source_dir / "manifest.json")
        recording_name = source_manifest.get("hdf5")
        _require(
            isinstance(recording_name, str) and Path(recording_name).name == recording_name,
            "invalid source recording name",
        )
        recording = source_dir / recording_name
        artifact = verify_recording_artifact(
            recording, portable_roots={**portable_roots, "recording": source_dir}
        )
        session = artifact.manifest["session_metadata"]
        _require(
            artifact.manifest.get("schema") == metadata["source_manifest_schema"],
            "source manifest schema mismatch",
        )
        _require(
            artifact.manifest.get("transition_schema") == ROW_SCHEMA, "source row schema mismatch"
        )
        _require(session.get("episode_id") == episode_id, "source episode identity mismatch")
        _require(session.get("source_profile") == SOURCE_PROFILE, "source profile mismatch")
        _require(session.get("demo_id", demo_id) == demo_id, "source demo identity mismatch")
        identity = {
            key: session.get(key)
            for key in (
                "run_id",
                "session_id",
                "task",
                "source_profile",
                "execution_profile",
                "runtime_config_sha256",
                "d0_revision",
                "environment_pins",
            )
        }
        _require(
            all(
                identity.get(key)
                for key in (
                    "run_id",
                    "session_id",
                    "task",
                    "runtime_config_sha256",
                    "d0_revision",
                    "environment_pins",
                )
            ),
            "source recording identity incomplete",
        )
        _require(
            identity["execution_profile"] == "isaac_vr_record",
            "source is not the physical human-VR recording profile",
        )
        _require(
            isinstance(identity["runtime_config_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", identity["runtime_config_sha256"]) is not None
            and isinstance(identity["environment_pins"], dict)
            and isinstance(identity["d0_revision"], str),
            "source recording configuration identity is malformed",
        )
        if common is None:
            common = identity
        _require(
            identity == common, "source segments have different session/configuration identities"
        )
        projection_path = projection_path.resolve(strict=True)
        bundle, arrays = verify_projection_bundle(projection_path)
        projected = bundle["source"]
        expected_source = {
            "recording": str(recording.resolve()),
            "recording_sha256": artifact.hdf5_sha256,
            "episode_id": episode_id,
            "run_id": session["run_id"],
            "session_id": session["session_id"],
            "source_profile": SOURCE_PROFILE,
            "task": session["task"],
            "execution_profile": session.get("execution_profile"),
            "outcome": artifact.outcome,
            "stage_snapshot_sha256": artifact.snapshot_sha256,
            "asset_closure_sha256": artifact.asset_closure_sha256,
            "visual_provenance_sha256": artifact.visual_provenance_sha256,
            "terminal_successor_sha256": artifact.terminal_successor_sha256,
        }
        _require(
            all(projected.get(key) == value for key, value in expected_source.items()),
            "projection source identity/digest mismatch",
        )
        visual = artifact.visual_provenance
        expected_visual = {
            "camera_roles": {
                item["role"]: {
                    "prim_path": item["prim_path"],
                    "camera_configuration_sha256": item["camera_configuration_sha256"],
                }
                for item in visual["camera_roles"]
            },
            "renderer_configuration_sha256": visual["renderer"]["renderer_configuration_sha256"],
            "materialization_revision": visual["materialization"]["materialization_revision"],
        }
        _require(
            projected.get("visual_identity") == expected_visual,
            "projection visual provenance identity mismatch",
        )
        _require(
            bundle["frames"] == artifact.committed_frames, "projection/source frame count mismatch"
        )
        output_path = output_path.resolve(strict=True)
        _require(output_path not in output_dirs, "duplicate materialization")
        output_dirs.add(output_path)
        material = verify_materialization_manifest(output_path)
        _require(
            material.get("schema") == MATERIALIZATION_SCHEMA
            and material.get("conversion_revision") == CONVERSION_REVISION,
            "materialization schema/revision mismatch",
        )
        material_source = material.get("source")
        _require(isinstance(material_source, dict), "materialization source is missing")
        _require(
            all(material_source.get(key) == value for key, value in projected.items()),
            "materialization source identity mismatch",
        )
        _require(
            material_source.get("projection_manifest_sha256") == bundle["manifest_sha256"]
            and material_source.get("projection_payload_sha256") == bundle["projection"]["sha256"],
            "materialization projection digest mismatch",
        )
        _require(
            material.get("frames") == bundle["frames"]
            and material.get("episodes") == 1
            and material.get("fps") == 30,
            "materialization frame/episode count mismatch",
        )
        _require(material.get("task_id") == session["task"], "materialization task mismatch")
        legacy_blockers = ["source_admission_requires_external_physical_vr_qualification"]
        if projected.get("outcome") != "success":
            legacy_blockers.append("source_outcome_is_not_success")
        execution_profile = projected.get("execution_profile")
        if not isinstance(execution_profile, str) or "smoke" in execution_profile:
            legacy_blockers.append("source_execution_profile_is_not_physical_human_vr")
        allowed_admission = (
            {"dataset_admissible": False, "blocking_reasons": ["requires_demo_admission_decision"]},
            {"dataset_admissible": False, "blocking_reasons": legacy_blockers},
        )
        _require(
            material.get("admission") in allowed_admission,
            "standalone materialization admission contract mismatch",
        )
        report_path = Path(material_source.get("replay_report", ""))
        _require(
            _sha(report_path) == material_source.get("replay_report_sha256"),
            "replay report digest mismatch",
        )
        images, report = _validated_image_join(report_path, bundle, arrays)
        _require(report["schema"] == material_source.get("replay_schema"), "replay schema mismatch")
        frames = bundle["frames"]
        qa = material.get("qa")
        _require(
            isinstance(qa, dict)
            and qa.get("all_frames_read") == frames
            and qa.get("all_video_frames_decoded") == frames * len(CAMERA_ROLES)
            and qa.get("dataloader_frames") == frames
            and isinstance(qa.get("dataloader_batches"), int)
            and qa["dataloader_batches"] > 0,
            "materialization QA incomplete",
        )
        _require(
            material.get("image_join", {}).get("verified_identities")
            == len(images)
            == frames * len(CAMERA_ROLES),
            "materialization camera coverage mismatch",
        )
        ledger = material.get("projection_image_join_ledger")
        _require(
            isinstance(ledger, list) and len(ledger) == frames,
            "materialization frame ledger incomplete",
        )
        expected_outcomes = [
            {
                "frame_index": frame,
                "transition_id": str(arrays["transition_id"][frame]),
                "transition_outcome": str(arrays["transition_outcome"][frame]),
                "terminated": bool(arrays["terminated"][frame]),
                "success": bool(arrays["success"][frame]),
            }
            for frame in range(frames)
        ]
        _require(
            material.get("row_outcomes") == expected_outcomes,
            "materialization row outcome/order mismatch",
        )
        for frame, row in enumerate(ledger):
            _require(
                isinstance(row, dict)
                and row.get("frame_index") == frame
                and row.get("obs_id") == str(arrays["obs_id"][frame])
                and row.get("transition_id") == str(arrays["transition_id"][frame])
                and row.get("scene_state_snapshot_id")
                == str(arrays["scene_state_snapshot_id"][frame])
                and row.get("scene_state_snapshot_sha256")
                == str(arrays["scene_state_snapshot_sha256"][frame])
                and row.get("observation_state_sha256")
                == hashlib.sha256(
                    arrays["observation_state"][frame].astype("<f4").tobytes()
                ).hexdigest()
                and row.get("action_sha256")
                == hashlib.sha256(arrays["action"][frame].astype("<f4").tobytes()).hexdigest(),
                "materialization frame order mismatch",
            )
            _require(
                set(row.get("images", {})) == set(CAMERA_ROLES),
                "materialization camera roles missing",
            )
            for role in CAMERA_ROLES:
                image = images[
                    (
                        str(arrays["obs_id"][frame]),
                        str(arrays["scene_state_snapshot_sha256"][frame]),
                        role,
                    )
                ]
                _require(
                    row["images"][role].get("rgb_sha256") == image["rgb_sha256"],
                    "materialization image ledger mismatch",
                )
        sources.append(
            {
                "episode_id": episode_id,
                "source_dir": str(source_dir),
                "recording": str(recording.resolve()),
                "source_manifest_sha256": _sha(artifact.manifest_path),
                "recording_state_sha256": _sha(source_dir / "recording_state.json"),
                "hdf5_sha256": artifact.hdf5_sha256,
                "projection": str(projection_path),
                "projection_manifest_sha256": _sha(projection_path / "manifest.json"),
                "source_outcome": artifact.outcome,
            }
        )
        outputs.append(
            {
                "episode_id": episode_id,
                "path": str(output_path),
                "manifest_sha256": _sha(output_path / MATERIALIZATION_MANIFEST),
                "replay_report_sha256": material_source["replay_report_sha256"],
                "frames": frames,
            }
        )

    assert common is not None
    binding = {
        "task_id": common["task"],
        "source_profile": SOURCE_PROFILE,
        "execution_profile": common["execution_profile"],
        "runtime_config_sha256": common["runtime_config_sha256"],
        "processor_revision": common["d0_revision"],
        "environment_pins_sha256": _digest_json(common["environment_pins"]),
    }
    physical, blockers = _physical_qualification(
        physical_qualification, binding, contract_path=contract_path
    )
    if outcome != "success":
        blockers.insert(0, f"human_task_outcome_is_{outcome}")
    return {
        "schema": SCHEMA,
        "revision": 1,
        "demo_id": demo_id,
        "demo": {"path": str(demo), "sha256": _sha(demo)},
        "save_classification": classification,
        "task_outcome": outcome,
        "source_profile": SOURCE_PROFILE,
        "source_manifest_schema": metadata["source_manifest_schema"],
        "row_schema": ROW_SCHEMA,
        "materialization_schema": MATERIALIZATION_SCHEMA,
        "materialization_revision": CONVERSION_REVISION,
        "recording_identity": binding,
        "session_id": common["session_id"],
        "run_id": common["run_id"],
        "ordered_source_technical_episodes": sources,
        "ordered_materialized_outputs": outputs,
        "physical_qualification": physical,
        "admitted": not blockers,
        "blocking_reasons": blockers,
    }


def publish_decision(
    decision: Mapping[str, Any],
    output: Path,
    *,
    portable_roots: Mapping[str, Path],
    contract_path: Path = CONTRACT,
) -> None:
    """Recheck inputs, then create a decision once without replacing prior bytes."""
    _require(
        _reevaluate(decision, portable_roots=portable_roots, contract_path=contract_path)
        == decision,
        "admission decision differs from verified inputs",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(decision, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _reevaluate(
    decision: Mapping[str, Any],
    *,
    portable_roots: Mapping[str, Path],
    contract_path: Path,
) -> dict[str, Any]:
    _require(decision.get("schema") == SCHEMA, "unsupported decision schema")
    return evaluate_demo_admission(
        demo=Path(decision["demo"]["path"]),
        projections=[
            Path(item["projection"]) for item in decision["ordered_source_technical_episodes"]
        ],
        materializations=[Path(item["path"]) for item in decision["ordered_materialized_outputs"]],
        portable_roots=portable_roots,
        physical_qualification=Path(decision["physical_qualification"]["path"])
        if decision.get("physical_qualification")
        else None,
        contract_path=contract_path,
    )


def verify_decision(
    path: Path, *, portable_roots: Mapping[str, Path], contract_path: Path = CONTRACT
) -> dict[str, Any]:
    stored = _json(path)
    current = _reevaluate(stored, portable_roots=portable_roots, contract_path=contract_path)
    _require(current == stored, "published admission decision no longer matches verified inputs")
    return stored


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("evaluate", "verify"))
    parser.add_argument("--demo", type=Path)
    parser.add_argument("--projection", type=Path, action="append", default=[])
    parser.add_argument("--materialization", type=Path, action="append", default=[])
    parser.add_argument("--physical-qualification", type=Path)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--portable-root", action="append", default=[], metavar="NAME=PATH")
    args = parser.parse_args()
    roots = {}
    for raw in args.portable_root:
        if "=" not in raw:
            parser.error("--portable-root requires NAME=PATH")
        name, path = raw.split("=", 1)
        roots[name] = Path(path)
    try:
        if args.command == "evaluate":
            if args.demo is None:
                parser.error("evaluate requires --demo")
            result = evaluate_demo_admission(
                demo=args.demo,
                projections=args.projection,
                materializations=args.materialization,
                portable_roots=roots,
                physical_qualification=args.physical_qualification,
            )
            publish_decision(result, args.decision, portable_roots=roots)
        else:
            result = verify_decision(args.decision, portable_roots=roots)
    except (AdmissionError, MaterializationError, ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"invalid admission input: {exc}\n")
    print(
        json.dumps(
            {
                "decision": str(args.decision),
                "admitted": result["admitted"],
                "blocking_reasons": result["blocking_reasons"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
