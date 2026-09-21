#!/usr/bin/env python3
"""Concrete Gate S1 asset materialization and D0/Isaac edge processors.

This module deliberately has no Isaac or LeRobot imports.  The executable runner imports
Isaac Lab only after Kit starts; core tests can exercise the semantic boundary offline.
"""

from __future__ import annotations

import hashlib
import math
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np


D0_PROCESSOR_REVISION = "piper_x_d0_isaac_edge_mapping_v1"

ISAAC_ARM_JOINT_NAMES = ("joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "gripper")
JOINT_LIMITS_DEG = np.asarray(
    [[-150.0, 150.0], [0.0, 180.0], [-170.0, 0.0], [-89.0, 89.0], [-89.0, 89.0], [-120.0, 120.0]],
    dtype=np.float64,
)
GRIPPER_LIMITS_MM = np.asarray([0.0, 100.0], dtype=np.float64)


class S1ConfigurationError(RuntimeError):
    """Raised when a checked S1 invariant is not satisfied."""


@dataclass(frozen=True)
class NativeBimanualTargets:
    """Separate native command derived from, but never substituted for, a D0 label."""

    left_rad_m: np.ndarray
    right_rad_m: np.ndarray
    saturated: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def seed_reset(seed: int) -> None:
    """Apply the S1 deterministic reset seed to all non-Isaac RNGs."""

    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def materialize_gate_c_urdf(source_checkout: Path, output_path: Path) -> str:
    """Resolve the single accepted Xacro include while preserving meshes and frames."""

    base_path = source_checkout / "piper_x/urdf/piper_x_description.urdf"
    gripper_path = source_checkout / "piper_x/urdf/piper_x_with_gripper_description.xacro"
    expected = {
        base_path: "34126caac7d5b37bc2409f337ac246afbe0bb8cd47fc9f16df5038f19bd21e3a",
        gripper_path: "0ee3f52f9acf3060a7f3e439c6e5e46b6a53d4fa509dd495045548be6b7f90cd",
    }
    for path, digest in expected.items():
        if not path.is_file():
            raise S1ConfigurationError(f"missing accepted Gate C source: {path}")
        if sha256_file(path) != digest:
            raise S1ConfigurationError(f"Gate C source SHA-256 mismatch: {path}")

    base = ET.parse(base_path).getroot()
    gripper = ET.parse(gripper_path).getroot()
    includes = [element for element in gripper if element.tag.endswith("include")]
    if len(includes) != 1:
        raise S1ConfigurationError("accepted gripper Xacro no longer has exactly one include")
    if not includes[0].get("filename", "").endswith("piper_x/urdf/piper_x_description.urdf"):
        raise S1ConfigurationError("accepted gripper Xacro include changed")
    for element in list(gripper):
        if not element.tag.endswith("include"):
            base.append(element)

    # The accepted aperture coordinate uses a geometry-free child link. PhysX requires
    # positive mass properties for that dynamic link, so provide a tiny inertial carrier;
    # this does not alter any joint, frame, limit, visual, collision, or FK semantics.
    aperture_link = base.find("link[@name='gripper_link']")
    if aperture_link is None or list(aperture_link):
        raise S1ConfigurationError("accepted geometry-free gripper_link changed")
    inertial = ET.SubElement(aperture_link, "inertial")
    ET.SubElement(inertial, "origin", {"xyz": "0 0 0", "rpy": "0 0 0"})
    ET.SubElement(inertial, "mass", {"value": "0.001"})
    ET.SubElement(
        inertial,
        "inertia",
        {
            "ixx": "1e-7",
            "ixy": "0",
            "ixz": "0",
            "iyy": "1e-7",
            "iyz": "0",
            "izz": "1e-7",
        },
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(base, space="  ")
    ET.ElementTree(base).write(output_path, encoding="utf-8", xml_declaration=True)
    return sha256_file(output_path)


def _checked_vector(
    values: Sequence[float] | np.ndarray, *, length: int, name: str
) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float64)
    if vector.shape != (length,):
        raise ValueError(f"{name} must have shape ({length},), got {vector.shape}")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} contains a non-finite value")
    return vector.copy()


