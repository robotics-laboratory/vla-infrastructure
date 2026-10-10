"""Diagnostic PhysX publication -> same-render-result geometry comparison.

Uses native semantic transforms and camera matrices, never a fixed frame offset.
The semantic stamp identifies its own publication; matching every render-relevant
native body checks whether physics geometry accompanied it. Optional optical
corroboration is recorded per result; dataset admission remains false.
"""
from collections import OrderedDict
from contextlib import nullcontext
import inspect
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import time

import numpy as np

from isaac_s1_runtime import jsonable, pose_xyzw_to_matrix


def semantic_matrix(result, path):
    geometry = result["result_geometry"]
    indices = [i for i, row in enumerate(geometry["semantic_token_rows"]) if path in row]
    if len(indices) != 1:
        raise ValueError(f"Expected one semantic row for {path}, got {indices}")
    matrix = np.asarray(geometry["semantic_world_matrices"][indices[0]], dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError(f"Invalid semantic matrix for {path}")
    return matrix


def stamp_matrix(publication_id):
    if type(publication_id) is not int or not 1 <= publication_id < 65536:
        raise ValueError("Diagnostic stamp needs publication ID 1..65535")
    matrix = np.diag([1.0 + publication_id / 65536.0, 1.5, 2.0, 1.0])
    matrix[3, :3] = (-1.137, -1.931, -0.1)
    return matrix


def decode_stamp(matrix):
    value = (float(matrix[0, 0]) - 1.0) * 65536.0
    if not np.isfinite(value) or abs(value - round(value)) > 0.125:
        raise ValueError("Nonintegral rendered publication stamp")
    publication_id = int(round(value))
    if not 1 <= publication_id < 65536:
        raise ValueError("Rendered publication stamp is outside diagnostic range")
    return publication_id


def compare_geometry(result, source, stamp_path, camera_path, tolerance):
    """Compare actual result geometry with one explicitly identified publication."""
    scope = source.get("proof_scope", "full_native_body_camera")
    if scope not in ("full_native_body_camera", "publication_clock_camera", "publication_attribute_camera"):
        raise ValueError("Unknown source proof scope")
    body_checked = scope == "full_native_body_camera"
    if bool(source["body_matrices"]) != body_checked:
        raise ValueError("Body comparison inventory disagrees with source proof scope")
    failures, errors = [], {}
    expected = dict(source["body_matrices"])
    if scope == "publication_attribute_camera":
        attribute_id = result.get("attribute_publication_id")
        if type(attribute_id) is not int or attribute_id < 1 or attribute_id != source["publication_id"]:
            failures.append("Native attribute publication ID differs from retained source")
    else:
        expected[stamp_path] = stamp_matrix(source["publication_id"])
    for path, matrix in expected.items():
        try:
            error = float(np.max(np.abs(semantic_matrix(result, path) - matrix)))
            errors[path] = error
            if error > tolerance:
                failures.append(path)
        except ValueError as exc:
            failures.append(str(exc))
    view = np.asarray(result["result_geometry"]["camera_view"], dtype=np.float64)
    if view.shape != (4, 4) or not np.isfinite(view).all():
        raise ValueError("Invalid rendered camera view")
    camera_error = float(np.max(np.abs(np.linalg.inv(view) - source["camera_matrices"][camera_path])))
    if camera_error > tolerance:
        failures.append(camera_path)
    return dict(geometry_matched=not failures, failed_paths=failures,
                proof_scope=scope, body_geometry_checked=body_checked,
                body_matrix_max_error=max(errors.values(), default=0.0),
                camera_matrix_max_error=camera_error, compared_bodies=len(source["body_matrices"]))


def _host(value):
    value = value.torch if hasattr(value, "torch") else value
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    elif hasattr(value, "numpy"):
        value = value.numpy()
    return np.array(value, copy=True)


def _host_batch(values):
    """Own identical native arrays with one packed host copy; physics must be held.

    Warp's public DLPack exporter hands off its current stream to Torch. Keep
    the blocking host copy on the default stream, as Warp.numpy() does. No
    backend stream pointers or global CUDA synchronization are introduced.
    """
    import torch
    tensors = []
    for value in values:
        value = value.torch if hasattr(value, "torch") else value
        if not isinstance(value, torch.Tensor):
            if not hasattr(value, "__dlpack__"):
                raise TypeError("Batched native reads require Torch or DLPack arrays")
            value = torch.from_dlpack(value)
        tensors.append(value.detach())
    if not tensors:
        raise ValueError("Batched native reads require at least one array")
    first = tensors[0]
    if first.dtype != torch.float32 or any(t.dtype != first.dtype or t.device != first.device for t in tensors):
        raise ValueError("Batched native reads require homogeneous float32 arrays on one device")
    scope = nullcontext()
    if first.is_cuda:
        stream = torch.cuda.default_stream(first.device)
        stream.wait_stream(torch.cuda.current_stream(first.device))
        scope = torch.cuda.stream(stream)
    with scope:
        packed = torch.cat([t.reshape(-1) for t in tensors]).cpu().numpy()
    arrays, offset = [], 0
    for tensor in tensors:
        end = offset + tensor.numel()
        arrays.append(np.array(packed[offset:end].reshape(tuple(tensor.shape)), copy=True))
        offset = end
    return arrays


def publication_log(source, compact=False):
    """Compact only the persisted diagnostics; source/history remain unchanged."""
    if not compact:
        return dict(kind="publication", **source)
    digest = hashlib.sha256()
    arrays = [(key, source[key]) for key in ("native_body_pose_xyzw", "q", "dq") if key in source]
    arrays += [(f"camera:{path}", matrix) for path, matrix in sorted(source.get("camera_matrices", {}).items())]
    for name, value in arrays:
        array = np.ascontiguousarray(value)
        header = json.dumps([name, array.dtype.str, array.shape], separators=(",", ":")).encode()
        digest.update(len(header).to_bytes(4, "little"))
        digest.update(header)
        digest.update(array.tobytes())
    return dict(kind="publication", **{key: source[key] for key in
                ("publication_id", "physics_step", "reset_epoch", "published_ns")},
                source_state_sha256=digest.hexdigest() if arrays else None,
                source_state_hash_schema=(("diagnostic_native_pose_camera_arrays_v1" if arrays else
                                           "publication_identity_only_no_pose_arrays_v1") if source.get("proof_scope")
                                          == "publication_attribute" else "named_native_pose_camera_arrays_v1" if source.get("proof_scope")
                                          in ("publication_clock_camera", "publication_attribute_camera") else "named_native_pose_q_dq_camera_arrays_v1"),
                proof_scope=source.get("proof_scope", "full_native_body_camera"),
                body_geometry_checked=bool(source["body_matrices"]),
                compared_body_count=len(source["body_matrices"]),
                camera_paths=sorted(source.get("camera_matrices", {})), compact_logging=True)


class OpticalPublication:
    """Diagnostic meshes published with native poses before the ordinary Kit update."""
    kinds = ("background", "marker", *(f"cell{i}" for i in range(16)))

    def __init__(self, stage, camera_paths, products):
        from pxr import UsdGeom
        if stage.GetPrimAtPath("/LiveTemporalMesh") or stage.GetPrimAtPath("/LiveTemporalMaterials"):
            raise ValueError("Optical proof requires exclusive diagnostic mesh paths")
        self.camera_paths, self.roles = dict(camera_paths), tuple(camera_paths)
        path = (Path(__file__).resolve().parents[1]
                / "docs/experiments/20261009_live_camera_recording_30hz/temporal_physics/mesh_freshness.py")
        spec = importlib.util.spec_from_file_location("native_source_optical_mesh", path)
        self.marker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.marker)
        self.marker.inject(stage, list(camera_paths.values()), products=list(products))
        self.intrinsics, self.previous_decoded = [], {}
        for path in camera_paths.values():
            camera = UsdGeom.Camera(stage.GetPrimAtPath(path))
            self.intrinsics.append([camera.GetFocalLengthAttr().Get(),
                                    camera.GetHorizontalApertureAttr().Get(),
                                    camera.GetVerticalApertureAttr().Get()])

    def publish(self, hierarchy, publication_id, camera_matrices):
        from usdrt import Gf, Sdf
        if not 0 < publication_id < 4096:
            raise ValueError("Optical publication ID exceeds twelve-bit diagnostic limit")
        for role, path in enumerate(self.camera_paths.values()):
            for kind in self.kinds:
                world = self.marker.local_matrix(kind, role, self.intrinsics[role], publication_id)
                world = world @ camera_matrices[path]
                hierarchy.set_world_xform(Sdf.Path(f"/LiveTemporalMesh/Role{role}/{kind}"),
                                          Gf.Matrix4d(*world.reshape(-1).tolist()))

    def observe(self, result, geometry_row):
        role, publication = result["role"], geometry_row.get("publication_id")
        known = isinstance(publication, int) and 0 < publication < 4096
        row = self.marker.decode(_host(result["rgba"]), publication if known else 0,
                                 self.roles.index(role), previous_source=self.previous_decoded.get(role))
        if row["confident"] and row["decoded_role"] == self.roles.index(role):
            self.previous_decoded[role] = row["decoded_source"]
        row["geometry_matched"] = bool(geometry_row.get("geometry_matched"))
        row["optical_and_source_matched"] = bool(known and row["passed"]
                                                and geometry_row.get("history_join_matched", False))
        row["optical_and_geometry_matched"] = bool(known and row["passed"] and row["geometry_matched"])
        row["dataset_admissible"] = False
        return row


