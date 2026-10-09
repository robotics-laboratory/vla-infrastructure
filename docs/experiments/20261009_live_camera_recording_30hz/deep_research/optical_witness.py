"""Probe-only camera-relative optical source IDs. No Kit/pxr/OVRTX imports.
16 emissive moving cells per camera: 12 row bits, 2 role bits, white/black anchors.
Bit value is cell row (upper=1, lower=0), not a metadata label or postrender paint.
Boards alter the scene; a passing board proves source phase, not all-body coverage.
"""

import numpy as np


def paths(role):
    return [f"/LiveWitness/r{role}_board"] + [f"/LiveWitness/r{role}_bit{i}" for i in range(16)]


def usd():
    materials = []
    for name, value in [("White", 5), ("Black", 0)]:
        materials.append(f'''def Material "{name}" {{
 token outputs:surface.connect = </LiveWitness/{name}/Shader.outputs:surface>
 def Shader "Shader" {{
  uniform token info:id = "UsdPreviewSurface"
  color3f inputs:diffuseColor = (0, 0, 0)
  color3f inputs:emissiveColor = ({value}, {value}, {value})
  float inputs:roughness = 1
  token outputs:surface
 }}
}}''')
    objects = []
    for role in range(3):
        for i, path in enumerate(paths(role)):
            material = "Black" if i == 0 else "White"
            objects.append(f'''def Cube "{path.rsplit("/", 1)[1]}" (prepend apiSchemas = ["MaterialBindingAPI"]) {{
 double size = 1
 rel material:binding = </LiveWitness/{material}>
}}''')
    return 'def Scope "LiveWitness" {\n' + "\n".join(materials + objects) + "\n}\n"


def matrices(camera_world, intrinsics, source_index, role, width=960, height=600):
    if not 0 <= source_index < 4096 or not 0 <= role < 3:
        raise ValueError("Witness supports source rows0..4095 and roles0..2")
    focal, aperture_x, aperture_y = intrinsics
    fx, fy = width * focal / aperture_x, height * focal / aperture_y
    bits = [(source_index >> i) & 1 for i in range(12)] + [role & 1, (role >> 1) & 1, 1, 0]
    pixel_specs = [(width / 2, height / 2, 342, 72, 0.061)]
    pixel_specs += [
        (width / 2 - 150 + 20 * i, height / 2 + (-20 if bit else 20), 12, 12, 0.06)
        for i, bit in enumerate(bits)
    ]
    result = []
    for x, y, sx, sy, z in pixel_specs:
        matrix = np.diag([sx * z / fx, sy * z / fy, 0.00015, 1.0])
        matrix[3, :3] = [(x - width / 2) * z / fx, -(y - height / 2) * z / fy, -z]
        result.append(matrix @ camera_world)
    return np.asarray(result)


def decode(image):
    height, width = image.shape[:2]
    values = []
    for i in range(16):
        x = int(width / 2 - 150 + 20 * i)
        lum = []
        for y in [int(height / 2 - 20), int(height / 2 + 20)]:
            lum.append(float(np.median(image[y - 1 : y + 2, x - 1 : x + 2, :3])))
        values.append(lum[0] - lum[1])
    bits = [int(v > 0) for v in values]
    row = sum(b << i for i, b in enumerate(bits[:12]))
    role = bits[12] + 2 * bits[13]
    return dict(
        row=row,
        role=role,
        min_contrast=min(abs(v) for v in values),
        anchors_ok=bits[14:] == [1, 0],
        cell_contrasts=values,
        confident=min(abs(v) for v in values) >= 30 and bits[14:] == [1, 0],
    )