def d0_action_to_native(action: Sequence[float] | np.ndarray) -> NativeBimanualTargets:
    """Convert D0 degrees/signed-mm into clipped Isaac radians/model-aperture targets.

    The caller's label is copied before conversion.  Clipping affects only the returned native
    command, never the source label that belongs in ``dataset.action``.
    """

    d0 = _checked_vector(action, length=14, name="D0 action")
    native_arms: list[np.ndarray] = []
    saturated = False
    for offset in (0, 7):
        source_joints = d0[offset : offset + 6]
        source_gripper = d0[offset + 6]
        clipped_joints = np.clip(source_joints, JOINT_LIMITS_DEG[:, 0], JOINT_LIMITS_DEG[:, 1])
        clipped_gripper = float(np.clip(source_gripper, *GRIPPER_LIMITS_MM))
        saturated |= not np.array_equal(source_joints, clipped_joints)
        saturated |= source_gripper != clipped_gripper
        native_arms.append(np.concatenate((np.deg2rad(clipped_joints), [clipped_gripper / 1000.0])))
    return NativeBimanualTargets(native_arms[0], native_arms[1], saturated)


def native_state_to_d0(left_rad_m, right_rad_m) -> np.ndarray:
    """Canonical measured joint degrees and absolute gripper millimetres."""
    native_arms = [
        _checked_vector(left_rad_m, length=7, name="left native observation"),
        _checked_vector(right_rad_m, length=7, name="right native observation"),
    ]
    d0_arms = []
    for arm in native_arms:
        d0_arms.append(np.concatenate((np.rad2deg(arm[:6]), [abs(arm[6]) * 1000.0])))

    return np.concatenate(d0_arms).astype(np.float32)


def native_observation_to_d0(
    left_rad_m: Sequence[float] | np.ndarray,
    right_rad_m: Sequence[float] | np.ndarray,
    left_image: np.ndarray,
    right_image: np.ndarray,
) -> dict[str, np.ndarray]:
    """Map the plain S1 state/wrist subset; this is not a complete D0 v4 source view."""

    def rgb(value: np.ndarray, role: str) -> np.ndarray:
        array = np.asarray(value)
        if array.shape not in {(480, 640, 3), (480, 640, 4)}:
            raise ValueError(f"{role} image must be 480x640 RGB/RGBA HWC, got {array.shape}")
        if array.dtype != np.uint8:
            raise ValueError(f"{role} image must be uint8, got {array.dtype}")
        return np.ascontiguousarray(array[..., :3])

    return {
        "observation.state": native_state_to_d0(left_rad_m, right_rad_m),
        "observation.images.left_wrist": rgb(left_image, "left_wrist"),
        "observation.images.right_wrist": rgb(right_image, "right_wrist"),
    }


def quaternion_xyzw_to_matrix(quaternion: Sequence[float] | np.ndarray) -> np.ndarray:
    """Convert Isaac Lab's documented xyzw quaternion to a 3x3 matrix."""

    x, y, z, w = _checked_vector(quaternion, length=4, name="quaternion")
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0.0:
        raise ValueError("zero quaternion")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def pose_xyzw_to_matrix(pose: Sequence[float] | np.ndarray) -> np.ndarray:
    checked = _checked_vector(pose, length=7, name="pose")
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = quaternion_xyzw_to_matrix(checked[3:])
    transform[:3, 3] = checked[:3]
    return transform


def relative_pose_matrix(
    base_pose: Sequence[float] | np.ndarray, tcp_pose: Sequence[float] | np.ndarray
) -> np.ndarray:
    return np.linalg.inv(pose_xyzw_to_matrix(base_pose)) @ pose_xyzw_to_matrix(tcp_pose)


def transform_error(actual: np.ndarray, expected: Sequence[Sequence[float]]) -> tuple[float, float]:
    expected_array = np.asarray(expected, dtype=np.float64)
    position = float(np.linalg.norm(actual[:3, 3] - expected_array[:3, 3]))
    relative_rotation = actual[:3, :3] @ expected_array[:3, :3].T
    cosine = float(np.clip((np.trace(relative_rotation) - 1.0) / 2.0, -1.0, 1.0))
    return position, math.acos(cosine)


def jsonable(value: Any) -> Any:
    """Convert runtime arrays/scalars into stable JSON values."""

    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value
