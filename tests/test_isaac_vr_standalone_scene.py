"""CPU-only scene adapter tests; optional OpenUSD is provided by Isaac Python."""

from types import SimpleNamespace

import numpy as np
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

    HAS_USD = True
except ImportError:
    HAS_USD = False

from tools.isaac_vr_standalone_ik import BODIES, DOFS
from tools.isaac_vr_standalone_scene import SnapshotPoses, build_seed


def make_scene(tmp_path):
    path = tmp_path / "source.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.SetStageUpAxis(stage, "Z")
    robots = []
    for side in ("Left", "Right"):
        root = f"/World/{side}Piper"
        UsdGeom.Xform.Define(stage, root)
        base = root + "/Geometry/world/base_link"
        body_paths = [base] + [base + "/" + name for name in BODIES[1:]]
        for body in body_paths:
            prim = UsdGeom.Xform.Define(stage, body).GetPrim()
            UsdPhysics.RigidBodyAPI.Apply(prim)
        UsdPhysics.ArticulationRootAPI.Apply(stage.GetPrimAtPath(base))
        stage.GetPrimAtPath(base).AddAppliedSchema("NewtonArticulationRootAPI")
        stage.GetPrimAtPath(base).CreateAttribute(
            "newton:selfCollisionEnabled", Sdf.ValueTypeNames.Bool
        ).Set(False)
        stage.GetPrimAtPath(base).CreateAttribute(
            "newton:jointsAddMobility", Sdf.ValueTypeNames.Bool
        ).Set(False)
        fixed = UsdPhysics.FixedJoint.Define(stage, root + "/Physics/world_to_base_link")
        fixed.CreateBody0Rel().SetTargets([root])
        fixed.CreateBody1Rel().SetTargets([base])
        joint_paths = [root + "/Physics/" + name for name in DOFS]
        for i, joint_path in enumerate(joint_paths):
            joint = UsdPhysics.PrismaticJoint.Define(stage, joint_path).GetPrim()
            if i > 6:
                joint.AddAppliedSchema("NewtonMimicAPI")
                joint.CreateRelationship("newton:mimicJoint").SetTargets([joint_paths[6]])
                joint.CreateAttribute("newton:mimicCoef0", Sdf.ValueTypeNames.Float).Set(0.0)
                joint.CreateAttribute("newton:mimicCoef1", Sdf.ValueTypeNames.Float).Set(
                    0.5 if i == 7 else -0.5
                )
        camera = UsdGeom.Camera.Define(stage, base + "/gripper_base/Camera")
        camera.AddTranslateOp().Set(Gf.Vec3d(1, 0, 0))
        view = SimpleNamespace(
            shared_metatype=SimpleNamespace(
                fixed_base=True, dof_names=list(DOFS), link_names=list(BODIES)
            ),
            dof_paths=[joint_paths],
            link_paths=[body_paths],
        )
        for getter in (
            "get_dof_positions",
            "get_dof_velocities",
            "get_dof_position_targets",
            "get_dof_velocity_targets",
            "get_dof_actuation_forces",
        ):
            setattr(view, getter, lambda: np.arange(9, dtype=np.float32)[None])
        for getter in (
            "get_dof_stiffnesses",
            "get_dof_dampings",
            "get_dof_max_forces",
            "get_dof_max_velocities",
        ):
            setattr(view, getter, lambda: np.array([[4, 4, 4, 4, 4, 4, 2, 0, 0]], np.float32))
        view.get_dof_limits = lambda: np.tile([-1, 1], (1, 9, 1)).astype(np.float32)
        view.get_drive_types = lambda: np.ones((1, 9), np.uint8)
        view.get_root_transforms = lambda: np.array([[0, 0, 0, 0, 0, 0, 1]], np.float32)
        view.get_link_transforms = lambda: np.tile([0, 0, 0, 0, 0, 0, 1], (1, 12, 1)).astype(
            np.float32
        )
        robots.append(SimpleNamespace(root_view=view))
    objects = []
    for name in ("LeftCube", "RightCube", "ValidationProbe"):
        body = "/World/RobosynDemo/" + name
        UsdPhysics.RigidBodyAPI.Apply(UsdGeom.Xform.Define(stage, body).GetPrim())
        view = SimpleNamespace(
            get_transforms=lambda: np.array([[0, 0, 0, 0, 0, 0, 1]], np.float32),
            get_velocities=lambda: np.zeros((1, 6), np.float32),
        )
        objects.append(SimpleNamespace(cfg=SimpleNamespace(prim_path=body), root_view=view))
    stage.GetRootLayer().Save()
    env = SimpleNamespace(
        robots=robots,
        sim=SimpleNamespace(get_physics_step_count=lambda: 8),
        vr_runtime=SimpleNamespace(dynamic_assets=objects[:2]),
        physics_probe=objects[2],
    )
    return env, path