def prepare_source_proof_stage(sim, *, clock_only=False, attribute_probe=False, attribute_only=False, identity_only=False):
    """Author semantics before the FIRST canonical reset creates tensor views.

    Caller owns the returned layer until native physics shutdown. Removing API
    opinions while views are alive can invalidate their physical descendants.
    """
    attribute_only = bool(attribute_only or identity_only)
    clock_only, attribute_probe = bool(clock_only or attribute_only), bool(attribute_probe or attribute_only)
    if sim.physics_sim_view is not None:
        raise RuntimeError("Source-proof stage preparation requires no existing physics view")
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics
    from isaacsim.core.experimental.utils.semantics import add_labels
    stage = sim.stage
    stamp_path = "/World/NativeSourceProofStamp"
    if stage.GetPrimAtPath(stamp_path):
        raise ValueError("Source-proof stamp path already exists")
    bodies = [str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)]
    if not bodies:
        raise ValueError("Source-proof stage preparation requires the authored native bodies")
    layer = Sdf.Layer.CreateAnonymous("native-source-proof")
    layer.customLayerData = {"native_source_proof_pre_physics": True, "clock_only": bool(clock_only),
                            "attribute_probe": bool(attribute_probe), "attribute_only": bool(attribute_only),
                            "identity_only": bool(identity_only)}
    stage.GetSessionLayer().subLayerPaths.insert(0, layer.identifier)
    try:
        with Usd.EditContext(stage, layer):
            stamp = UsdGeom.Cube.Define(stage, stamp_path)
            stamp.CreateSizeAttr(0.001)
            stamp.AddTransformOp().Set(Gf.Matrix4d(1))
            if attribute_probe:
                stamp.GetPrim().CreateAttribute("vla:publicationId", Sdf.ValueTypeNames.Int, custom=True).Set(0)
            for path in (() if attribute_only else ((stamp_path,) if clock_only else (*bodies, stamp_path))):
                add_labels(stage.GetPrimAtPath(path), labels="native_source_proof", taxonomy="class")
    except BaseException:
        session = stage.GetSessionLayer()
        session.subLayerPaths = [p for p in session.subLayerPaths if p != layer.identifier]
        raise
    return layer


