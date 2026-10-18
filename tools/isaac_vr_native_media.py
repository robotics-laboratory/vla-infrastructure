"""Opt-in current Kit stage RGB products -> owned CUDA frames -> NVENC/preview.

Never reads HDF or applies recorder transforms. Camera/preview ownership spans
RUN/DIAG and recording episodes; only attached episodes open encoders and binding
HDF. Held-state capture preserves the native physics counter. Source IDs are
bindings, not optical proof.
"""
import importlib.util
from collections import deque
import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading
import time

ROLES = ("left_wrist", "right_wrist", "scene")


class NativeKitMedia:
    def __init__(self, record, env, output, *, capture="pump", preview=True, witness=False,
                 annotator_name="rgb", fast=False, rendering="default", viewport=True,
                 preview_transport="cuda", max_publications=None, source_proof=False, optical_proof=False, managed_probe=False, prepared_source_layer=None, no_temporal_lighting=False, bind_sources=False, proof_compact=False, legacy_products=False, proof_batch_reads=False, proof_skip_sync=False, proof_clock_only=False, attribute_probe=False, attribute_only=False, identity_only=False, cache_helpers=False):
        import carb
        import omni.kit.app
        import omni.replicator.core as rep
        import omni.usd
        import torch
        import warp as wp
        from isaac_vr_live_gpu import _CheckedCudaFences

        self.record, self.env, self.output = None, env, Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.thread, self.closed, self.failed = threading.get_ident(), False, False
        self.torch, self.rep, self.wp = torch, rep, wp
        self.settings, self.app = carb.settings.get_settings(), omni.kit.app.get_app()
        self.stage = omni.usd.get_context().get_stage()
        self.capture_mode, self.witness = capture, witness
        self.products, self.annotators, self.references, self.encoders = [], [], [], []
        self.rows, self.preview, self.marker = deque(maxlen=3), None, None
        self.capture_count = 0
        self.previous, self.saved_instance, self.was_owned = None, None, False
        self.episode_output, self.row_file = None, None
        self.encoded_count = self.boundary_count = self.warmup_skips = 0
        self.source_epoch = env.camera.reset_epoch
        self.bind_sources = bind_sources
        self.binding_options = dict(clock_only=proof_clock_only,
                                    attribute_only=attribute_only, identity_only=identity_only)
        self.episode_receipts = []
        self.restored_settings = {}
        self.partition_specs = []
        self.consumer, self.latest_results, self.last_result_ids = None, {}, None
        self.orchestrator_restore = None
        self.viewport_restore = None
        self.source_proof = None
        self.managed_probe = None
        self.source_binding, self.binding_hdf = None, None
        self.legacy_products = legacy_products
        self.legacy_opinions = (
            ("OmniRtxSettingsCommonAPI_1", "omni:rtx:rendermode", "RaytracedLighting"),
            ("OmniRtxDebugSettingsAPI_1", "omni:rtx:rtpt:rtCompatibility", True),
            ("OmniRtxDebugSettingsAPI_1", "omni:rtx:newDenoiser:enabled", False),
            ("OmniRtxPostDebugSettingsAPI_1", "omni:rtx:post:aa:limitedOps", False),
            ("OmniRtxPostDebugSettingsAPI_1", "omni:rtx:post:aa:op", "none"),
        )
        if bind_sources and not source_proof:
            raise ValueError("Live source bindings require rendered geometry proof")
        if optical_proof and (not source_proof or witness):
            raise ValueError("Optical publication proof requires source proof and disabled old witness")
        try:
            self.device = wp.get_device("cuda:0")
            self.stream, self.fences = wp.Stream(self.device), _CheckedCudaFences()
            self.initial_native_step = self._native_step()
            if fast:
                for key, value in (("/app/asyncRendering", False),
                                   ("/renderer/lowLatency", True),
                                   ("/rtx/post/aa/op", 0),
                                   ("/rtx/newDenoiser/enabled", False)):
                    previous = self.settings.get(key)
                    if previous != value:
                        print(json.dumps(dict(event="native_renderer_setting", key=key,
                                              previous=previous, requested=value)), flush=True)
                        self.restored_settings[key] = previous
                        self.settings.set(key, value)
            if rendering != "default":
                asynchronous = rendering.startswith("async")
                for key, value in (("/app/asyncRendering", asynchronous),
                                   ("/app/asyncRenderingLowLatency", rendering == "async-latency"),
                                   ("/app/omni.usd/asyncHandshake", asynchronous),
                                   ("/omni/replicator/asyncRendering", asynchronous),
                                   ("/exts/isaacsim.core.throttling/enable_async", False),
                                   ("/renderer/lowLatency", rendering == "async-latency")):
                    self.restored_settings.setdefault(key, self.settings.get(key))
                    self.settings.set(key, value)
            if not viewport:
                from omni.kit.viewport.utility import get_active_viewport
                active = get_active_viewport()
                if active is None:
                    raise RuntimeError("Viewport ablation requires an active viewport")
                self.viewport_restore = (active, active.updates_enabled)
                active.updates_enabled = False
            for role, path in enumerate(env.camera.camera_prim_paths.values()):
                product = rep.create.render_product(path, (960, 600), name=f"NativeLive{role}")
                self.products.append(product)
                if rendering.startswith("async"):
                    product.hydra_texture.is_async = True
                if fast:
                    from isaaclab_teleop.camera_feed_kit_scene_ui import _set_render_product_schema_attribute
                    prim = self.stage.GetPrimAtPath(product.path)
                    _set_render_product_schema_attribute(prim, "OmniRtxPostDebugSettingsAPI_1",
                                                         "omni:rtx:post:aa:op", "none")
                    _set_render_product_schema_attribute(prim, "OmniRtxDebugSettingsAPI_1",
                                                         "omni:rtx:newDenoiser:enabled", False)
                if no_temporal_lighting:
                    from isaaclab_teleop.camera_feed_kit_scene_ui import _set_render_product_schema_attribute
                    prim = self.stage.GetPrimAtPath(product.path)
                    for suffix, value in (
                        ("directLighting:domeLight:denoisingTechnique", "None"),
                        ("directLighting:sampledLighting:denoisingTechnique", "None"),
                        ("indirectDiffuse:denoiser:enabled", False),
                        ("indirectDiffuse:denoiser:temporal:enabled", False),
                        ("directLighting:sampledLighting:irradiance:denoiser:enabled", False),
                        ("reflections:denoiser:enabled", False),
                        ("shadows:denoiser:enabled", False),
                    ):
                        _set_render_product_schema_attribute(
                            prim, "OmniRtxDebugSettingsAPI_1", "omni:rtx:" + suffix, value)
                if legacy_products:
                    from pxr import Usd
                    from isaaclab_teleop.camera_feed_kit_scene_ui import _set_render_product_schema_attribute
                    with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
                        prim = self.stage.GetPrimAtPath(product.path)
                        for api, name, value in self.legacy_opinions:
                            _set_render_product_schema_attribute(prim, api, name, value)
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
                from isaac_vr_native_callback import NativeResultConsumer

                consumer = NativeResultConsumer
                if source_proof:
                    from isaac_vr_native_source_proof import NativeSourceProof
                    self.source_proof = NativeSourceProof(env, self.output, optical=optical_proof,
                                                          render_products=[p.path for p in self.products],
                                                          prepared_layer=prepared_source_layer,
                                                          compact_logging=proof_compact,
                                                          batch_reads=proof_batch_reads,
                                                          skip_redundant_sync=proof_skip_sync,
                                                          clock_only=proof_clock_only,
                                                          attribute_probe=attribute_probe,
                                                          attribute_only=attribute_only, identity_only=identity_only)
                if managed_probe:
                    from live_mirror import load
                    path = Path(__file__).resolve().parents[1] / "docs/experiments/20261009_live_camera_recording_30hz/native_deep/managed_event_probe.py"
                    self.managed_probe = load(path, "native_managed_probe").ManagedEventProbe(
                        {role: (p.path, p.hydra_texture) for role, p in zip(ROLES, self.products)},
                        retain_managed=True, max_managed_per_role=max_publications + 32,
                        max_events_per_stream=3 * (max_publications + 32))
                def accept_result(result):
                    if self.source_proof:
                        result["source_proof"] = self.source_proof.observe(result)
                    if self.managed_probe:
                        self.managed_probe.observe_sd(result)
                    self.latest_results[result["role"]] = result
                self.consumer = consumer({role: p.path for role, p in zip(ROLES, self.products)},
                                         on_frame=accept_result, geometry=source_proof,
                                         attribute_probe=attribute_probe, attribute_only=attribute_only, identity_only=identity_only, cache_helpers=cache_helpers,
                                         attribute_probe_output=self.output / "attribute-probe.jsonl" if attribute_probe else None)
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
                self.preview = SharedCameraPreview(env.vr_runtime.config, isolation=isolation,
                                                   transport=preview_transport,
                                                   max_publications=max_publications)
            (self.output / "setup.json").write_text(json.dumps(dict(
                source="main_kit_stage_rgb", current_stage_id=self.stage.GetRootLayer().identifier,
                camera_paths=env.camera.camera_prim_paths, products=[p.path for p in self.products],
                capture=capture, annotator=annotator_name, fast=fast,
                rendering=rendering, viewport_updates=viewport,
                preview_transport=preview_transport, source_proof=source_proof,
                no_temporal_lighting=no_temporal_lighting,
                proof_compact=proof_compact,
                proof_batch_reads=proof_batch_reads,
                proof_skip_sync=proof_skip_sync,
                proof_clock_only=proof_clock_only,
                attribute_probe=attribute_probe,
                attribute_only=attribute_only,
                identity_only=identity_only,
                cache_helpers=cache_helpers,
                legacy_products=legacy_products,
                authored_product_settings={p.path: {
                    "applied_schemas": list(self.stage.GetPrimAtPath(p.path).GetAppliedSchemas()),
                    "attributes": {a.GetName(): a.Get()
                                   for a in self.stage.GetPrimAtPath(p.path).GetAttributes()
                                   if a.GetName().startswith("omni:rtx:") and a.HasAuthoredValueOpinion()},
                } for p in self.products},
                rendering_context={k: self.settings.get(k) for k in (
                    "/app/hydra/renderSettings/useUsdAttributes", "/app/hydra/renderSettings/useFabricAttributes",
                    "/rtx/rendermode", "/rtx-transient/post/aa/limitedOps", "/rtx-transient/dldenoiser/enabled",
                    "/rtx/rtpt/rtCompatibility", "/persistent/rtx/modes/rt2/enabled", "/rtx/post/aa/op")},
                effective_settings={k: self.settings.get(k) for k in self.restored_settings},
                physics_step_at_setup=self.initial_native_step,
                preview_isolation="scene-partitions" if preview else None), indent=2, default=str) + "\n")
            if record is not None:
                self.start_recording(record, self.output)
        except BaseException:
            self.close()
            raise

    def start_recording(self, record, output):
        """Attach one episode; camera, callback and source clock retain ownership."""
        self._guard()
        if self.record is not None:
            raise RuntimeError("A native media recording is already attached")
        if self.env.camera.reset_epoch != self.source_epoch:
            raise RuntimeError("Reset requires reset_source_epoch before recording")
        from isaac_vr_live_nvenc import PacketEncoder
        self.episode_output = Path(output)
        self.episode_output.mkdir(parents=True, exist_ok=self.episode_output == self.output)
        self.capture_count = self.encoded_count = self.warmup_skips = 0
        self.episode_first_step = None
        self.rows.clear()
        self.record = record
        self.previous = record._capture_new_observation
        self.was_owned = "_capture_new_observation" in vars(record)
        self.saved_instance = vars(record).get("_capture_new_observation")
        record._capture_new_observation = self.capture
        try:
            self.row_file = (self.episode_output / "frames.jsonl").open("x", buffering=1)
            with self.device.context_guard:
                for role in range(3):
                    self.encoders.append(PacketEncoder(
                        self.episode_output / "media" / f"role{role}", width=960, height=600,
                        cpu=False, cuda_context=self.device.context,
                        cuda_stream=self.stream.cuda_stream, gpu=0, fps=30,
                        release_owner=lambda frame: None,
                        synchronize=lambda: self.fences.stream(self.stream)))
            self._open_bindings()
        except BaseException:
            self.failed = True
            self.stop_recording()
            raise

    def _open_bindings(self):
        if self.bind_sources:
            import h5py
            import numpy as np
            from isaac_vr_native_binding import NativeSourceBinding
            self.source_binding = NativeSourceBinding(capacity=256, **self.binding_options)
            self.binding_hdf = h5py.File(self.episode_output / "camera_bindings.hdf5", "x", libver="latest")
            dtype = np.dtype([(k, "<i8") for k in (
                "packet_ordinal", "current_capture_sequence", "actual_capture_sequence",
                "publication_id", "reset_epoch", "physics_step", "state_generation")]
                + [("scene_state_snapshot_id", "S512"), ("scene_state_snapshot_sha256", "S64")])
            self.binding_table = self.binding_hdf.create_dataset(
                "bindings", shape=(0,), maxshape=(None,), chunks=(64,), dtype=dtype)
            self.binding_hdf.attrs.update(
                schema="native_live_rendered_source_bindings_v1", committed_rows=0,
                state_hdf=os.path.relpath(getattr(self.record, "hdf5_path",
                    self.episode_output.parent / "episode/session.hdf5"), self.episode_output),
                roles=json.dumps(list(ROLES)),
                media=json.dumps([f"media/role{i}/stream.h264" for i in range(3)]),
                dataset_admissible=False, optical_alignment_proven=False, receipt="")
            self.binding_hdf.attrs["proof_scope"] = self.source_binding.proof_scope
            self.binding_hdf.attrs["body_geometry_checked"] = self.source_binding.proof_scope == "full_native_body_camera"
            self.binding_hdf.attrs["camera_geometry_checked"] = not self.binding_options["identity_only"]
            self.binding_hdf.flush()
            self.binding_hdf.swmr_mode = True

    def _guard(self):
        if self.closed or self.failed or threading.get_ident() != self.thread:
            raise RuntimeError("Native camera capture requires its Kit owner thread")

    def reset_source_epoch(self):
        """Acknowledge a detached canonical reset without resetting native publication IDs."""
        self._guard()
        if self.record is not None:
            raise RuntimeError("Detach recording before resetting native source history")
        self.source_epoch = self.env.camera.reset_epoch
        self.last_result_ids = None
        # Called after canonical reset/settling renders. No-proof profiles retain
        # that completed triplet without assigning it a rendered source identity.
        if self.source_proof:
            self.latest_results = {role: result for role, result in self.latest_results.items()
                if result.get("source_proof", {}).get("reset_epoch") == self.source_epoch}
            for publication, entry in list(self.source_proof.history.items()):
                if entry.get("source", {}).get("reset_epoch") != self.source_epoch:
                    del self.source_proof.history[publication]

    def stop_recording(self):
        """Drain only the episode. Keep camera, preview and native forward hook live."""
        if threading.get_ident() != self.thread:
            raise RuntimeError("Native recording drain requires its Kit owner thread")
        if self.record is None:
            return getattr(self, "last_episode_receipt", None)
        errors, encoded = [], []
        def release(action):
            try:
                return action()
            except BaseException as exc:
                errors.append(str(exc))
        if vars(self.record).get("_capture_new_observation") == self.capture:
            if self.was_owned:
                self.record._capture_new_observation = self.saved_instance
            else:
                vars(self.record).pop("_capture_new_observation", None)
        else:
            errors.append("Another owner replaced the recording capture hook")
        self.record = None
        for encoder in self.encoders:
            def finish(encoder=encoder):
                with self.device.context_guard:
                    return encoder.finish()
            encoded.append(release(finish))
        binding = self.source_binding.receipt() if getattr(self, "source_binding", None) else None
        if getattr(self, "binding_hdf", None):
            release(lambda: self.binding_hdf.attrs.modify("receipt", json.dumps(binding)))
            release(self.binding_hdf.close)
        if self.row_file:
            release(self.row_file.close)
        receipt = dict(source="main_kit_stage_rgb", captures=self.capture_count,
                       encoded_packets=getattr(self, "encoded_count", self.capture_count),
                       warmup_skips=getattr(self, "warmup_skips", 0),
                       encode_done_ns=time.monotonic_ns(), encoders=encoded,
                       cleanup_errors=errors, source_binding=binding,
                       snapshot_renderer_used=False, dataset_admissible=False)
        output = getattr(self, "episode_output", None) or self.output
        release(lambda: (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n"))
        self.encoders, self.source_binding, self.binding_hdf = [], None, None
        self.previous = self.saved_instance = None
        self.last_episode_receipt = receipt
        if hasattr(self, "episode_receipts"):
            self.episode_receipts.append(dict(output=str(output), **receipt))
        if errors:
            self.failed = True
            raise RuntimeError("Native camera encoder drain failed: " + str(errors))
        return receipt

    def capture_boundary(self, token=None, frames=None):
        """Observe a canonical control boundary, including detached RUN/DIAG preview."""
        self._guard()
        if token is None and self.record is not None:
            raise RuntimeError("Attached recording owns its canonical observation capture")
        try:
            return self._capture_current(token, frames)
        except BaseException:
            self.failed = True
            raise

    def _native_step(self):
        from isaacsim.core.simulation_manager import SimulationManager
        return int(SimulationManager.get_num_physics_steps())

    def verify_product_settings(self, phase):
        """Retain actual opinions and layer ownership; not proof of active RTX passes."""
        if not self.legacy_products:
            return
        receipt = {}
        for product in self.products:
            prim = self.stage.GetPrimAtPath(product.path)
            receipt[product.path] = {}
            for _, name, expected in self.legacy_opinions:
                attr = prim.GetAttribute(name)
                value = attr.Get()
                receipt[product.path][name] = dict(
                    value=value, expected=expected, authored=attr.IsAuthored(),
                    property_stack=[dict(layer=s.layer.identifier, path=str(s.path))
                                    for s in attr.GetPropertyStack()])
        (self.output / f"product-settings-{phase}.json").write_text(
            json.dumps(receipt, indent=2, default=str) + "\n")
        if any(v["value"] != v["expected"] for fields in receipt.values() for v in fields.values()):
            raise RuntimeError("Native product renderer opinions were overwritten")

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

    def _capture_current(self, token=None, frames=None):
        if getattr(self, "legacy_products", False) and not self.rows:
            self.verify_product_settings("first-capture")
        recording = self.record is not None
        if token is None:
            if recording:
                token, frames = self.previous()
            else:
                token = SimpleNamespace(capture_sequence=getattr(self, "boundary_count", 0),
                    physics_step=self.env.sim.get_physics_step_count(),
                    reset_epoch=self.env.camera.reset_epoch,
                    state_generation=self.env._state_physics_step,
                    scene_state_snapshot_id=None, scene_state_snapshot_sha256=None)
        if token.reset_epoch != getattr(self, "source_epoch", token.reset_epoch):
            raise RuntimeError("Reset requires reset_source_epoch before capture")
        if recording and token.capture_sequence != self.capture_count:
            raise RuntimeError("Nonconsecutive native source boundary")
        if getattr(self, "source_binding", None):
            self.source_binding.register(token)
            if self.episode_first_step is None:
                self.episode_first_step = token.physics_step
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
        binding, warmup = None, False
        proofs = {role: result.get("source_proof") for role, result in self.latest_results.items()}
        if getattr(self, "source_proof", None):
            identities = set()
            for role in ROLES:
                proof = proofs.get(role)
                if (not isinstance(proof, dict) or proof.get("role") != role
                        or proof.get("failed_paths") or proof.get("unresolved")
                        or not (proof.get("geometry_matched") is True
                                or proof.get("proof_scope") == "publication_attribute"
                                and proof.get("history_join_matched") is True
                                and proof.get("attribute_clock_matched") is True)):
                    raise RuntimeError("Native rendered source proof is unresolved or mismatched")
                identities.add((proof.get("publication_id"), proof.get("reset_epoch"), proof.get("physics_step")))
            if len(identities) != 1:
                raise RuntimeError("Native rendered roles disagree on source identity")
            _, epoch, step = next(iter(identities))
            if epoch != token.reset_epoch or step is None or step > token.physics_step:
                raise RuntimeError("Native rendered source crosses current epoch/time")
            warmup = bool(getattr(self, "source_binding", None) and step < self.episode_first_step)
        if self.consumer:
            # Start observes the already completed O_t before any native step.
            # Reuse it once; subsequent observations still require fresh results.
            initial_reuse = recording and self.capture_count == 0 and result_ids == self.last_result_ids
            if result_ids == self.last_result_ids:
                if not recording:
                    return token, frames
                if not initial_reuse:
                    raise RuntimeError("Native result callback did not advance")
            ids = [tuple(sorted(v.items())) for v in result_ids.values()]
            if len(set(ids)) != 1:
                raise RuntimeError("Native result callback roles have different result identities")
            if self.last_result_ids and not initial_reuse and any(result_ids[role]["frameNumber"] <= old["frameNumber"]
                                            for role, old in self.last_result_ids.items()):
                raise RuntimeError("Native result callback identity regressed")
            self.last_result_ids = result_ids
        if getattr(self, "source_binding", None) and not warmup:
            binding = self.source_binding.bind(getattr(self, "encoded_count", self.capture_count), proofs)
            if len(binding["scene_state_snapshot_id"].encode("utf-8")) > 512:
                raise ValueError("Snapshot identity exceeds binding HDF capacity")
        for reference in self.references:
            references.append(str(reference.get_data()))
        if recording and not warmup:
            from isaac_vr_live_nvenc import CudaRGBAFrame
            with self.device.context_guard:
                for index, role in enumerate(ROLES):
                    image = images[role]
                    self.encoders[index].submit(CudaRGBAFrame(image, image.data_ptr(), 960, 600),
                                                getattr(self, "encoded_count", self.capture_count))
        if self.preview:
            self.preview.publish(getattr(self, "boundary_count", token.capture_sequence), images)
            # Provider copies GPU memory; retain immutable frames through upload.
            if (getattr(self.preview, "cpu_probe", None) is None
                    and getattr(self.preview, "transport", None) not in ("cuda-retained", "cuda-event")):
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
                   native_copy_ns={role: result.get("copy_ns") for role, result in self.latest_results.items()},
                   rendered_source_proof={role: result.get("source_proof") for role, result in self.latest_results.items()},
                   camera_source_binding=binding,
                   encoded=recording and not warmup,
                   coverage="pre_episode_source_skipped" if warmup else "recorded" if recording else "preview_only",
                   preview_transport=getattr(self.preview, "transport", None),
                   source="main_kit_stage_rgb", optical_alignment_proven=False)
        self.rows.append(row)
        self.boundary_count = getattr(self, "boundary_count", 0) + 1
        if recording:
            self.capture_count += 1
            self.encoded_count = getattr(self, "encoded_count", self.capture_count - 1) + (not warmup)
            self.warmup_skips = getattr(self, "warmup_skips", 0) + warmup
            self.row_file.write(json.dumps(row) + "\n")
        if binding is not None:
            snapshot = binding["scene_state_snapshot_id"].encode("utf-8")
            if len(snapshot) > 512:
                raise ValueError("Snapshot identity exceeds binding HDF capacity")
            self.binding_table.resize((self.encoded_count,))
            self.binding_table[-1] = tuple(binding[k] for k in self.binding_table.dtype.names[:7]) + (
                snapshot, binding["scene_state_snapshot_sha256"].encode("ascii"))
            self.binding_hdf.attrs.modify("committed_rows", self.encoded_count)
            self.binding_hdf.flush()
        return token, frames

    def close(self):
        if self.closed:
            return getattr(self, "receipt", {})
        if threading.get_ident() != self.thread:
            raise RuntimeError("Native camera teardown requires its Kit owner thread")
        errors = []
        episode = getattr(self, "last_episode_receipt", None)
        if self.record is not None:
            try:
                episode = self.stop_recording()
            except BaseException as exc:
                errors.append(str(exc))
                episode = getattr(self, "last_episode_receipt", None)
        encoded = episode["encoders"] if episode else []
        done = episode["encode_done_ns"] if episode else time.monotonic_ns()
        if getattr(self, "legacy_products", False):
            try:
                self.verify_product_settings("after-loop")
            except BaseException as exc:
                errors.append(str(exc))
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
        if getattr(self, "viewport_restore", None):
            active, previous_updates = self.viewport_restore
            release(lambda: setattr(active, "updates_enabled", previous_updates))
            if active.updates_enabled != previous_updates:
                errors.append("Viewport update restoration mismatch")
        if getattr(self, "managed_probe", None):
            release(self.managed_probe.close)
            (self.output / "managed-event-probe.json").write_text(
                json.dumps(self.managed_probe.receipt(), indent=2) + "\n")
        if self.consumer:
            release(self.consumer.close)
        if getattr(self, "source_proof", None):
            release(self.source_proof.close)
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
            if getattr(self, "legacy_products", False):
                from pxr import Usd
                def remove_owned_opinions(product=product):
                    with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
                        self.stage.RemovePrim(product.path)
                release(remove_owned_opinions)
        if self.marker:
            for path in ("/LiveTemporalMesh", "/LiveTemporalMaterials"):
                release(lambda: self.stage.RemovePrim(path))
        for key, value in self.restored_settings.items():
            release(lambda: self.settings.destroy_item(key) if value is None else self.settings.set(key, value))
            if self.settings.get(key) != value:
                errors.append(f"Setting restoration mismatch: {key}")
        self.closed = True
        self.receipt = dict(source="main_kit_stage_rgb", captures=getattr(self, "capture_count", len(self.rows)),
                            encode_done_ns=done, encoders=encoded, cleanup_errors=errors,
                            preview_publications=self.preview.publications if self.preview else 0,
                            source_binding=episode.get("source_binding") if episode else None,
                            encoded_packets=episode.get("encoded_packets", 0) if episode else 0,
                            warmup_skips=episode.get("warmup_skips", 0) if episode else 0,
                            episodes=getattr(self, "episode_receipts", []),
                            preview_boundaries=getattr(self, "boundary_count", 0),
                            native_callback_counts=dict(self.consumer.counts) if self.consumer else {},
                            snapshot_renderer_used=False, dataset_admissible=False)
        if self.preview and getattr(self.preview, "cpu_probe", None):
            self.receipt["host_preview_retained_bytes"] = sum(
                array.nbytes for submission in self.preview.cpu_probe.submitted for array in submission.values())
            self.receipt["host_preview_retention_until_app_close"] = True
        if self.preview and getattr(self.preview, "copy_queue", None):
            self.receipt["preview_copy_queue"] = self.preview.copy_queue.receipt()
        if self.preview and getattr(self.preview, "gpu_retained", None):
            self.receipt["gpu_preview_retained_bytes"] = sum(
                image.numel() for submission in self.preview.gpu_retained for image in submission.values())
            self.receipt["gpu_preview_retention_until_app_close"] = True
        (self.output / "receipt.json").write_text(json.dumps(self.receipt, indent=2) + "\n")
        if errors:
            raise RuntimeError("Native camera encoder drain failed: " + str(errors))
        return self.receipt
