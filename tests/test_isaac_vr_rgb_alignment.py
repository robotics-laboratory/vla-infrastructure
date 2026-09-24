"""CPU tests for the independent offline RGB spatial oracle."""

from __future__ import annotations

import numpy as np

from tools.isaac_vr_rgb_alignment import (
    CENTER_TOLERANCE_PX,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    MIN_MASK_PIXELS,
    box_iou,
    compare_geometry,
    mask_bounds,
    project_cube,
)


IDENTITY = np.array([1.0, 0.0, 0.0, 0.0])
ORIGIN = np.zeros(3)


def projection(x: float, *, camera_x: float = 0.0):
    return project_cube(
        np.array([x, 0.0, -1.0]), IDENTITY,
        np.array([camera_x, 0.0, 0.0]), IDENTITY,
        18.0, 20.955, 15.71625,
    )


def test_projection_math_visibility_and_orientation() -> None:
    center = projection(0.0)
    assert center.visibility == "in_frame"
    assert np.allclose(center.center, (IMAGE_WIDTH / 2, IMAGE_HEIGHT / 2))
    assert center.bounds is not None
    assert 19 < center.bounds[2] - center.bounds[0] < 26
    assert projection(2.0).visibility == "out_of_frame"
    partial = projection(0.60)
    assert partial.visibility == "partial_out_of_frame"
    assert partial.bounds is not None and partial.bounds[2] == IMAGE_WIDTH
    assert compare_geometry(partial, None)["pass"]
    assert project_cube(ORIGIN, IDENTITY, ORIGIN, IDENTITY, 18, 20.955, 15.71625).visibility == "near_plane_or_behind"
    rotated = project_cube(
        np.array([0.0, 0.0, -1.0]),
        np.array([np.cos(np.pi / 8), 0, 0, np.sin(np.pi / 8)]),
        ORIGIN, IDENTITY, 18, 20.955, 15.71625,
    )
    assert rotated.bounds is not None
    assert rotated.bounds[2] - rotated.bounds[0] > center.bounds[2] - center.bounds[0]


def test_mask_tolerance_and_out_of_frame_logic() -> None:
    expected = projection(0.0)
    assert expected.bounds is not None
    assert compare_geometry(expected, expected.bounds)["pass"]
    shifted = tuple(value + (3 if index % 2 == 0 else 2) for index, value in enumerate(expected.bounds))
    assert compare_geometry(expected, shifted)["pass"]
    assert box_iou(expected.bounds, shifted) > 0.5
    assert not compare_geometry(expected, None)["pass"]
    assert compare_geometry(projection(2.0), None)["pass"]
    assert not compare_geometry(projection(2.0), expected.bounds)["pass"]
    mask = np.zeros((IMAGE_HEIGHT, IMAGE_WIDTH), dtype=bool)
    mask[100:110, 200:210] = True
    assert mask_bounds(mask) == (200.0, 100.0, 210.0, 110.0)
    mask[:] = False
    mask[100, 200 : 200 + MIN_MASK_PIXELS - 1] = True
    assert mask_bounds(mask) is None


def test_deliberately_lagged_role_swapped_and_wrong_transform_fail() -> None:
    current = projection(0.0)
    previous = projection(0.35)
    assert current.bounds is not None and previous.bounds is not None
    assert not compare_geometry(previous, current.bounds)["pass"]
    assert not compare_geometry(projection(0.0, camera_x=0.35), current.bounds)["pass"]
    assert not compare_geometry(projection(-0.35), current.bounds)["pass"]
    assert CENTER_TOLERANCE_PX < abs(current.center[0] - previous.center[0])


def test_frozen_geometry_at_known_moving_witness_fails() -> None:
    first = projection(-0.25)
    moved = projection(0.25)
    assert first.bounds is not None and moved.bounds is not None
    assert compare_geometry(first, first.bounds)["pass"]
    assert not compare_geometry(moved, first.bounds)["pass"]
