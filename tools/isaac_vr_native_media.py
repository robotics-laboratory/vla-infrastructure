"""Opt-in current Kit stage RGB products -> owned CUDA frames -> NVENC/preview.

Never reads HDF or applies recorder transforms. Held-state capture preserves
the native physics counter. Source IDs are bindings, not optical proof.
"""
import importlib.util
import json
from pathlib import Path
import threading
import time

ROLES = ("left_wrist", "right_wrist", "scene")


class NativeKitMedia:
    def __init__(self, record, env, output, *, capture="pump", preview=True, witness=False,
                 annotator_name="rgb", fast=False):
        import carb
        import omni.kit.app
        import omni.replicator.core as rep
        import omni.usd
        import torch
        import warp as wp
        from isaac_vr_live_gpu import _CheckedCudaFences
        from isaac_vr_live_nvenc import PacketEncoder

        self.record, self.env, self.output = record, env, Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.thread, self.closed, self.failed = threading.get_ident(), False, False
        self.torch, self.rep, self.wp = torch, rep, wp
        self.settings, self.app = carb.settings.get_settings(), omni.kit.app.get_app()
        self.stage = omni.usd.get_context().get_stage()
        self.capture_mode, self.witness = capture, witness
        self.products, self.annotators, self.references, self.encoders = [], [], [], []
        self.rows, self.preview, self.marker = [], None, None
        self.previous = record._capture_new_observation
        self.was_owned = "_capture_new_observation" in vars(record)
        self.saved_instance = vars(record).get("_capture_new_observation")
        self.restored_settings = {}
        self.partition_specs = []
        self.consumer, self.latest_results, self.last_result_ids = None, {}, None
        self.orchestrator_restore = None
        self.row_file = (self.output / "frames.jsonl").open("x", buffering=1)
        try:
            self.device = wp.get_device("cuda:0")
            self.stream, self.fences = wp.Stream(self.device), _CheckedCudaFences()
            self.initial_native_step = self._native_step()
            if fast:
                for key, value in (("/app/asyncRendering", False),
                                   ("/renderer/lowLatency", True),
                                   ("/rtx/post/aa/op", 0),
                                   ("/rtx/newDenoiser/enabled", False)):
                    self.restored_settings[key] = self.settings.get(key)
                    self.settings.set(key, value)
            for role, path in enumerate(env.camera.camera_prim_paths.values()):
                product = rep.create.render_product(path, (960, 600), name=f"NativeLive{role}")
                self.products.append(product)
                if fast:
                    from isaaclab_teleop.camera_feed_kit_scene_ui import _set_render_product_schema_attribute
                    prim = self.stage.GetPrimAtPath(product.path)
                    _set_render_product_schema_attribute(prim, "OmniRtxPostDebugSettingsAPI_1",
                                                         "omni:rtx:post:aa:op", "none")
                    _set_render_product_schema_attribute(prim, "OmniRtxDebugSettingsAPI_1",
                                                         "omni:rtx:newDenoiser:enabled", False)
                if capture == "callback":
                    self.annotators.append(None)
                    continue
                annotator = rep.AnnotatorRegistry.get_annotator(annotator_name, device="cuda", do_array_copy=False)
                annotator.attach([product.path])
                self.annotators.append(annotator)
                reference = rep.AnnotatorRegistry.get_annotator("ReferenceTime")
                reference.attach([product.path])
                self.references.append(reference)
            if capture == "callback":
                from live_mirror import load
                helper = Path(__file__).resolve().parents[1] / "docs/experiments/20261009_live_camera_recording_30hz/native_live/render_callback.py"
                consumer = load(helper, "native_live_callback").NativeResultConsumer
                self.consumer = consumer({role: p.path for role, p in zip(ROLES, self.products)},
                                         on_frame=lambda result: self.latest_results.__setitem__(result["role"], result))
            if capture == "orchestrator":
                import omni.timeline
                from omni.replicator.core.scripts.orchestrator import SETTINGS_TO_SAVE
                timeline = omni.timeline.get_timeline_interface()
                selection = omni.usd.get_context().get_selection()
                self.orchestrator_restore = (timeline, timeline.get_play_every_frame(),
                                             timeline.is_auto_updating(), selection,
                                             selection.get_selected_prim_paths())
                for key in SETTINGS_TO_SAVE + ["/app/asyncRendering"]:
                    self.restored_settings.setdefault(key, self.settings.get(key))
                for key, value in (("/exts/omni.replicator.core/Orchestrator/enabled", True),
                                   ("/omni/replicator/captureOnPlay", False)):
                    self.restored_settings[key] = self.settings.get(key)
                    self.settings.set(key, value)
                rep.orchestrator.set_capture_on_play(False)
            if witness:
                helper = Path(__file__).resolve().parents[1] / "docs/experiments/20261009_live_camera_recording_30hz/temporal_physics/mesh_freshness.py"
                spec = importlib.util.spec_from_file_location("native_live_marker", helper)
                self.marker = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(self.marker)
                self.marker.inject(self.stage, list(env.camera.camera_prim_paths.values()),
                                   products=[p.path for p in self.products])
                from isaacsim.core.experimental.prims import XformPrim
                self.camera_views = XformPrim(list(env.camera.camera_prim_paths.values()),
                                             resolve_paths=False, reset_xform_op_properties=False)
                self._publish_marker(0)
            for _ in range(12):
                self._pump()
            with self.device.context_guard:
                for role in range(3):
                    self.encoders.append(PacketEncoder(
                        self.output / "media" / f"role{role}", width=960, height=600,
                        cpu=False, cuda_context=self.device.context,
                        cuda_stream=self.stream.cuda_stream, gpu=0, fps=30,
                        release_owner=lambda frame: None,
                        synchronize=lambda: self.fences.stream(self.stream)))
            if preview:
                from isaac_vr_native_preview import SharedCameraPreview
                from isaac_preview_partitions import PreviewPartitions
                for key in ("/renderer/scenePartitioning/enabled",
                            "/rtx/scenePartitioning/showAllPartitionsByDefault"):
                    self.restored_settings.setdefault(key, self.settings.get(key))
                    self.settings.set_bool(key, True)
                isolation = PreviewPartitions(self.stage)
                from pxr import Sdf
                session = self.stage.GetSessionLayer()
                backup = Sdf.Layer.CreateAnonymous("native-partitions")
                for path in env.camera.camera_prim_paths.values():
                    prop = Sdf.Path(path).AppendProperty("omni:scenePartition")
                    existing = session.GetPropertyAtPath(prop) is not None
                    if existing:
                        Sdf.CreatePrimInLayer(backup, prop.GetPrimPath())
                        Sdf.CopySpec(session, prop, backup, prop)
                    self.partition_specs.append((prop, backup, existing))
                isolation.bind_sensors([], concrete_paths=list(env.camera.camera_prim_paths.values()))
                self.preview = SharedCameraPreview(env.vr_runtime.config, isolation=isolation)
            (self.output / "setup.json").write_text(json.dumps(dict(
                source="main_kit_stage_rgb", current_stage_id=self.stage.GetRootLayer().identifier,
                camera_paths=env.camera.camera_prim_paths, products=[p.path for p in self.products],
                capture=capture, annotator=annotator_name, fast=fast,
                effective_settings={k: self.settings.get(k) for k in self.restored_settings},
                physics_step_at_setup=self.initial_native_step,
                preview_isolation="scene-partitions" if preview else None), indent=2) + "\n")
            record._capture_new_observation = self.capture
        except BaseException:
            self.close()
            raise

    def _native_step(self):
        from isaacsim.core.simulation_manager import SimulationManager
        return int(SimulationManager.get_num_physics_steps())

    def _pump(self):
        if self.preview and getattr(self.preview, "isolation", None):
            self.preview.isolation.assert_valid()
        before = self._native_step()
        key = "/app/player/playSimulations"
        previous = self.settings.get(key)
        self.settings.set_bool(key, False)
        try:
            if self.capture_mode == "orchestrator":
                self.rep.orchestrator.step(delta_time=0.0, pause_timeline=False,
                                           rt_subframes=1, wait_for_render=True)
            else:
                self.app.update()
        finally:
            self.settings.set(key, previous)
        if self._native_step() != before:
            raise RuntimeError("Native physics advanced during camera-only capture")

    def _publish_marker(self, source):
        import numpy as np
        from pxr import Gf, UsdGeom
        from isaacsim.core.experimental.utils.backend import use_backend
        from live_mirror import load
        helper = Path(__file__).resolve().parents[1] / "docs/experiments/20261009_live_camera_recording_30hz/deep_research/ovrtx_live_probe.py"
        with use_backend("usdrt"):
            positions, rotations = self.camera_views.get_world_poses()
        world = load(helper, "native_live_pose").pose_matrices(positions.numpy(), rotations.numpy())
        for role, path in enumerate(self.env.camera.camera_prim_paths.values()):
            camera = UsdGeom.Camera(self.stage.GetPrimAtPath(path))
            intrinsics = [camera.GetFocalLengthAttr().Get(), camera.GetHorizontalApertureAttr().Get(),
                          camera.GetVerticalApertureAttr().Get()]
            for kind in ["background", "marker"] + [f"cell{i}" for i in range(16)]:
                mesh = UsdGeom.Xformable(self.stage.GetPrimAtPath(f"/LiveTemporalMesh/Role{role}/{kind}"))
                matrix = self.marker.local_matrix(kind, role, intrinsics, source) @ world[role]
                mesh.GetOrderedXformOps()[0].Set(Gf.Matrix4d(*np.asarray(matrix).reshape(-1).tolist()))

    def capture(self):
        if self.closed or self.failed or threading.get_ident() != self.thread:
            raise RuntimeError("Native camera capture requires its Kit owner thread")
        try:
            return self._capture_current()
        except BaseException:
            self.failed = True
            raise

    def _capture_current(self):
        token, frames = self.previous()
        if token.capture_sequence != len(self.rows):
            raise RuntimeError("Nonconsecutive native source boundary")
        if self.marker:
            self._publish_marker(token.capture_sequence)
        start = time.monotonic_ns()
        if self.consumer:
            self.consumer.raise_if_failed()
        else:
            self._pump()
        if token.capture_sequence == 0 and self.capture_mode == "orchestrator":
            # Initial camera/body publication can precede recorder admission.
            self._pump()
        if (self.env.sim.get_physics_step_count() != token.physics_step
                or self.env.camera.reset_epoch != token.reset_epoch
                or self.env._state_physics_step != token.state_generation):
            raise RuntimeError("Native camera source boundary changed during capture")
        images, references = {}, []
        for role, annotator in zip(ROLES, self.annotators, strict=True):
            if self.consumer:
                result = self.latest_results.get(role)
                if result is None:
                    raise RuntimeError("Native result callback lacks a three-role frame")
                images[role] = self.torch.from_dlpack(result["rgba"])
                continue
            data = annotator.get_data()
            if isinstance(data, dict):
                data = data["data"]
            # The raw annotator pointer has no reliable producer-stream receipt.
            # Conservatively fence the main CUDA context before borrowing it.
            self.torch.cuda.synchronize()
            image = self.torch.from_dlpack(data).reshape(600, 960, 4)
            if (image.device.type != "cuda" or image.dtype != self.torch.uint8
                    or getattr(image.device, "index", 0) not in (None, 0)):
                raise RuntimeError("Native camera is not a CUDA RGBA8 producer")
            images[role] = image.clone()
        # Establish producer/clone completion before NVENC's explicit stream.
        if not self.consumer:
            self.torch.cuda.synchronize()
        if (self.env.sim.get_physics_step_count() != token.physics_step
                or self.env.camera.reset_epoch != token.reset_epoch
                or self.env._state_physics_step != token.state_generation):
            raise RuntimeError("Native camera source boundary changed during extraction")
        completed = time.monotonic_ns()
        result_ids = {role: result["frame_identifier"] for role, result in self.latest_results.items()}
        if self.consumer:
            if result_ids == self.last_result_ids:
                raise RuntimeError("Native result callback did not advance")
            ids = [tuple(sorted(v.items())) for v in result_ids.values()]
            if len(set(ids)) != 1:
                raise RuntimeError("Native result callback roles have different result identities")
            if self.last_result_ids and any(result_ids[role]["frameNumber"] <= old["frameNumber"]
                                            for role, old in self.last_result_ids.items()):
                raise RuntimeError("Native result callback identity regressed")
            self.last_result_ids = result_ids
        for reference in self.references:
            references.append(str(reference.get_data()))
        from isaac_vr_live_nvenc import CudaRGBAFrame
        with self.device.context_guard:
            for index, role in enumerate(ROLES):
                image = images[role]
                self.encoders[index].submit(CudaRGBAFrame(image, image.data_ptr(), 960, 600),
                                            token.capture_sequence)
        if self.preview:
            self.preview.publish(token.capture_sequence, images)
            # Provider copies GPU memory; retain immutable frames through upload.
            self.torch.cuda.synchronize()
        row = dict(source_id=token.capture_sequence, physics_step=token.physics_step,
                   state_generation=token.state_generation,
                   snapshot_id=token.scene_state_snapshot_id, snapshot_sha256=token.scene_state_snapshot_sha256,
                   reset_epoch=token.reset_epoch, capture_begin_ns=start, pixels_owned_ns=completed,
                   write_submitted_ns=time.monotonic_ns(), reference_time=references,
                   preview_same_owned_frame=self.preview is not None,
                   owned_cuda_pointers={role: image.data_ptr() for role, image in images.items()},
                   native_result_identifiers=result_ids,
                   native_formats={role: result["native_format"] for role, result in self.latest_results.items()},
                   source="main_kit_stage_rgb", optical_alignment_proven=False)
        self.rows.append(row)
        self.row_file.write(json.dumps(row) + "\n")
        return token, frames

    def close(self):
        if self.closed:
            return getattr(self, "receipt", {})
        if self.was_owned:
            self.record._capture_new_observation = self.saved_instance
        else:
            vars(self.record).pop("_capture_new_observation", None)
        errors, encoded = [], []
        for encoder in self.encoders:
            try:
                with self.device.context_guard:
                    encoded.append(encoder.finish())
            except BaseException as exc:
                errors.append(str(exc))
        done = time.monotonic_ns()
        def release(action):
            try:
                action()
            except BaseException as exc:
                errors.append(str(exc))
        if self.orchestrator_restore:
            def stop_capture():
                key = "/app/player/playSimulations"
                previous, before = self.settings.get(key), self._native_step()
                self.settings.set_bool(key, False)
                try:
                    self.rep.orchestrator.stop()
                    self.rep.orchestrator.wait_until_complete()
                    # Upstream defers async-rendering restoration by five updates.
                    for _ in range(6):
                        self.app.update()
                    if self._native_step() != before:
                        raise RuntimeError("Native physics advanced during capture teardown")
                finally:
                    self.settings.set(key, previous)
            release(stop_capture)
            timeline, play_every, auto_update, selection, selected = self.orchestrator_restore
            release(lambda: timeline.set_play_every_frame(play_every))
            release(lambda: timeline.set_auto_update(auto_update))
            release(timeline.commit_silently)
            release(lambda: selection.set_selected_prim_paths(selected, False))
        if self.preview:
            release(self.preview.close)
        if self.consumer:
            release(self.consumer.close)
        if self.partition_specs:
            from pxr import Sdf, Usd
            for prop, backup, existing in self.partition_specs:
                def restore_partition(prop=prop, backup=backup, existing=existing):
                    with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
                        self.stage.GetPrimAtPath(prop.GetPrimPath()).RemoveProperty(prop.name)
                    if existing:
                        if not Sdf.CopySpec(backup, prop, self.stage.GetSessionLayer(), prop):
                            raise RuntimeError(f"Camera partition restoration failed: {prop}")
                release(restore_partition)
        for annotator, product in zip(self.annotators, self.products):
            if annotator is not None:
                release(lambda: annotator.detach([product.path]))
        for annotator, product in zip(self.references, self.products):
            release(lambda: annotator.detach([product.path]))
        for product in self.products:
            release(product.destroy)
        if self.marker:
            for path in ("/LiveTemporalMesh", "/LiveTemporalMaterials"):
                release(lambda: self.stage.RemovePrim(path))
        for key, value in self.restored_settings.items():
            release(lambda: self.settings.set(key, value))
            if self.settings.get(key) != value:
                errors.append(f"Setting restoration mismatch: {key}")
        release(self.row_file.close)
        self.closed = True
        self.receipt = dict(source="main_kit_stage_rgb", captures=len(self.rows),
                            encode_done_ns=done, encoders=encoded, cleanup_errors=errors,
                            preview_publications=self.preview.publications if self.preview else 0,
                            native_callback_counts=dict(self.consumer.counts) if self.consumer else {},
                            snapshot_renderer_used=False, dataset_admissible=False)
        (self.output / "receipt.json").write_text(json.dumps(self.receipt, indent=2) + "\n")
        if errors:
            raise RuntimeError("Native camera encoder drain failed: " + str(errors))
        return self.receipt
