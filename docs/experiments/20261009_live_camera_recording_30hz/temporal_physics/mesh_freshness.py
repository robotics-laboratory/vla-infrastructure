"""Opt-in rendering-only Mesh phase probe; shares existing camera-parent publication."""

import numpy as np

WIDTH, HEIGHT = 960, 600
Y, SIZE, DEPTH = 530, 20, 0.02
PROJECTION_POLICY = dict(aspectRatioConformPolicy="expandAperture", pixelAspectRatio=1.0, fx="width*focal/horizontalAperture", fy="fx")


def position(source_id):
    if not 0 <= source_id < 4096:
        raise ValueError("Temporal source ID must fit twelve optical bits")
    if source_id < 16:
        bit = 0
    elif source_id < 96:
        bit = source_id & 1
    elif source_id < 112:
        bit = 1
    elif source_id < 128:
        bit = (source_id // 8) & 1
    else:
        bit = ((source_id * 1103515245 + 12345) >> 16) & 1
    return 100 + 80 * bit


def classify(path, cameras):
    for role, _camera in enumerate(cameras):
        prefix = f"/LiveTemporalMesh/Role{role}/"
        if path.startswith(prefix):
            return dict(temporal_role=role, temporal_kind=path[len(prefix):])
    return {}


def pixel_matrix(x, y, width, height, depth, intrinsics):
    focal, aperture_x, aperture_y = intrinsics
    if aperture_x / aperture_y < WIDTH / HEIGHT:
        raise ValueError("Probe requires horizontal aperture fit with expandAperture")
    # The declared expandAperture/square-pixel product expands aperture height
    # for these 16:9 cameras at 960x600. Authored vertical aperture is not pixel K.
    fx = fy = WIDTH * focal / aperture_x
    matrix = np.diag([width * depth / fx, height * depth / fy, 1, 1]).astype("<f8")
    matrix[3, :3] = [(x - WIDTH / 2) * depth / fx, -(y - HEIGHT / 2) * depth / fy, -depth]
    return matrix


def local_matrix(kind, role, intrinsics, source_id):
    if kind == "background":
        return pixel_matrix(450, 532, 820, 86, DEPTH + .001, intrinsics)
    if kind == "marker":
        return pixel_matrix(position(source_id), Y, SIZE, SIZE, DEPTH, intrinsics)
    cell = int(kind.removeprefix("cell"))
    bits = [(source_id >> i) & 1 for i in range(12)] + [role & 1, (role >> 1) & 1, 1, 0]
    return pixel_matrix(300 + 24 * cell, 512 if bits[cell] else 552, 12, 12, DEPTH, intrinsics)


def inject(stage, cameras, *, products=None):
    """Add diagnostic geometry to the supplied stage, including explicit native products."""
    from pxr import Gf, Usd, UsdGeom, UsdShade, Sdf

    material_paths = {}
    for role in range(3):
        product = stage.GetPrimAtPath(products[role] if products else f"/Live30/Camera{role}")
        if not product:
            raise ValueError("Probe requires existing three render products")
        for name, value, type_name in [
            ("aspectRatioConformPolicy", "expandAperture", Sdf.ValueTypeNames.Token),
            ("pixelAspectRatio", 1.0, Sdf.ValueTypeNames.Float),
        ]:
            current = product.GetAttribute(name).Get()
            if current is not None and current != value:
                raise ValueError(f"Unsupported diagnostic product {name}: {current}")
            product.CreateAttribute(name, type_name, custom=False, variability=Sdf.VariabilityUniform).Set(value)
    for name, emission in [("Black", 0), ("White", 5)]:
        material = UsdShade.Material.Define(stage, "/LiveTemporalMaterials/" + name)
        shader = UsdShade.Shader.Define(stage, str(material.GetPath()) + "/Shader")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0))
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(emission))
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(1)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        material_paths[name] = material
    for role, camera in enumerate(cameras):
        cam = UsdGeom.Camera(stage.GetPrimAtPath(camera))
        if cam.GetProjectionAttr().Get() != "perspective" or cam.GetHorizontalApertureOffsetAttr().Get() or cam.GetVerticalApertureOffsetAttr().Get():
            raise ValueError("Probe requires centered perspective camera")
        intrinsics = [cam.GetFocalLengthAttr().Get(), cam.GetHorizontalApertureAttr().Get(), cam.GetVerticalApertureAttr().Get()]
        camera_world = np.array(cam.ComputeLocalToWorldTransform(Usd.TimeCode.Default()))
        # Cameras may inherit invisible. Keep diagnostic geometry outside that
        # namespace and explicitly bind its publication parent to this camera.
        for kind in ["background", "marker"] + [f"cell{i}" for i in range(16)]:
            mesh = UsdGeom.Mesh.Define(stage, f"/LiveTemporalMesh/Role{role}/" + kind)
            mesh.CreatePointsAttr([(-.5, -.5, 0), (.5, -.5, 0), (.5, .5, 0), (-.5, .5, 0)])
            mesh.CreateFaceVertexCountsAttr([4])
            mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
            mesh.CreateSubdivisionSchemeAttr("none")
            mesh.CreateDoubleSidedAttr(True)
            matrix = local_matrix(kind, role, intrinsics, 0) @ camera_world
            mesh.AddTransformOp().Set(Gf.Matrix4d(*matrix.reshape(-1).tolist()))
            UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material_paths["Black" if kind == "background" else "White"])


