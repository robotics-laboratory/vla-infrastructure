#!/usr/bin/env python3
"""Offline Gate C verification for the pinned AgileX PIPER-X model."""

from __future__ import annotations

import hashlib
import math
import tempfile
import xml.etree.ElementTree as ET
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from lerobot.model import RobotKinematics
from lerobot_robot_piperx.sdk import PIPER_JOINT_NAMES


ROOT = Path(__file__).resolve().parents[1]
MODEL_CONTRACT_PATH = ROOT / "configs/piper_x_model_contract.yaml"
CALIBRATION_INTERFACE_PATH = ROOT / "configs/piper_x_calibration_interface.yaml"


class VerificationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path} must contain a mapping")
    return value


def _child(element: ET.Element, tag: str) -> ET.Element:
    child = element.find(tag)
    if child is None:
        raise VerificationError(f"{element.tag} {element.get('name', '')} has no {tag}")
    return child


def _attribute(element: ET.Element, name: str) -> str:
    value = element.get(name)
    if value is None:
        raise VerificationError(f"{element.tag} {element.get('name', '')} has no {name}")
    return value


def _origin(joint: ET.Element) -> tuple[list[float], list[float]]:
    origin = _child(joint, "origin")
    xyz = [float(v) for v in origin.get("xyz", "0 0 0").split()]
    rpy = [float(v) for v in origin.get("rpy", "0 0 0").split()]
    return xyz, rpy


def _joint_by_name(root: ET.Element, name: str) -> ET.Element:
    joint = root.find(f"joint[@name='{name}']")
    if joint is None:
        raise VerificationError(f"missing joint {name}")
    return joint


def _verify_source(path: Path, local_sha: str, upstream_crlf_sha: str) -> None:
    data = path.read_bytes()
    _require(_sha256(data) == local_sha, f"local SHA-256 mismatch: {path}")
    _require(b"\r\n" not in data, f"local source is not LF-normalized: {path}")
    _require(
        _sha256(data.replace(b"\n", b"\r\n")) == upstream_crlf_sha,
        f"upstream CRLF SHA-256 mismatch: {path}",
    )


def _compose_model(contract: dict[str, Any]) -> ET.Element:
    model = contract["model"]
    base_spec = model["base_urdf"]
    gripper_spec = model["gripper_xacro"]
    base_path = ROOT / base_spec["local_path"]
    gripper_path = ROOT / gripper_spec["local_path"]
    _verify_source(base_path, base_spec["local_sha256_lf"], base_spec["upstream_sha256_crlf"])
    _verify_source(
        gripper_path,
        gripper_spec["local_sha256_lf"],
        gripper_spec["upstream_sha256_crlf"],
    )

    base = ET.parse(base_path).getroot()
    gripper = ET.parse(gripper_path).getroot()
    _require(base.get("name") == model["name"], "base URDF robot name mismatch")
    _require(gripper.get("name") == model["name"], "gripper Xacro robot name mismatch")
    includes = [child for child in gripper if child.tag.endswith("include")]
    _require(len(includes) == 1, "gripper Xacro must have exactly one include")
    _require(
        includes[0].get("filename", "").endswith(base_spec["path"]),
        "gripper Xacro does not include the pinned base URDF",
    )
    for child in list(gripper):
        if not child.tag.endswith("include"):
            base.append(child)

    # Placo needs the upstream link/joint graph, not unavailable package:// meshes.
    for link in base.findall("link"):
        for tag in ("visual", "collision"):
            for child in link.findall(tag):
                link.remove(child)
    return base


