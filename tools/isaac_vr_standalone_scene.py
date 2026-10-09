"""Seed the opt-in CPU PhysX worker from the live native scene, without stepping.

Only derived artifacts are written. Native tensors are read once at one frozen
boundary; the exported scene and its Newton mimic schemas remain unchanged.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from tools.isaac_vr_standalone_ik import BODIES, DOFS


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _array(value, shape) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    elif hasattr(value, "numpy"):
        value = value.numpy()
    result = np.asarray(value, dtype=np.float32)
    if result.shape != shape or not np.isfinite(result).all():
        raise ValueError(f"Expected finite native array {shape}; got {result.shape}")
    return result.copy()


def _matrix_pose(matrix) -> np.ndarray:
    from pxr import Gf

    m = np.asarray(matrix, dtype=np.float64)
    if (
        m.shape != (4, 4)
        or not np.isfinite(m).all()
        or not np.allclose(m[:3, :3] @ m[:3, :3].T, np.eye(3), atol=1e-5, rtol=0)
        or not np.isclose(np.linalg.det(m[:3, :3]), 1, atol=1e-5)
        or not np.allclose(m[:, 3], [0, 0, 0, 1], atol=1e-7, rtol=0)
    ):
        raise ValueError("Pose mapping requires a rigid, unit-scale USD transform")
    rotation = Gf.Transform(Gf.Matrix4d(m.tolist())).GetRotation().GetQuat()
    return np.asarray([*m[3, :3], rotation.GetReal(), *rotation.GetImaginary()], np.float32)


class SnapshotPoses:
    """Resolve bodies, static containers and fixed camera mounts from one snapshot.

    All matrices use USD row-vector convention. No runtime USD/Fabric pose reads.
    Mutable mount/intrinsics/topology changes require a new seed/epoch.
    """

    def __init__(self, snapshot: Path, rigid_body_paths: list[str]):
        from pxr import Usd, UsdGeom

        if len(set(rigid_body_paths)) != len(rigid_body_paths):
            raise ValueError("Duplicate rigid body paths")
        self.body_paths = tuple(rigid_body_paths)
        self._body_index = {p: i for i, p in enumerate(self.body_paths)}
        stage = Usd.Stage.Open(str(Path(snapshot).resolve()))
        if not stage:
            raise ValueError("Cannot open source snapshot")
        cache = UsdGeom.XformCache()
        self._world = {
            str(prim.GetPath()): np.asarray(cache.GetLocalToWorldTransform(prim), np.float64)
            for prim in stage.Traverse()
            if prim.IsA(UsdGeom.Xformable)
        }
        self._reset_paths = {
            str(prim.GetPath())
            for prim in stage.Traverse()
            if prim.IsA(UsdGeom.Xformable) and UsdGeom.Xformable(prim).GetResetXformStack()
        }
        if not set(self.body_paths).issubset(self._world):
            raise ValueError("Source snapshot lacks required rigid body transforms")
        self._resolved: dict[str, tuple[int | None, np.ndarray]] = {}
        self._batches = {}

    def poses(self, paths, rigid_body_world_pose_xyzw) -> np.ndarray:
        values = _array(rigid_body_world_pose_xyzw, (len(self.body_paths), 7))
        if not np.allclose(np.linalg.norm(values[:, 3:], axis=1), 1, atol=1e-4, rtol=0):
            raise ValueError("Nonunit native world quaternion")
        paths = tuple(map(str, paths))
        if paths not in self._batches:
            for path in paths:
                if path in self._resolved:
                    continue
                if path not in self._world:
                    raise ValueError(f"Unseeded requested pose path: {path}")
                parent = path
                while parent and parent not in self._body_index:
                    if parent in self._reset_paths:
                        raise ValueError(
                            f"Unsupported reset transform in mounted pose path: {path}"
                        )
                    parent = parent.rsplit("/", 1)[0]
                if parent:
                    index = self._body_index[parent]
                    relative = self._world[path] @ np.linalg.inv(self._world[parent])
                else:
                    index, relative = None, self._world[path]
                self._resolved[path] = index, _matrix_pose(relative)
            rows = [self._resolved[p] for p in paths]
            indices = np.array([0 if i is None else i for i, _ in rows], dtype=int)
            dynamic = np.array([i is not None for i, _ in rows], dtype=bool)
            local = np.array([p for _, p in rows], np.float32).reshape(len(paths), 7)
            self._batches[paths] = indices, dynamic, local
        indices, dynamic, local = self._batches[paths]
        base = values[indices]
        q, r = base[:, 3:], local[:, [4, 5, 6, 3]]  # Native xyzw; local wxyz.
        t = 2 * np.cross(q[:, :3], local[:, :3])
        positions = base[:, :3] + local[:, :3] + q[:, 3:] * t + np.cross(q[:, :3], t)
        xyz = q[:, 3:] * r[:, :3] + r[:, 3:] * q[:, :3] + np.cross(q[:, :3], r[:, :3])
        w = q[:, 3:] * r[:, 3:] - np.sum(q[:, :3] * r[:, :3], axis=1, keepdims=True)
        result = np.concatenate([positions, w, xyz], axis=1)
        result[~dynamic] = local[~dynamic]
        return np.ascontiguousarray(result, dtype=np.float32)


def _fixed_base_overlay(snapshot: Path, output: Path, mimics: list[dict]) -> tuple[Path, dict]:
    from pxr import Sdf, Usd, UsdGeom, UsdPhysics

    source_hash = _sha(snapshot)
    source = Usd.Stage.Open(str(snapshot))
    if not source:
        raise ValueError("Cannot open exported source scene")
    if UsdGeom.GetStageMetersPerUnit(source) != 1.0 or UsdGeom.GetStageUpAxis(source) != "Z":
        raise ValueError("Pinned Piper seed requires metre/Z stage metadata")
    overlay = output / "physics_fixed_base.usda"
    if overlay.exists():
        raise FileExistsError(overlay)
    layer = Sdf.Layer.CreateNew(str(overlay))
    layer.subLayerPaths = [str(snapshot)]
    stage = Usd.Stage.Open(layer)
    for key in ("metersPerUnit", "upAxis", "timeCodesPerSecond", "framesPerSecond"):
        if source.HasAuthoredMetadata(key):
            stage.SetMetadata(key, source.GetMetadata(key))
    if source.GetDefaultPrim():
        stage.SetDefaultPrim(stage.GetPrimAtPath(source.GetDefaultPrim().GetPath()))
    edits = []
    for side in ("Left", "Right"):
        base_path = f"/World/{side}Piper/Geometry/world/base_link"
        joint_path = f"/World/{side}Piper/Physics/world_to_base_link"
        base, joint = stage.GetPrimAtPath(base_path), stage.GetPrimAtPath(joint_path)
        if not base.HasAPI(UsdPhysics.ArticulationRootAPI) or not joint.IsA(UsdPhysics.FixedJoint):
            raise ValueError("Unexpected Piper root/world weld authoring")
        body0 = list(joint.GetRelationship("physics:body0").GetTargets())
        body1 = list(joint.GetRelationship("physics:body1").GetTargets())
        if [str(p) for p in body0] != [f"/World/{side}Piper"] or [str(p) for p in body1] != [
            base_path
        ]:
            raise ValueError("Unexpected world weld body relationships")
        old_schemas = base.GetMetadata("apiSchemas").GetAppliedItems()
        root_schemas = ["PhysicsArticulationRootAPI", "PhysxArticulationAPI"]
        if "NewtonArticulationRootAPI" in old_schemas:
            # This API includes PhysicsArticulationRootAPI as a built-in API.
            # Deleting the latter alone leaves a second effective root in Kit.
            root_schemas.append("NewtonArticulationRootAPI")
        newton_root_attributes = {}
        # Exact installed NewtonArticulationRootAPI property inventory; do not
        # move NewtonMassAPI/body/link attributes off their physical link.
        for name in ("newton:selfCollisionEnabled", "newton:jointsAddMobility"):
            attribute = base.GetAttribute(name)
            if attribute and attribute.HasAuthoredValueOpinion() and attribute.Get() is not None:
                newton_root_attributes[name] = (attribute.GetTypeName(), attribute.Get())
        for schema in root_schemas:
            base.RemoveAppliedSchema(schema)
            joint.AddAppliedSchema(schema)
        joint.GetRelationship("physics:body0").SetTargets([])
        for attribute in base.GetAttributes():
            if attribute.GetName().startswith("physxArticulation:") and attribute.Get() is not None:
                joint.CreateAttribute(
                    attribute.GetName(), attribute.GetTypeName(), custom=attribute.IsCustom()
                ).Set(attribute.Get())
        for name, (kind, value) in newton_root_attributes.items():
            joint.CreateAttribute(name, kind, custom=False).Set(value)
        edits.append(
            dict(
                old_root=base_path,
                new_root=joint_path,
                relocated_root_schemas=root_schemas,
                relocated_newton_root_attributes={
                    k: v[1] for k, v in newton_root_attributes.items()
                },
            )
        )
    mimic_edits = []
    for entry in mimics:
        follower = stage.GetPrimAtPath(entry["follower"])
        leader = stage.GetPrimAtPath(entry["leader"])
        if not follower.IsA(UsdPhysics.PrismaticJoint) or not leader.IsA(UsdPhysics.PrismaticJoint):
            raise ValueError("Reviewed mimic translation requires single-DOF prismatic joints")
        schemas = follower.GetMetadata("apiSchemas").GetAppliedItems()
        if any(str(name).startswith("PhysxMimicJointAPI:") for name in schemas):
            raise ValueError("Source already contains PhysX mimic; refusing duplicate constraint")
        # Pinned ovstage population did not enforce the original Newton schema.
        # This equivalent authoring was verified with passive follower drives in
        # a separate CPU-native fixture. Do not claim parity for a new seed yet.
        follower.RemoveAppliedSchema("NewtonMimicAPI")
        follower.AddAppliedSchema("PhysxMimicJointAPI:rotX")
        prefix = "physxMimicJoint:rotX:"
        for name, value in (
            ("gearing", -entry["mimicCoef1"]),
            ("offset", -entry["mimicCoef0"]),
            ("naturalFrequency", 0.0),
            ("dampingRatio", 0.0),
        ):
            follower.CreateAttribute(prefix + name, Sdf.ValueTypeNames.Float, custom=False).Set(
                value
            )
        follower.CreateAttribute(
            prefix + "referenceJointAxis", Sdf.ValueTypeNames.Token, custom=False
        ).Set("rotX")
        follower.CreateRelationship(prefix + "referenceJoint", custom=False).SetTargets(
            [entry["leader"]]
        )
        mimic_edits.append(
            dict(
                follower=entry["follower"],
                leader=entry["leader"],
                gearing=-entry["mimicCoef1"],
                offset=-entry["mimicCoef0"],
                source_equation="follower=coef0+coef1*leader",
                derived_equation="follower+gearing*leader+offset=0",
            )
        )
    layer.Save()
    reloaded = Usd.Stage.Open(str(overlay))
    before, after = UsdGeom.XformCache(), UsdGeom.XformCache()
    count = 0
    for prim in source.Traverse():
        if prim.IsA(UsdGeom.Xformable):
            if before.GetLocalToWorldTransform(prim) != after.GetLocalToWorldTransform(
                reloaded.GetPrimAtPath(prim.GetPath())
            ):
                raise RuntimeError(f"Overlay changed initial world transform: {prim.GetPath()}")
            count += 1
    roots = [
        str(p.GetPath()) for p in reloaded.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)
    ]
    expected = [entry["new_root"] for entry in edits]
    current_hash = _sha(snapshot)
    if sorted(roots) != sorted(expected) or current_hash != source_hash:
        details = {}
        for path in sorted(set(roots + expected + [entry["old_root"] for entry in edits])):
            prim = reloaded.GetPrimAtPath(path)
            raw = prim.GetMetadata("apiSchemas")
            details[path] = dict(
                raw_tokens=[] if raw is None else list(raw.GetAppliedItems()),
                applied_schemas=list(prim.GetAppliedSchemas()),
            )
        raise RuntimeError(
            f"Derived root inventory or original snapshot changed: roots={roots}, "
            f"expected={expected}, source_before={source_hash}, "
            f"source_after={current_hash}, schemas={details}"
        )
    return overlay, dict(
        edits=edits,
        articulation_roots=expected,
        initial_world_transforms_unchanged=count,
        source_sha256=source_hash,
        mimic_translation=mimic_edits,
        mimic_native_runtime_verified=False,
    )


def _mimics(stage, joint_paths) -> list[dict]:
    result = []
    for paths in joint_paths:
        for path in paths:
            prim = stage.GetPrimAtPath(path)
            schemas = prim.GetMetadata("apiSchemas")
            if schemas is None or "NewtonMimicAPI" not in schemas.GetAppliedItems():
                continue
            leader = [str(p) for p in prim.GetRelationship("newton:mimicJoint").GetTargets()]
            if len(leader) != 1 or leader[0] not in paths or leader[0] == path:
                raise ValueError(f"Invalid Newton mimic leader: {path}")
            entry = dict(follower=path, leader=leader[0])
            for name, default in (("mimicCoef0", 0.0), ("mimicCoef1", 1.0), ("mimicEnabled", True)):
                value = prim.GetAttribute(f"newton:{name}").Get()
                entry[name] = default if value is None else value
            if not all(np.isfinite(entry[n]) for n in ("mimicCoef0", "mimicCoef1")):
                raise ValueError("Nonfinite mimic coefficient")
            result.append(entry)
    if len(result) != 4 or any(not entry["mimicEnabled"] for entry in result):
        raise ValueError("Expected four enabled native Newton mimic followers")
    return result


def build_seed(env, snapshot: Path, output: Path) -> dict:
    """Read one native boundary and write seed.json plus a reversible USD overlay.

    No app.update, physics step, state writes or SDK mutations. Returns the exact
    JSON seed written to output/seed.json. output may already contain receipts.
    """
    from pxr import Usd, UsdPhysics

    snapshot, output = Path(snapshot).resolve(strict=True), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    seed_path = output / "seed.json"
    if seed_path.exists():
        raise FileExistsError(seed_path)
    step_before = env.sim.get_physics_step_count()
    stage = Usd.Stage.Open(str(snapshot))
    if not stage:
        raise ValueError("Cannot open current exported snapshot")
    views = [robot.root_view for robot in env.robots]
    if len(views) != 2:
        raise ValueError("Require exactly two current native robots")
    body_paths, dof_paths, joint_orders, body_orders = [], [], [], []
    for view in views:
        meta = view.shared_metatype
        metadata = dict(
            fixed_base=bool(meta.fixed_base),
            dof_names=list(meta.dof_names),
            link_names=list(meta.link_names),
            count=int(view.count) if hasattr(view, "count") else None,
        )
        # Kit may expose a floating articulation anchored by an external world
        # weld. The derived overlay relocates the root onto THAT existing weld;
        # _fixed_base_overlay validates both exact body relationships below.
        if len(meta.dof_names) != 9 or len(meta.link_names) != 12:
            raise ValueError(f"Unexpected native Piper topology: {metadata}")
        if tuple(meta.dof_names) != DOFS or tuple(meta.link_names) != BODIES:
            raise ValueError(
                f"Unexpected native Piper names/order; requalification required: {metadata}"
            )
        joints = [list(meta.dof_names).index(name) for name in DOFS]
        bodies = [list(meta.link_names).index(name) for name in BODIES]
        joint_orders.append(joints)
        body_orders.append(bodies)
        dof_paths.append([str(view.dof_paths[0][i]) for i in joints])
        body_paths.extend(str(view.link_paths[0][i]) for i in bodies)

    def joints(getter, width=None):
        shape = (1, 9) if width is None else (1, 9, width)
        return np.stack(
            [
                _array(getattr(v, getter)(), shape)[0, ids]
                for v, ids in zip(views, joint_orders, strict=True)
            ]
        )

    properties = {
        name: joints(getter, 2 if name == "limits" else None)
        for name, getter in (
            ("stiffness", "get_dof_stiffnesses"),
            ("damping", "get_dof_dampings"),
            ("max_force", "get_dof_max_forces"),
            ("max_velocity", "get_dof_max_velocities"),
            ("limits", "get_dof_limits"),
        )
    }
    dynamic = [*env.vr_runtime.dynamic_assets, env.physics_probe]
    if len(dynamic) != 3:
        raise ValueError("Require two cubes and ValidationProbe")
    dynamic_paths = [str(asset.cfg.prim_path) for asset in dynamic]
    dynamic_pose = np.stack([_array(a.root_view.get_transforms(), (1, 7))[0] for a in dynamic])
    dynamic_velocity = np.stack([_array(a.root_view.get_velocities(), (1, 6))[0] for a in dynamic])
    body_paths.extend(dynamic_paths)
    inventory = {str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)}
    if len(body_paths) != 27 or len(set(body_paths)) != 27 or set(body_paths) != inventory:
        raise ValueError(
            f"Dynamic body coverage differs: missing={inventory - set(body_paths)}, extra={set(body_paths) - inventory}"
        )
    link_pose = np.stack(
        [
            _array(v.get_link_transforms(), (1, 12, 7))[0, ids]
            for v, ids in zip(views, body_orders, strict=True)
        ]
    )
    initial = dict(
        q=joints("get_dof_positions"),
        dq=joints("get_dof_velocities"),
        position_target=joints("get_dof_position_targets"),
        velocity_target=joints("get_dof_velocity_targets"),
        external_effort=joints("get_dof_actuation_forces"),
        root_pose=np.stack([_array(v.get_root_transforms(), (1, 7))[0] for v in views]),
        dynamic_body_pose=dynamic_pose,
        dynamic_body_velocity=dynamic_velocity,
        rigid_body_world_pose=np.concatenate([link_pose.reshape(24, 7), dynamic_pose]),
        link_pose=link_pose,
    )
    mimics = _mimics(stage, dof_paths)
    for entry in mimics:
        arm = next(i for i, paths in enumerate(dof_paths) if entry["follower"] in paths)
        index = dof_paths[arm].index(entry["follower"])
        entry["native_follower_stiffness"] = float(properties["stiffness"][arm, index])
        entry["native_follower_damping"] = float(properties["damping"][arm, index])
        if entry["native_follower_stiffness"] != 0 or entry["native_follower_damping"] != 0:
            raise ValueError("Selected canonical mimic followers must remain passive")
    drive_type = joints("get_drive_types").astype(np.uint8)
    if not np.isin(drive_type, [0, 1, 2]).all():
        raise ValueError("Unknown native drive type")
    if env.sim.get_physics_step_count() != step_before:
        raise RuntimeError("Native state changed during seed capture")
    overlay, adaptation = _fixed_base_overlay(snapshot, output, mimics)
    seed = dict(
        schema="standalone_cpu_physx_seed_v1",
        profile="standalone_cpu_physx_diagnostic_v1",
        stage_overlay=str(overlay),
        source_snapshot=str(snapshot),
        files=[dict(path=str(p), sha256=_sha(p)) for p in (snapshot, overlay)],
        articulation_roots=adaptation["articulation_roots"],
        rigid_body_paths=body_paths,
        dynamic_body_paths=dynamic_paths,
        dof_names=list(DOFS),
        body_names=list(BODIES),
        dof_properties={k: v.tolist() for k, v in properties.items()},
        drive_type=drive_type.tolist(),
        initial={k: v.tolist() for k, v in initial.items()},
        mimic_config=mimics,
        adaptation=adaptation,
        native_capture_physics_step=int(step_before),
        native_fixed_base=[bool(v.shared_metatype.fixed_base) for v in views],
        quaternion_order="xyzw",
        physics_dt_s=1 / 120,
        substeps_per_control=4,
        physical=False,
        dataset_admissible=False,
        canonical_physics_parity_verified=False,
    )
    with seed_path.open("x") as stream:
        json.dump(seed, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return seed