class NativeSourceProof:
    """Optional main-thread diagnostic; existing physics/render pumps stay owned by Kit."""
    def __init__(self, env, output, *, capacity=256, tolerance=5e-5, optical=False,
                 render_products=None, prepared_layer=None, compact_logging=False, batch_reads=False,
                 skip_redundant_sync=False, clock_only=False, attribute_probe=False, attribute_only=False, identity_only=False):
        from pxr import Usd, UsdGeom, UsdPhysics
        import omni.usd
        from usdrt import Usd as RtUsd, hierarchy

        if capacity < 2 or not np.isfinite(tolerance) or tolerance <= 0:
            raise ValueError("Invalid source-proof capacity/tolerance")
        if optical and (render_products is None or len(render_products) != 3):
            raise ValueError("Optical proof requires three existing render-product paths")
        if prepared_layer is None:
            raise ValueError("Source proof requires a layer prepared before the first canonical physics reset")
        self.env, self.stage = env, env.sim.stage
        self.capacity, self.tolerance = capacity, tolerance
        self.thread, self.closed, self.error = threading.get_ident(), False, None
        self.history, self.counts = OrderedDict(), dict(publications=0, matched=0, mismatched=0,
                                                       unresolved=0, evicted_unmatched=0)
        self.geometry_samples = 0
        self.compact_logging = bool(compact_logging)
        self.batch_reads = bool(batch_reads)
        self.skip_redundant_sync = bool(skip_redundant_sync)
        self.identity_only = bool(identity_only)
        attribute_only = bool(attribute_only or identity_only)
        self.attribute_only = attribute_only
        self.clock_only = bool(clock_only or attribute_only)
        self.proof_scope = ("publication_attribute" if identity_only else
                            "publication_attribute_camera" if attribute_only else
                            "publication_clock_camera" if self.clock_only else "full_native_body_camera")
        self.attribute_probe = bool(attribute_probe or attribute_only)
        self.attribute_clock = self.attribute_prim = None
        self.attribute_tag_owned = False
        self.attribute_last_written = 0
        self.layer = self.previous_forward = self.replacement = None
        self.prepared_layer = prepared_layer
        self.stream = None
        self.optical = None
        self.counts.update(optical_matched=0, optical_failed=0)
        self.counts.update(attribute_clock_matched=0, attribute_clock_failed=0)
        self.manager = env.sim.physics_manager
        self.physics_view = env.sim.physics_sim_view
        self.stamp_path = "/World/NativeSourceProofStamp"
        self.camera_paths = dict(env.camera.camera_prim_paths)
        self.views = [r.root_view for r in env.robots]
        self.props = [*env.vr_runtime.dynamic_assets, env.physics_probe]
        self.robot_body_paths = [str(p) for view in self.views for p in view.link_paths[0]]
        self.body_paths = list(self.robot_body_paths)
        self.body_paths += [str(asset.cfg.prim_path) for asset in self.props]
        inventory = {str(p.GetPath()) for p in self.stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)}
        if set(self.body_paths) != inventory or len(set(self.body_paths)) != len(self.body_paths):
            raise ValueError("Native source proof does not cover the rigid-body inventory")
        if UsdGeom.GetStageMetersPerUnit(self.stage) != 1.0:
            raise ValueError("Source proof currently requires meter stage units")
        # Bodies without visible geometry have no semantic render instance to validate.
        render_bodies = set()
        for prim in self.stage.Traverse(Usd.TraverseInstanceProxies()):
            if prim.IsA(UsdGeom.Gprim) and UsdGeom.Imageable(prim).ComputeVisibility() != UsdGeom.Tokens.invisible:
                parent = prim
                while parent and str(parent.GetPath()) != "/":
                    if str(parent.GetPath()) in inventory:
                        render_bodies.add(str(parent.GetPath()))
                        break
                    parent = parent.GetParent()
        self.render_body_paths = tuple(p for p in self.body_paths if p in render_bodies)
        if not self.render_body_paths:
            raise ValueError("No render-relevant native bodies")
        self.camera_mounts = {}
        cache = UsdGeom.XformCache()
        # PhysX link poses describe rigid motion, not authored scale/shear.
        # Reject unsupported body transforms instead of silently comparing a
        # scale-free native pose with differently scaled rendered geometry.
        for path in self.body_paths:
            basis = np.asarray(cache.GetLocalToWorldTransform(self.stage.GetPrimAtPath(path)))[:3, :3]
            if (not np.allclose(basis @ basis.T, np.eye(3), atol=1e-6, rtol=0)
                    or not np.isclose(np.linalg.det(basis), 1.0, atol=1e-6, rtol=0)):
                raise ValueError(f"Unsupported authored body world scale/shear: {path}")
        for path in self.camera_paths.values():
            camera = self.stage.GetPrimAtPath(path)
            parent = camera.GetParent()
            while parent and str(parent.GetPath()) not in inventory and str(parent.GetPath()) != "/":
                parent = parent.GetParent()
            body = str(parent.GetPath()) if parent and str(parent.GetPath()) in inventory else None
            if body:
                local, resets = cache.ComputeRelativeTransform(camera, parent)
                if resets:
                    raise ValueError(f"Camera mount resets its native body transform: {path}")
            else:
                local = cache.GetLocalToWorldTransform(camera)
            self.camera_mounts[path] = (body, np.array(local, dtype=np.float64, copy=True))
            if self.clock_only and body is not None and body not in self.robot_body_paths:
                raise ValueError("Clock-only camera must mount to an inventoried native robot link")
        folder = Path(output) / "source_proof"
        folder.mkdir(parents=True, exist_ok=False)
        self.output = folder
        try:
            self.stream = (folder / "events.jsonl").open("x", buffering=1)
            if (not prepared_layer.customLayerData.get("native_source_proof_pre_physics")
                    or bool(prepared_layer.customLayerData.get("clock_only", False)) != self.clock_only
                    or bool(prepared_layer.customLayerData.get("attribute_probe", False)) != self.attribute_probe
                    or bool(prepared_layer.customLayerData.get("attribute_only", False)) != self.attribute_only
                    or bool(prepared_layer.customLayerData.get("identity_only", False)) != self.identity_only
                    or prepared_layer.identifier not in self.stage.GetSessionLayer().subLayerPaths
                    or any(prepared_layer.GetPrimAtPath(path) is None
                           for path in ((self.stamp_path,) if self.clock_only
                                        else (*self.body_paths, self.stamp_path)))):
                raise ValueError("Missing pre-physics source-proof layer/body opinions")
            self.layer = prepared_layer
            self._check_native_view("before_optical_geometry")
            with Usd.EditContext(self.stage, self.layer):
                if optical:
                    self.optical = OpticalPublication(self.stage, self.camera_paths, render_products)
            self._check_native_view("after_optical_geometry")
            self.rt = RtUsd.Stage.Attach(omni.usd.get_context().get_stage_id())
            self._sync_to_fabric()  # Setup authoring must be populated in both modes.
            if self.attribute_probe:
                from usdrt import Sdf
                self.attribute_prim = self.rt.GetPrimAtPath(self.stamp_path)
                self.attribute_clock = self.attribute_prim.GetAttribute("vla:publicationId")
                if not self.attribute_clock.IsValid() or self.attribute_clock.Get() != 0:
                    raise ValueError("Missing initialized owned publication attribute")
                if not self.attribute_prim.GetAttribute("fc_exportToRingbuffer").IsValid():
                    self.attribute_prim.CreateAttribute("fc_exportToRingbuffer", Sdf.ValueTypeNames.Tag, True)
                    self.attribute_tag_owned = True
            self._check_native_view("after_initial_population_sync")
            self.hierarchy = hierarchy.IFabricHierarchy().get_fabric_hierarchy(
                self.rt.GetFabricId(), self.rt.GetStageIdAsStageId())
            self._install()
            self._write(dict(kind="setup", body_paths=self.body_paths,
                             render_body_paths=self.render_body_paths,
                             bodies_without_visible_geometry=sorted(inventory - render_bodies),
                             camera_paths=self.camera_paths, tolerance=tolerance, capacity=capacity,
                             proof_scope=self.proof_scope, body_geometry_checked=not self.clock_only,
                             attribute_probe=self.attribute_probe, attribute_only=self.attribute_only,
                             identity_only=self.identity_only, camera_geometry_checked=not self.identity_only,
                             compared_bodies=0 if self.clock_only else len(self.render_body_paths),
                             sampled_native_pose_paths=([] if self.identity_only and not optical else
                                                       self.robot_body_paths if self.clock_only else self.body_paths),
                             skip_redundant_sync=self.skip_redundant_sync,
                             optical_enabled=optical, optical_mesh_count=54 if optical else 0))
            self.manager.forward()  # Initial held-state publication, without a Kit/physics step.
        except BaseException:
            self.close()
            raise

    def _write(self, row):
        self.stream.write(json.dumps(jsonable(row), allow_nan=False) + "\n")

    def _check_native_view(self, phase):
        valid = self.env.sim.physics_sim_view is self.physics_view and self.physics_view.is_valid
        if not valid:
            self._write(dict(kind="physics_view_invalid", phase=phase))
            raise RuntimeError(f"Original native physics view invalidated at {phase}")

    def _sync_to_fabric(self):
        """Public population call, exposed separately for host-only profiling."""
        self.rt.SynchronizeToFabric()

    def _install(self):
        original = self.manager.forward
        def describe(value):
            cls = type(value)
            row = dict(type=f"{cls.__module__}.{cls.__qualname__}",
                       module=getattr(value, "__module__", None),
                       qualname=getattr(value, "__qualname__", None))
            try:
                row["source_file"] = inspect.getfile(value)
            except (TypeError, OSError) as exc:
                row["source_file_unavailable"] = str(exc)
            return row
        metadata = dict(manager=describe(self.manager), forward=describe(original),
                        forward_owner=describe(getattr(original, "__self__", None)),
                        simulation=describe(type(self.env.sim)),
                        manager_is_class=isinstance(self.manager, type))
        if isinstance(self.manager, str):
            # ResolvableString forwards reads but cannot own a patched attribute.
            # Use the same public resolver as its installed _resolve implementation.
            from isaaclab.utils.string import string_to_callable
            resolved = string_to_callable(str(self.manager))
            if not isinstance(resolved, type) or resolved.forward != original:
                raise TypeError("Resolved physics manager does not own the observed forward method")
            self.manager = resolved
            metadata["resolved_manager"] = describe(resolved)
        try:
            namespace = vars(self.manager)
            metadata["own_forward"] = describe(namespace.get("forward"))
        except TypeError as exc:
            namespace = None
            metadata["namespace_unavailable"] = str(exc)
        (self.output / "manager-type.json").write_text(json.dumps(metadata, indent=2) + "\n")
        if namespace is None:
            raise TypeError("Native manager has no Python namespace; inspect source_proof/manager-type.json")
        if not callable(original):
            raise TypeError("Expected callable native physics manager forward")
        self.forward_was_owned = "forward" in namespace
        self.previous_forward = namespace.get("forward")

        def forward():
            try:
                self._guard()
                step = self.env.sim.get_physics_step_count()
                # Opt-in ablation: after setup we only author Fabric transforms.
                # Kit still populates pending USD changes before native rendering.
                if not self.skip_redundant_sync:
                    self._sync_to_fabric()
                original()  # Kinematics + native PhysX Fabric force_update; no physics/app pump.
                self._check_native_view("after_native_forward")
                self._publish(step)
                if self.env.sim.get_physics_step_count() != step:
                    raise RuntimeError("Source boundary changed during native publication")
            except Exception as exc:
                self.error = exc
                raise

        # Preserve the resolved callable, including an inherited classmethod or
        # an existing observer wrapper. A staticmethod avoids adding a new cls
        # argument; instance attributes likewise do not bind an extra self.
        self.replacement = staticmethod(forward) if isinstance(self.manager, type) else forward
        setattr(self.manager, "forward", self.replacement)

    def _guard(self):
        if self.closed or threading.get_ident() != self.thread:
            raise RuntimeError("Source proof requires its live Kit owner thread")
        self.raise_if_failed()

    def _publish(self, step):
        from usdrt import Gf, Sdf
        from pxr import UsdGeom
        publication_id = self.counts["publications"] + 1
        if not self.attribute_only:
            matrix = stamp_matrix(publication_id)
            self.hierarchy.set_world_xform(Sdf.Path(self.stamp_path), Gf.Matrix4d(*matrix.reshape(-1).tolist()))
        if self.attribute_probe:
            if not self.attribute_clock.Set(publication_id):
                raise RuntimeError("Failed to write owned Fabric publication attribute")
            self.attribute_last_written = publication_id
        if self.identity_only and self.optical is None:
            self._retain_publication(dict(publication_id=publication_id, physics_step=int(step),
                                         reset_epoch=int(self.env.camera.reset_epoch),
                                         published_ns=time.monotonic_ns(), proof_scope=self.proof_scope,
                                         body_geometry_checked=False, camera_geometry_checked=False,
                                         body_matrices={}))
            return
        pose_paths = self.robot_body_paths if self.clock_only else self.body_paths
        if self.clock_only:
            native = [v.get_link_transforms() for v in self.views]
            poses = np.concatenate([a.reshape(-1, 7) for a in
                                    (_host_batch(native) if self.batch_reads else [_host(v) for v in native])])
        elif self.batch_reads:
            arrays = _host_batch([v.get_link_transforms() for v in self.views]
                                 + [p.root_view.get_transforms() for p in self.props]
                                 + [v.get_dof_positions() for v in self.views]
                                 + [v.get_dof_velocities() for v in self.views])
            pose_count, robot_count = len(self.views) + len(self.props), len(self.views)
            poses = np.concatenate([array.reshape(-1, 7) for array in arrays[:pose_count]])
            q, dq = arrays[pose_count:pose_count + robot_count], arrays[pose_count + robot_count:]
        else:
            poses = np.concatenate([_host(v.get_link_transforms()).reshape(-1, 7) for v in self.views]
                                   + [_host(p.root_view.get_transforms()).reshape(-1, 7) for p in self.props])
        if len(poses) != len(pose_paths):
            raise RuntimeError("Native body pose inventory changed")
        # Native pose matrices are column-vector; renderer/USD uses row-vector convention.
        mounted_bodies = {body for body, _ in self.camera_mounts.values() if body is not None}
        native_matrices = {p: pose_xyzw_to_matrix(pose).T
                           for p, pose in zip(pose_paths, poses, strict=True)
                           if not self.clock_only or p in mounted_bodies}
        body_matrices = {} if self.clock_only else {p: native_matrices[p] for p in self.render_body_paths}
        cameras, cache = {}, UsdGeom.XformCache()
        for path, (body, local) in self.camera_mounts.items():
            prim = self.stage.GetPrimAtPath(path)
            current = (cache.ComputeRelativeTransform(prim, self.stage.GetPrimAtPath(body))[0]
                       if body else cache.GetLocalToWorldTransform(prim))
            if not np.allclose(np.asarray(current), local, atol=1e-10, rtol=0):
                raise RuntimeError(f"Declared camera mount changed during source proof: {path}")
            cameras[path] = local @ native_matrices[body] if body else local.copy()
        if self.optical is not None:
            self.optical.publish(self.hierarchy, publication_id, cameras)
        self.hierarchy.update_world_xforms()
        source = dict(publication_id=publication_id, physics_step=int(step),
                      proof_scope=self.proof_scope, body_geometry_checked=not self.clock_only,
                      camera_geometry_checked=not self.identity_only,
                      reset_epoch=int(self.env.camera.reset_epoch), published_ns=time.monotonic_ns(),
                      body_matrices=body_matrices, camera_matrices=cameras,
                      native_body_pose_xyzw=poses)
        if not self.clock_only:
            source.update(q=q if self.batch_reads else [_host(v.get_dof_positions()) for v in self.views],
                          dq=dq if self.batch_reads else [_host(v.get_dof_velocities()) for v in self.views])
        self._retain_publication(source)

    def _retain_publication(self, source):
        publication_id = source["publication_id"]
        if len(self.history) >= self.capacity:
            key, previous = self.history.popitem(last=False)
            missing = sorted(set(self.camera_paths) - previous["observed_roles"])
            self.counts["evicted_unmatched"] += bool(missing)
            self._write(dict(kind="eviction", publication_id=key, missing_roles=missing))
        self.history[publication_id] = dict(source=source, observed_roles=set())
        self.counts["publications"] = publication_id
        self._write(publication_log(source, self.compact_logging))

    def observe(self, result):
        self._guard()
        if self.geometry_samples < (3 if self.compact_logging else 256):
            self._write(dict(kind="result_geometry_sample", role=result["role"],
                             frame_identifier=result["frame_identifier"],
                             result_geometry=result.get("result_geometry", {})))
            self.geometry_samples += 1
        role = result["role"]
        if role not in self.camera_paths:
            raise ValueError(f"Unknown source-proof role: {role}")
        row = dict(kind="render_result", role=role, frame_identifier=result["frame_identifier"],
                   proof_scope=self.proof_scope, body_geometry_checked=False,
                   camera_geometry_checked=not self.identity_only, history_join_matched=False,
                   optical_alignment_proven=False, dataset_admissible=False)
        try:
            if self.attribute_only:
                publication_id = result.get("attribute_publication_id")
                if type(publication_id) is not int or publication_id < 1:
                    raise ValueError("Invalid native attribute publication ID")
            else:
                publication_id = decode_stamp(semantic_matrix(result, self.stamp_path))
            row["publication_id"] = publication_id
            entry = self.history.get(publication_id)
            if entry is None:
                raise ValueError("Rendered stamp is not in retained publication history")
            source = entry["source"]
            if source.get("proof_scope", "full_native_body_camera") != self.proof_scope:
                raise ValueError("Retained publication proof scope differs from observer")
            row.update(physics_step=source["physics_step"], reset_epoch=source["reset_epoch"])
            row["history_join_matched"] = True
            if self.identity_only:
                row.update(geometry_matched=False, failed_paths=[], compared_bodies=0,
                           camera_geometry_checked=False)
            else:
                row.update(compare_geometry(result, source, self.stamp_path, self.camera_paths[role], self.tolerance))
            if self.attribute_probe:
                attribute_id = result.get("attribute_publication_id")
                matched = type(attribute_id) is int and attribute_id >= 1 and attribute_id == publication_id
                row.update(attribute_publication_id=attribute_id, attribute_clock_matched=matched,
                           attribute_clock_reference="retained_publication_history" if self.attribute_only
                           else "independent_semantic_stamp")
                self.counts["attribute_clock_matched" if matched else "attribute_clock_failed"] += 1
                if not matched:
                    row["geometry_matched"] = False
                    row["history_join_matched"] = False
                    row["failed_paths"].append("Native attribute publication ID differs from semantic stamp")
            entry["observed_roles"].add(role)
            matched = row["history_join_matched"] if self.identity_only else row["geometry_matched"]
            self.counts["matched" if matched else "mismatched"] += 1
        except (ValueError, np.linalg.LinAlgError) as exc:
            row.update(geometry_matched=False, unresolved=str(exc))
            self.counts["unresolved"] += 1
        if self.optical is not None:
            row["optical"] = self.optical.observe(result, row)
            optical_key = "optical_and_source_matched" if self.identity_only else "optical_and_geometry_matched"
            self.counts["optical_matched" if row["optical"][optical_key] else "optical_failed"] += 1
        self._write(row)
        return row

    def raise_if_failed(self):
        if self.error is not None:
            raise RuntimeError("Native source proof failed") from self.error

    def close(self):
        if self.closed:
            return
        errors = []
        if self.replacement is not None:
            if vars(self.manager).get("forward") is self.replacement:
                if self.forward_was_owned:
                    setattr(self.manager, "forward", self.previous_forward)
                else:
                    delattr(self.manager, "forward")
            else:
                errors.append("Another owner replaced the publication hook")
        if self.attribute_tag_owned:
            if self.attribute_clock.Get() != self.attribute_last_written:
                errors.append("Another owner changed the Fabric publication attribute")
            elif not self.attribute_prim.RemoveProperty("fc_exportToRingbuffer"):
                errors.append("Failed to remove owned Fabric export tag")
            else:
                self.attribute_tag_owned = False
        # The runner releases the pre-physics layer after physics shutdown.
        # Late removal of body API schemas would resync live collision shapes.
        if self.stream is not None:
            self.stream.close()
        self.closed = True
        receipt = dict(**self.counts, cleanup_errors=errors, geometry_only=self.optical is None,
                       layer_release_deferred_to_physics_shutdown=True,
                       compact_logging=self.compact_logging,
                       batch_reads=self.batch_reads,
                       skip_redundant_sync=self.skip_redundant_sync,
                       proof_scope=self.proof_scope, body_geometry_checked=not self.clock_only,
                       attribute_probe=self.attribute_probe, attribute_only=self.attribute_only,
                             identity_only=self.identity_only, camera_geometry_checked=not self.identity_only,
                       optical_alignment_proven=False, dataset_admissible=False)
        (self.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        if errors:
            raise RuntimeError("; ".join(errors))