def _verify_frames_and_joints(root: ET.Element, contract: dict[str, Any]) -> None:
    frames = contract["frames"]
    expected_chain = [frames["base"], *frames["serial_links"]]
    for index, mapping in enumerate(contract["joint_mapping"], start=1):
        _require(mapping["order"] == index, f"joint mapping order mismatch at {index}")
        _require(mapping["plugin_name"] == PIPER_JOINT_NAMES[index - 1], "plugin joint order mismatch")
        _require(mapping["urdf_name"] == f"joint{index}", "URDF joint rename mismatch")
        _require(mapping["sign"] == 1, f"joint {index} is not a positive identity mapping")
        _require(
            math.isclose(mapping["scale_urdf_rad_per_plugin_degree"], math.pi / 180.0),
            f"joint {index} degree/radian scale mismatch",
        )
        joint = _joint_by_name(root, mapping["urdf_name"])
        parent = _child(joint, "parent")
        child = _child(joint, "child")
        _require(parent.get("link") == expected_chain[index - 1], f"joint {index} parent mismatch")
        _require(child.get("link") == expected_chain[index], f"joint {index} child mismatch")
        _require(_child(joint, "axis").get("xyz") == "0 0 1", f"joint {index} axis mismatch")
        limit = _child(joint, "limit")
        actual_deg = np.rad2deg(
            [float(_attribute(limit, "lower")), float(_attribute(limit, "upper"))]
        )
        _require(
            np.allclose(
                actual_deg,
                mapping["limits_deg"],
                atol=contract["verification"]["joint_limit_tolerance_deg"],
                rtol=0.0,
            ),
            f"joint {index} limits mismatch",
        )

    fixed_checks = (
        ("world_to_base_link", frames["root"], frames["base"], frames["world_to_base_link"]),
        ("flange_joint", "link6", frames["flange"], frames["link6_to_flange_link"]),
        (
            "gripper_base_joint",
            frames["flange"],
            frames["tool"],
            frames["flange_link_to_gripper_base"],
        ),
    )
    for name, parent_name, child_name, expected in fixed_checks:
        joint = _joint_by_name(root, name)
        _require(joint.get("type") == "fixed", f"{name} is not fixed")
        _require(_child(joint, "parent").get("link") == parent_name, f"{name} parent mismatch")
        _require(_child(joint, "child").get("link") == child_name, f"{name} child mismatch")
        xyz, rpy = _origin(joint)
        _require(np.allclose(xyz, expected["xyz_m"], atol=1e-12), f"{name} xyz mismatch")
        _require(np.allclose(rpy, expected["rpy_rad"], atol=1e-12), f"{name} rpy mismatch")
    _require(frames["tool"] == frames["tcp"] == "gripper_base", "model TCP mismatch")


def _verify_gripper(root: ET.Element, contract: dict[str, Any]) -> None:
    spec = contract["gripper"]
    joint = _joint_by_name(root, spec["model_joint"])
    _require(joint.get("type") == "prismatic", "model gripper is not prismatic")
    limit = _child(joint, "limit")
    _require(
        np.allclose(
            [float(_attribute(limit, "lower")), float(_attribute(limit, "upper"))],
            spec["model_limits_m"],
            atol=1e-12,
        ),
        "model gripper limits mismatch",
    )
    for name, expected in spec["finger_mimics"].items():
        mimic = _child(_joint_by_name(root, name), "mimic")
        _require(mimic.get("joint") == spec["model_joint"], f"{name} mimic mismatch")
        _require(
            float(_attribute(mimic, "multiplier")) == expected["multiplier"],
            f"{name} multiplier mismatch",
        )
        _require(
            float(_attribute(mimic, "offset")) == expected["offset"],
            f"{name} offset mismatch",
        )


def _orientation_error_rad(actual: np.ndarray, expected: np.ndarray) -> float:
    relative = actual[:3, :3] @ expected[:3, :3].T
    cosine = float(np.clip((np.trace(relative) - 1.0) / 2.0, -1.0, 1.0))
    return math.acos(cosine)