@unittest.skipUnless(HAS_USD, "OpenUSD unavailable in this environment")
class StandaloneSceneTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.tmp_path = Path(self.directory.name)

    def test_seed_preserves_source_and_native_state(self):
        tmp_path = self.tmp_path
        env, source = make_scene(tmp_path)
        # Logically welded source can expose floating metadata in native Kit.
        env.robots[0].root_view.shared_metatype.fixed_base = False
        before = source.read_bytes()
        seed = build_seed(env, source, tmp_path / "out")
        assert source.read_bytes() == before
        assert seed["schema"] == "standalone_cpu_physx_seed_v1"
        assert seed["native_fixed_base"] == [False, True]
        assert seed["initial"]["q"][0] == list(range(9))
        assert seed["dof_properties"]["stiffness"][0][-2:] == [0, 0]
        assert len(seed["rigid_body_paths"]) == 27
        assert [entry["mimicCoef1"] for entry in seed["mimic_config"]] == [0.5, -0.5] * 2
        overlay = Usd.Stage.Open(seed["stage_overlay"])
        assert UsdGeom.GetStageMetersPerUnit(overlay) == 1
        assert UsdGeom.GetStageUpAxis(overlay) == "Z"
        for root in seed["articulation_roots"]:
            assert overlay.GetPrimAtPath(root).HasAPI(UsdPhysics.ArticulationRootAPI)
            assert not overlay.GetPrimAtPath(root).GetRelationship("physics:body0").GetTargets()
            assert (
                "NewtonArticulationRootAPI"
                in overlay.GetPrimAtPath(root).GetMetadata("apiSchemas").GetAppliedItems()
            )
            assert (
                overlay.GetPrimAtPath(root).GetAttribute("newton:selfCollisionEnabled").Get()
                is False
            )
        for entry in seed["adaptation"]["edits"]:
            assert (
                "NewtonArticulationRootAPI"
                not in overlay.GetPrimAtPath(entry["old_root"])
                .GetMetadata("apiSchemas")
                .GetAppliedItems()
            )
        for entry in seed["mimic_config"]:
            follower = overlay.GetPrimAtPath(entry["follower"])
            schemas = follower.GetMetadata("apiSchemas").GetAppliedItems()
            assert "NewtonMimicAPI" not in schemas
            assert "PhysxMimicJointAPI:rotX" in schemas
            assert (
                follower.GetAttribute("physxMimicJoint:rotX:gearing").Get() == -entry["mimicCoef1"]
            )
            assert (
                follower.GetAttribute("physxMimicJoint:rotX:offset").Get() == -entry["mimicCoef0"]
            )
        with self.assertRaises(FileExistsError):
            build_seed(env, source, tmp_path / "out")
        env.robots[0].root_view.shared_metatype.dof_names.reverse()
        with self.assertRaisesRegex(ValueError, "order"):
            build_seed(env, source, tmp_path / "changed_order")

    def test_mount_follows_nearest_body_and_static_container_stays(self):
        tmp_path = self.tmp_path
        env, source = make_scene(tmp_path)
        seed = build_seed(env, source, tmp_path / "out")
        resolver = SnapshotPoses(source, seed["rigid_body_paths"])
        body = "/World/LeftPiper/Geometry/world/base_link/gripper_base"
        poses = np.asarray(seed["initial"]["rigid_body_world_pose"], np.float32)
        index = seed["rigid_body_paths"].index(body)
        poses[index] = [3, 4, 0, 0, 0, np.sqrt(0.5), np.sqrt(0.5)]
        result = resolver.poses([body, body + "/Camera", "/World/LeftPiper"], poses)
        np.testing.assert_allclose(result[0, :3], [3, 4, 0], atol=1e-6)
        np.testing.assert_allclose(result[1, :3], [3, 5, 0], atol=1e-6)
        np.testing.assert_allclose(result[2], [0, 0, 0, 1, 0, 0, 0], atol=1e-6)
        with self.assertRaisesRegex(ValueError, "Unseeded"):
            resolver.poses(["/World/Missing"], poses)

    def test_seed_rejects_uncovered_body_and_active_mimic_drive(self):
        tmp_path = self.tmp_path
        env, source = make_scene(tmp_path)
        env.robots[0].root_view.get_dof_stiffnesses = lambda: np.ones((1, 9), np.float32)
        with self.assertRaisesRegex(ValueError, "passive"):
            build_seed(env, source, tmp_path / "active")
        stage = Usd.Stage.Open(str(source))
        UsdPhysics.RigidBodyAPI.Apply(UsdGeom.Xform.Define(stage, "/World/Uncovered").GetPrim())
        stage.GetRootLayer().Save()
        with self.assertRaisesRegex(ValueError, "coverage"):
            build_seed(env, source, tmp_path / "uncovered")
