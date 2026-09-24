"""Pure spatial oracle for bounded offline RGB replay qualification.

Expected image coordinates come from recorded world poses and camera intrinsics.
Observed bounds come from a diagnostic renderer instance mask, never from this
projection.  This module has no Kit dependency and is not a dataset validator.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

import numpy as np


IMAGE_WIDTH = 640
IMAGE_HEIGHT = 480
CUBE_EDGE_M = 0.04
CENTER_TOLERANCE_PX = 24.0
MIN_BOX_IOU = 0.20
MIN_MASK_PIXELS = 12


@dataclass(frozen=True)
class Projection:
    bounds: tuple[float, float, float, float] | None
    center: tuple[float, float] | None
    visibility: str


def quaternion_rotation(wxyz: np.ndarray) -> np.ndarray:
    """World rotation matrix for the recorder's normalized wxyz quaternion."""
    q = np.asarray(wxyz, dtype=np.float64)
    if q.shape != (4,) or not np.isfinite(q).all():
        raise ValueError("orientation must be a finite wxyz quaternion")
    norm = np.linalg.norm(q)
    if norm < 1e-8:
        raise ValueError("orientation quaternion is zero")
    w, x, y, z = q / norm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def project_cube(
    position: np.ndarray,
    orientation: np.ndarray,
    camera_position: np.ndarray,
    camera_orientation: np.ndarray,
    focal_length_mm: float,
    horizontal_aperture_mm: float,
    vertical_aperture_mm: float,
    *,
    edge_m: float = CUBE_EDGE_M,
) -> Projection:
    """Project eight native cube corners through a recorded USD camera pose.

    USD camera optical axis is local -Z, with local +Y upward.  A box crossing
    the near plane is indeterminate and must not produce a passing comparison.
    """
    if min(focal_length_mm, horizontal_aperture_mm, vertical_aperture_mm, edge_m) <= 0:
        raise ValueError("camera intrinsics and cube edge must be positive")
    half = edge_m / 2
    corners = np.array(
        [(x, y, z) for x in (-half, half) for y in (-half, half) for z in (-half, half)]
    )
    world = corners @ quaternion_rotation(orientation).T + np.asarray(position)
    local = (world - np.asarray(camera_position)) @ quaternion_rotation(camera_orientation)
    depth = -local[:, 2]
    if np.any(depth <= 0.02):
        return Projection(None, None, "near_plane_or_behind")
    u = IMAGE_WIDTH / 2 + IMAGE_WIDTH * focal_length_mm / horizontal_aperture_mm * local[:, 0] / depth
    v = IMAGE_HEIGHT / 2 - IMAGE_HEIGHT * focal_length_mm / vertical_aperture_mm * local[:, 1] / depth
    raw = (float(u.min()), float(v.min()), float(u.max()), float(v.max()))
    if raw[2] <= 0 or raw[0] >= IMAGE_WIDTH or raw[3] <= 0 or raw[1] >= IMAGE_HEIGHT:
        return Projection(None, None, "out_of_frame")
    # A diagnostic mask is clipped to the render product; compare like bounds.
    bounds = (
        max(0.0, raw[0]), max(0.0, raw[1]),
        min(float(IMAGE_WIDTH), raw[2]), min(float(IMAGE_HEIGHT), raw[3]),
    )
    center = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
    raw_center = ((raw[0] + raw[2]) / 2, (raw[1] + raw[3]) / 2)
    partial = not (0 <= raw_center[0] < IMAGE_WIDTH and 0 <= raw_center[1] < IMAGE_HEIGHT)
    return Projection(bounds, center, "partial_out_of_frame" if partial else "in_frame")


def mask_bounds(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    pixels = np.asarray(mask, dtype=bool)
    if pixels.shape != (IMAGE_HEIGHT, IMAGE_WIDTH):
        raise ValueError("diagnostic mask must be 480x640")
    yy, xx = np.nonzero(pixels)
    if len(xx) < MIN_MASK_PIXELS:
        return None
    return (float(xx.min()), float(yy.min()), float(xx.max() + 1), float(yy.max() + 1))


def box_iou(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    x0, y0 = max(left[0], right[0]), max(left[1], right[1])
    x1, y1 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area_left = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    area_right = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = area_left + area_right - intersection
    return intersection / union if union > 0 else 0.0


def compare_static_relative(
    expected_dynamic: Projection,
    expected_static: Projection,
    observed_dynamic: tuple[float, float, float, float] | None,
    observed_static: tuple[float, float, float, float] | None,
) -> dict[str, float | bool | None]:
    """Compare a recorded dynamic witness against an independent world landmark."""
    if (
        expected_dynamic.center is None or expected_static.center is None
        or observed_dynamic is None or observed_static is None
    ):
        return {"pass": False, "relative_error_px": None}
    expected = np.subtract(expected_dynamic.center, expected_static.center)
    dynamic = ((observed_dynamic[0] + observed_dynamic[2]) / 2,
               (observed_dynamic[1] + observed_dynamic[3]) / 2)
    static = ((observed_static[0] + observed_static[2]) / 2,
              (observed_static[1] + observed_static[3]) / 2)
    error = float(np.linalg.norm(expected - np.subtract(dynamic, static)))
    return {"pass": error <= CENTER_TOLERANCE_PX, "relative_error_px": round(error, 3)}


def compare_geometry(
    expected: Projection,
    observed: tuple[float, float, float, float] | None,
) -> dict[str, float | bool | str | None]:
    """Return a fixed spatial verdict; no photometric or exact pixel criterion."""
    if expected.visibility == "near_plane_or_behind":
        return {"pass": False, "reason": "indeterminate_near_plane", "center_error_px": None, "iou": None}
    if expected.visibility == "out_of_frame":
        return {"pass": observed is None, "reason": "expected_out_of_frame", "center_error_px": None, "iou": None}
    if expected.visibility == "partial_out_of_frame" and observed is None:
        return {"pass": True, "reason": "partial_out_of_frame_unseen", "center_error_px": None, "iou": None}
    if expected.bounds is None or expected.center is None or observed is None:
        return {"pass": False, "reason": "missing_visible_witness", "center_error_px": None, "iou": None}
    center = ((observed[0] + observed[2]) / 2, (observed[1] + observed[3]) / 2)
    error = hypot(center[0] - expected.center[0], center[1] - expected.center[1])
    overlap = box_iou(expected.bounds, observed)
    return {
        "pass": error <= CENTER_TOLERANCE_PX and overlap >= MIN_BOX_IOU,
        "reason": "spatial_comparison",
        "center_error_px": round(error, 3),
        "iou": round(overlap, 4),
    }