def verify_model(work_dir: Path) -> dict[str, float | int | str]:
    contract = _load_yaml(MODEL_CONTRACT_PATH)
    calibration = _load_yaml(CALIBRATION_INTERFACE_PATH)
    _require(calibration["revision"] == "piper_x_calibration_interface_v1", "calibration revision mismatch")
    _require(calibration["status"] == "interface_only_no_physical_values", "calibration status mismatch")
    root = _compose_model(contract)
    _verify_frames_and_joints(root, contract)
    _verify_gripper(root, contract)

    composed_path = work_dir / "piper_x_gate_c.urdf"
    ET.ElementTree(root).write(composed_path, encoding="utf-8", xml_declaration=True)
    kinematics_spec = contract["kinematics"]
    solver = RobotKinematics(
        str(composed_path),
        kinematics_spec["target_frame"],
        kinematics_spec["joint_names"],
    )
    checks = contract["verification"]
    matrix_tolerance = checks["matrix_absolute_tolerance"]
    for name, reference in checks["fk_references"].items():
        actual = solver.forward_kinematics(np.asarray(reference["q_deg"], dtype=float))
        _require(
            np.allclose(actual, reference["T_base_tcp"], atol=matrix_tolerance, rtol=0.0),
            f"FK reference mismatch: {name}",
        )

    direction = checks["positive_direction_reference"]
    q_reference = np.asarray(direction["q_deg"], dtype=float)
    for index, mapping in enumerate(contract["joint_mapping"]):
        perturbed = q_reference.copy()
        perturbed[index] += direction["delta_deg"]
        actual = solver.forward_kinematics(perturbed)
        expected = direction["T_base_tcp"][mapping["plugin_name"]]
        _require(
            np.allclose(actual, expected, atol=matrix_tolerance, rtol=0.0),
            f"positive direction reference mismatch: {mapping['plugin_name']}",
        )

    target_q = np.asarray(checks["ik_target_q_deg"], dtype=float)
    target_pose = solver.forward_kinematics(target_q)
    solved_q = np.asarray(checks["ik_seed_q_deg"], dtype=float)
    for _ in range(checks["ik_iterations"]):
        solved_q = solver.inverse_kinematics(
            solved_q,
            target_pose,
            position_weight=1.0,
            orientation_weight=1.0,
        )
    solved_pose = solver.forward_kinematics(solved_q)
    position_error = float(np.linalg.norm(solved_pose[:3, 3] - target_pose[:3, 3]))
    orientation_error = _orientation_error_rad(solved_pose, target_pose)
    _require(position_error <= checks["ik_position_tolerance_m"], "IK position error exceeded")
    _require(orientation_error <= checks["ik_orientation_tolerance_rad"], "IK orientation error exceeded")
    for value, mapping in zip(solved_q, contract["joint_mapping"], strict=True):
        lower, upper = mapping["limits_deg"]
        tolerance = checks["joint_limit_tolerance_deg"]
        _require(lower - tolerance <= value <= upper + tolerance, f"IK limit failure: {mapping['plugin_name']}")

    return {
        "fk_references": len(checks["fk_references"]),
        "positive_direction_references": len(contract["joint_mapping"]),
        "ik_position_error_m": position_error,
        "ik_orientation_error_rad": orientation_error,
        "lerobot_version": version("lerobot"),
        "placo_version": version("placo"),
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="piperx-gate-c-") as directory:
        result = verify_model(Path(directory))
    print("GATE C OFFLINE MODEL VERIFICATION: PASS")
    print("MODEL: AgileX PIPER-X f6642ce0d7872c686f29c99e9e10cd23d1d49313")
    print("FRAMES: base_link -> link1..link6 -> flange_link -> gripper_base (model TCP)")
    print("JOINT MAP: plugin joint_1..joint_6 -> URDF joint1..joint6, sign +1, degrees")
    print("GRIPPER: Gate A signed-mm action/absolute-mm observation preserved; URDF aperture remains model-native")
    print(f"KINEMATICS: LeRobot {result['lerobot_version']} RobotKinematics / Placo {result['placo_version']}")
    print(f"FK REFERENCES: {result['fk_references']} PASS")
    print(f"POSITIVE-DIRECTION REFERENCES: {result['positive_direction_references']} PASS")
    print("IK TARGET->SOLVE->FK: PASS within registered position/orientation tolerances and joint limits")
    print("CALIBRATION: piper_x_calibration_interface_v1 (interface only; physical values deferred to R1)")
    print("ROBOT/CAN ACTIVITY: NONE")


if __name__ == "__main__":
    main()
