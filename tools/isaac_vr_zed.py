"""Compose pinned Stereolabs USD cameras with native Isaac Lab Camera sensors.

Only the rig root is moved. Authored optics remain unchanged; sensor housing
physics is disabled so the existing massless camera mounts do not alter robots.
No SDK, streaming graph, replacement capture owner, or camera subclass is used.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


def upstream_identity(selection: dict) -> dict:
    """Check the pin and the exact code/assets used by the SDK-free Lab path."""
    checkout = Path(selection["checkout"]).resolve()
    revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != selection["revision"]:
        raise RuntimeError("ZED upstream revision differs from selected pin")
    package = "exts/sl.sensor.camera/sl/sensor/camera/"
    paths = [package + "__init__.py", package + "utils.py", package + "isaaclab_utils.py",
             f"exts/sl.sensor.camera/data/usd/{selection['model']}.usdc"]
    hashes = {}
    for relative in paths:
        data = (checkout / relative).read_bytes()
        original = subprocess.check_output(
            ["git", "-C", str(checkout), "show", f"HEAD:{relative}"]
        )
        if relative.endswith("isaaclab_utils.py"):
            # The shared experiment checkout has an unrelated fixed-joint patch.
            # Compare the actual helper we call; record the full effective file.
            def helper(source):
                return next(ast.dump(node) for node in ast.parse(source).body
                            if isinstance(node, ast.FunctionDef) and node.name == "make_camera_cfg")
            unchanged = helper(data) == helper(original)
        else:
            unchanged = data == original
        if not unchanged:
            raise RuntimeError(f"Selected ZED source/asset differs from its pin: {relative}")
        hashes[relative] = hashlib.sha256(data).hexdigest()
    extension = checkout / "exts/sl.sensor.camera"
    if str(extension) not in sys.path:
        sys.path.insert(0, str(extension))
    from sl.sensor.camera import utils
    from sl.sensor.camera import isaaclab_utils
    for module in (utils, isaaclab_utils):
        if not Path(module.__file__).resolve().is_relative_to(extension):
            raise RuntimeError("ZED helpers were imported from a different checkout")
    resolution = utils.get_resolution(selection["model"], selection["resolution"])
    if resolution != [960, 600]:
        raise RuntimeError(f"Expected selected native SVGA dimensions, got {resolution}")
    return {"revision": revision, "model": selection["model"],
            "resolution": selection["resolution"], "native_resolution": resolution,
            "source_sha256": hashes, "path": "isaac_lab_authored_usd_sdk_free"}


def create_camera(stage: Any, root_path: str, camera: dict, selection: dict,
                  identity: dict, *, rgba: bool, wrist: bool, live_rgb_enabled: bool = True):
    """Attach the native sensor to the vendor optical prim at the original pose."""
    import torch
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics
    from isaaclab.sensors.camera import Camera
    from isaaclab.utils.math import (
        convert_camera_frame_orientation_convention,
        create_rotation_matrix_from_view,
        quat_from_matrix,
    )
    from sl.sensor.camera.isaaclab_utils import make_camera_cfg
    from sl.sensor.camera.utils import get_camera_paths, get_camera_usd_path

    if stage.GetPrimAtPath(root_path).IsValid():
        raise RuntimeError(f"ZED rig already exists: {root_path}")
    root = stage.DefinePrim(root_path, "Xform")
    asset = get_camera_usd_path(selection["model"])
    if not asset or not root.GetReferences().AddReference(asset):
        raise RuntimeError("Could not reference the pinned ZED USD")
    path = get_camera_paths(root_path, selection["model"])["left"]
    optical = stage.GetPrimAtPath(path)
    if not optical.IsA(UsdGeom.Camera):
        raise RuntimeError(f"Authored ZED optical camera missing: {path}")
    authored, reset_stack = UsdGeom.XformCache().ComputeRelativeTransform(optical, root)
    if reset_stack:
        raise RuntimeError("ZED optical frame resets its transform stack")
    if wrist:
        position = camera["offset_xyz_m"]
        rotation = convert_camera_frame_orientation_convention(
            torch.tensor([camera["offset_quat_xyzw"]], dtype=torch.float32),
            origin="world", target="opengl",
        )[0].tolist()
    else:
        position = camera["eye_m"]
        matrix = create_rotation_matrix_from_view(
            torch.tensor([position], dtype=torch.float32),
            torch.tensor([camera["target_m"]], dtype=torch.float32), "Z", device="cpu",
        )
        rotation = quat_from_matrix(matrix)[0].tolist()
    desired = Gf.Matrix4d(1)
    desired.SetRotate(Gf.Quatd(rotation[3], Gf.Vec3d(*rotation[:3])))
    desired.SetTranslateOnly(Gf.Vec3d(*position))
    # USD row-vector convention: optical_to_root * root_to_parent = desired.
    mount = UsdGeom.Xformable(root)
    mount.ClearXformOpOrder()
    mount.AddTransformOp().Set(authored.GetInverse() * desired)
    for prim in Usd.PrimRange(root):
        # Remove the schemas in the referencing layer: a disabled rigid body
        # still appears in native robot/contact-sensor body enumeration.
        for schema in (UsdPhysics.RigidBodyAPI, UsdPhysics.MassAPI, UsdPhysics.CollisionAPI):
            if prim.HasAPI(schema):
                prim.RemoveAPI(schema)
    optical.CreateAttribute("piper:zed_identity", Sdf.ValueTypeNames.String).Set(
        json.dumps(identity, sort_keys=True, separators=(",", ":"))
    )
    cfg = make_camera_cfg(path, selection["model"], selection["resolution"],
                          data_types=("rgba",) if rgba else ("rgb",), spawn_pinhole=False)
    cfg.update_latest_camera_pose = True
    cfg.renderer_cfg.enable_scene_partitioning = False
    if [cfg.width, cfg.height] != [camera["width"], camera["height"]]:
        raise RuntimeError("VR camera dimensions differ from native ZED configuration")
    receipt = {"root_path": root_path, "prim_path": path, "usd": asset,
               "desired_optical_matrix": [list(row) for row in desired],
               "authored_optical_matrix": [list(row) for row in authored],
               "mount_physics": "parented_massless_no_collision", **identity}
    return (Camera(cfg) if live_rgb_enabled else cfg), receipt


def verify_mounts(env: Any) -> dict:
    """Compare captured native optical poses with the preserved wrist/world poses."""
    import numpy as np
    from pxr import Gf, UsdGeom

    def matrix(position, quaternion):
        result = Gf.Matrix4d(1)
        result.SetRotate(Gf.Quatd(float(quaternion[3]), Gf.Vec3d(*map(float, quaternion[:3]))))
        result.SetTranslateOnly(Gf.Vec3d(*map(float, position)))
        return result

    cameras = {"left_wrist": env.camera.wrists[0], "right_wrist": env.camera.wrists[1],
               "scene": env.camera.scene_camera}
    receipts = {}
    for index, (role, camera) in enumerate(cameras.items()):
        if env.camera.live_rgb_enabled:
            data = camera.data
            position = data.pos_w.torch[0].detach().cpu().tolist()
            orientation = data.quat_w_opengl.torch[0].detach().cpu().tolist()
            actual = matrix(position, orientation)
            if role != "scene":
                pose = env.robots[index].data.body_link_pose_w.torch[0, env.wrist_ids[index]].cpu().tolist()
                actual = actual * matrix(pose[:3], pose[3:]).GetInverse()
        else:
            # Authored relative optics need no sensor or render in RECORD.
            optical = env.sim.stage.GetPrimAtPath(camera.prim_path)
            cache = UsdGeom.XformCache()
            if role == "scene":
                actual = cache.GetLocalToWorldTransform(optical)
            else:
                actual, resets = cache.ComputeRelativeTransform(
                    optical, env.sim.stage.GetPrimAtPath(env.wrist_paths[index])
                )
                if resets:
                    raise RuntimeError("ZED optical frame resets its transform stack")
        expected = env.camera.zed_mounts[role]["desired_optical_matrix"]
        error = float(np.max(np.abs(np.asarray(actual) - np.asarray(expected))))
        receipts[role] = {"max_matrix_error": error, "passed": error < 1e-4,
                          "actual_optical_matrix": [list(row) for row in actual]}
        if not receipts[role]["passed"]:
            raise RuntimeError(f"ZED optical pose differs from preserved camera pose: {role}: {error}")
    return receipts
