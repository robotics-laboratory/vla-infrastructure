"""Evaluate pinned delta/matrix functions, without Isaac or an XR client."""
import ast
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

repo = Path(__file__).resolve().parents[4]
upstream = Path('/data/vla-infrastructure/envs/isaac-s1-candidate-b/lib/python3.12/site-packages/isaacteleop/retargeters/se3_retargeter.py')

def extract(path, name):
    tree = ast.parse(path.read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {'np': np, 'Rotation': Rotation}
    text = 'from __future__ import annotations\n' + ast.unparse(node)
    exec(compile(text, str(path), 'exec'), scope)
    return scope[name]

delta_pose = extract(upstream, '_calculate_delta_pose')
row_to_column = extract(repo / 'tools/isaac_s2_upstream.py', '_gf_row_matrix_to_numpy_transform')
oxr_to_usd = Rotation.from_euler('x', 90, degrees=True).as_matrix()
initial = np.eye(4)
initial[:3, :3] = Rotation.from_euler('z', -90, degrees=True).as_matrix() @ oxr_to_usd
initial[:3, 3] = [-0.05, 0, -0.1]
new = initial.copy()
new[:3, :3] = Rotation.from_euler('z', 90, degrees=True).as_matrix() @ initial[:3, :3]
new[:3, 3] = [0.6, -0.2, 1.3]
physical_position = np.array([0.2, 1.2, -0.4])
def pose(matrix, position):
    return np.r_[matrix[:3, :3] @ position + matrix[:3, 3], Rotation.from_matrix(matrix[:3, :3]).as_quat()]

converted = row_to_column(new.T.tolist())
np.testing.assert_allclose(converted, new, atol=1e-6)
before = pose(new, physical_position)
after = pose(new, physical_position + [0.01, 0, 0])
expected_right = new[:3, :3] @ np.array([1, 0, 0])
measured = delta_pose(None, after, before)
np.testing.assert_allclose(measured[:3], 0.01 * expected_right, atol=1e-7)
np.testing.assert_allclose(measured[3:], 0, atol=1e-7)
stale_delta = delta_pose(None, pose(initial, physical_position + [0.01, 0, 0]), pose(initial, physical_position))
dot = float(np.dot(stale_delta[:3] / np.linalg.norm(stale_delta[:3]), expected_right))
np.testing.assert_allclose(dot, 0, atol=1e-7)
origin_jump = delta_pose(None, pose(new, physical_position), pose(initial, physical_position))

results = {
    'scope': 'synthetic transforms evaluated with exact pinned function bodies; not a live R3 reproduction',
    'gf_row_to_column_roundtrip_passed': True,
    'full_navigation_transform_right_delta_passed': True,
    'new_view_right_world': expected_right.tolist(),
    'world_delta_m_rad': measured.tolist(),
    'stale_anchor_delta_m_rad': stale_delta.tolist(),
    'stale_direction_dot_new_view_right': dot,
    'unchanged_controller_across_transform_change_delta_m_rad': origin_jump.tolist(),
    'origin_jump_translation_norm_m': float(np.linalg.norm(origin_jump[:3])),
    'origin_jump_rotation_norm_rad': float(np.linalg.norm(origin_jump[3:])),
    'proper_new_epoch_baseline_delta': delta_pose(None, before, before).tolist(),
}
Path('/tmp/piper_xr_frame_math_result.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