def update_locals(descendants, local, intrinsics, source_id):
    """Modify only opted-in Mesh locals; caller retains the sole locals@parents write."""
    result = local.copy()
    for index, item in enumerate(descendants):
        if "temporal_kind" in item:
            role = item["temporal_role"]
            result[index] = local_matrix(item["temporal_kind"], role, intrinsics[role], source_id)
    return result


def decode(image, expected_source, role, previous_source=None):
    """Independent image measurements; expected sequence never supplies decoded bits."""
    lum = np.median(image[..., :3].astype(float), axis=2)
    differences = []
    for cell in range(16):
        x = 300 + 24 * cell
        differences.append(float(np.median(lum[510:515, x-2:x+3]) - np.median(lum[550:555, x-2:x+3])))
    bits = [int(value > 0) for value in differences]
    decoded_source = sum(bit << index for index, bit in enumerate(bits[:12]))
    decoded_role = bits[12] + 2 * bits[13]
    white = float(np.median(lum[510:515, 634:639]))  # cell14 white upper anchor
    black = float(np.median(lum[550:555, 634:639]))
    contrast = white - black
    x = position(expected_source)
    current = float(np.clip((lum[Y-6:Y+7, x-6:x+7].mean() - black) / max(contrast, 1), 0, 1))
    previous_x = position(previous_source) if previous_source is not None else x
    changed = previous_source is not None and x != previous_x
    ghost = float(np.clip((lum[Y-6:Y+7, previous_x-6:previous_x+7].mean() - black) / max(contrast, 1), 0, 1)) if changed else None
    roi = lum[Y-16:Y+17, 75:206]
    weights = np.maximum(roi - (black + .5 * max(contrast, 1)), 0)
    yy, xx = np.indices(weights.shape)
    centroid = [float((weights * (xx + 75)).sum() / weights.sum()), float((weights * (yy + Y - 16)).sum() / weights.sum())] if weights.sum() else None
    centroid_error = float(np.linalg.norm(np.asarray(centroid) - [x, Y])) if centroid else None
    confident = min(abs(value) for value in differences) >= 30 and bits[14:] == [1, 0]
    passed = confident and decoded_source == expected_source and decoded_role == role and current >= .8 and centroid_error is not None and centroid_error <= 2 and (ghost is None or ghost <= .08)
    return dict(expected_source=expected_source, decoded_source=decoded_source, decoded_role=decoded_role,
                confident=confident, minimum_bit_contrast=min(abs(value) for value in differences),
                current_roi_normalized=current, changed_position=changed, previous_roi_normalized=ghost,
                measured_centroid=centroid, centroid_error_px=centroid_error, passed=passed)
