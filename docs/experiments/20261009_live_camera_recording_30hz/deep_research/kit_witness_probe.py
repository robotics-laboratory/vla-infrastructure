"""Probe-only optical clock, using the same witness geometry as standalone OVRTX."""

import numpy as np
import optical_witness as witness


class KitWitness:
    def __init__(self, stage, cameras):
        from pxr import Sdf, Usd, UsdGeom, UsdShade

        self.stage = stage
        self.layer = Sdf.Layer.CreateAnonymous("live30-witness.usda")
        if not self.layer.ImportFromString("#usda 1.0\n" + witness.usd()):
            raise RuntimeError("Witness layer failed parsing")
        stage.GetSessionLayer().subLayerPaths.append(self.layer.identifier)
        self.operations, self.intrinsics, self.camera_local = [], [], []
        with Usd.EditContext(stage, self.layer):
            # Include diffuse white for Minimal textured mode as well as emission.
            stage.GetPrimAtPath("/LiveWitness/White/Shader").GetAttribute(
                "inputs:diffuseColor"
            ).Set((1.0, 1.0, 1.0))
            for role, camera_path in enumerate(cameras):
                camera = UsdGeom.Camera(stage.GetPrimAtPath(camera_path))
                self.camera_local.append(
                    np.asarray(UsdGeom.Xformable(camera.GetPrim()).GetLocalTransformation())
                )
                self.intrinsics.append(
                    [
                        camera.GetFocalLengthAttr().Get(),
                        camera.GetHorizontalApertureAttr().Get(),
                        camera.GetVerticalApertureAttr().Get(),
                    ]
                )
                ops = []
                for index, source in enumerate(witness.paths(role)):
                    stage.GetPrimAtPath(source).SetActive(False)
                    cube = UsdGeom.Cube.Define(
                        stage, camera_path.rsplit("/", 1)[0] + "/Clock/" + source.rsplit("/", 1)[-1]
                    )
                    cube.GetSizeAttr().Set(1)
                    material = UsdShade.Material(
                        stage.GetPrimAtPath("/LiveWitness/" + ("Black" if index == 0 else "White"))
                    )
                    UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(material)
                    ops.append(cube.AddTransformOp(precision=UsdGeom.XformOp.PrecisionDouble))
                self.operations.append(ops)
        self.set_row(0)

    def set_row(self, index):
        from pxr import Gf

        for role, ops in enumerate(self.operations):
            matrices = witness.matrices(np.eye(4), self.intrinsics[role], index, role)
            for op, matrix in zip(ops, matrices, strict=True):
                matrix = matrix @ self.camera_local[role]
                op.Set(Gf.Matrix4d(*matrix.reshape(-1).tolist()))

    def close(self):
        paths = self.stage.GetSessionLayer().subLayerPaths
        paths.remove(self.layer.identifier)
