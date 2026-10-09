"""6.1 diagnostic only: three existing camera prims, native atlas vs separate RPs.

Import is CPU-only; instantiate AFTER SimulationApp. Run in a fresh diagnostic
scene with camera prims only, not simultaneously with the three old Camera RPs.
Call capture() after the existing app/control pump; never pump from this helper.
Returned GPU buffer is owned until release(); no raw pixels are staged to host.
Sequence counts fetches, not renderer source frames. Decode moving witnesses and
bind observed source phase to state/action history before claiming fresh RGB.
"""

from pathlib import Path
import hashlib
import math
import time

ROLES = ("left_wrist", "right_wrist", "scene")
AUDITED = {
    "isaacsim.sensors.experimental.rtx/isaacsim/sensors/experimental/rtx/impl/tiled_camera_sensor.py": "4d5d09a90d440f2154dad66f26ec3868318712b0a5f9703c762406205b5482a9",
    "isaacsim.core.experimental.objects/isaacsim/core/experimental/objects/impl/camera.py": "c96acc6a794a3b9dfaaaaa76d4975130b3b5dfeed6f4259302fca97ce5bfaa0c",
}


def source_guard(extension_root):
    receipts = []
    for relative, expected in AUDITED.items():
        path = Path(extension_root) / relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected is not None and digest != expected:
            raise RuntimeError(f"Audited source changed: {path}")
        receipts.append(dict(path=str(path), sha256=digest, expected=expected))
    return receipts


def camera_signature(stage, paths):
    from pxr import UsdGeom

    signatures = {}
    for path in paths:
        prim = stage.GetPrimAtPath(path)
        if not prim.IsA(UsdGeom.Camera):
            raise ValueError(f"Existing Camera required: {path}")
        values = {
            str(attr.GetName()): str(attr.Get())
            for attr in prim.GetAttributes()
            if not str(attr.GetName()).startswith("_replicator:")
        }
        values["schemas"] = list(prim.GetAppliedSchemas())
        values["parent"] = str(prim.GetParent().GetPath())
        values["local_matrix"] = str(UsdGeom.Xformable(prim).GetLocalTransformation())
        signatures[path] = values
    return signatures


class CudaSubview:
    """PyNvVideoCodec 2.2.3 sample protocol; pitch acceptance needs GPU testing.

    cuda() returns an object with __cuda_array_interface__, not a dict. The
    allocation owner must survive encoder input consumption; no CPU copy here.
    """

    def __init__(self, owner, ptr, width, height, pitch):
        self.owner = owner
        self.__cuda_array_interface__ = dict(
            shape=(height, width, 4),
            strides=(pitch, 4, 1),
            data=(int(ptr), False),
            typestr="|u1",
            version=3,
        )

    def cuda(self):
        return self


class ThreeCameraProbe:
    """Thin probe over upstream camera/Replicator APIs, with owned GPU outputs.

    mode: sensor -> public TiledCameraSensor.get_data(tiled=True,out=...).
          tiled -> direct rep.create.render_product_tiled; no optics editing.
          separate -> three stock products as comparison.
    payload: rgba -> owned CUDA arrays; h264 -> stock compressed packet bytes.
    H264 atlas is ONE 1920x1200 stream; crop into roles after decode. It is not
    three encoder sessions and must be measured independently from three RPs.
    """

    def __init__(
        self,
        camera_paths,
        *,
        mode="sensor",
        payload="rgba",
        width=960,
        height=600,
        extension_root=None,
        reject_existing_products=True,
    ):
        import numpy as np
        import omni.replicator.core as rep
        import omni.usd
        from pxr import Sdf, Usd, UsdGeom, UsdRender

        if tuple(camera_paths) != ROLES or len(set(camera_paths.values())) != 3:
            raise ValueError("Ordered, unique left_wrist/right_wrist/scene paths required")
        if mode not in ("sensor", "tiled", "separate") or payload not in ("rgba", "h264"):
            raise ValueError("Unknown mode/payload")
        self.paths, self.mode, self.payload = dict(camera_paths), mode, payload
        self.width, self.height = int(width), int(height)
        self.sequence, self.busy, self.closed = 0, False, False
        self.buffers, self.products, self.annotators, self.handles = {}, [], [], []
        self.sensor = None
        self.completions, self.subscriptions = {}, []
        self.stage = omni.usd.get_context().get_stage()
        paths = list(self.paths.values())
        self.before = camera_signature(self.stage, paths)
        original_attrs = {
            p: {str(a.GetName()): a.Get() for a in self.stage.GetPrimAtPath(p).GetAttributes()}
            for p in paths
        }
        self.sources = source_guard(
            extension_root
            or "/data/vla-infrastructure/isaac61_production/env/lib/python3.12/site-packages/isaacsim/exts"
        )
        if reject_existing_products:
            for prim in self.stage.Traverse():
                if prim.IsA(UsdRender.Product) and set(
                    map(str, prim.GetRelationship("camera").GetTargets())
                ) & set(paths):
                    raise RuntimeError(
                        f"Old camera RP would contaminate comparison: {prim.GetPath()}"
                    )
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            if mode == "sensor":
                from isaacsim.core.experimental.objects import Camera
                from isaacsim.sensors.experimental.rtx import TiledCameraSensor

                for path in paths:
                    camera = UsdGeom.Camera(self.stage.GetPrimAtPath(path))
                    ha, va = (
                        camera.GetHorizontalApertureAttr().Get(),
                        camera.GetVerticalApertureAttr().Get(),
                    )
                    if not np.isclose(va, ha * self.height / self.width, rtol=1e-5, atol=1e-7):
                        raise RuntimeError(
                            f"Native sensor would change vertical aperture at {path}; use mode=tiled"
                        )
                wrapped = Camera(paths, reset_xform_op_properties=False)
                self.sensor = TiledCameraSensor(
                    wrapped,
                    resolution=(self.height, self.width),
                    annotators=["rgba"] if payload == "rgba" else [],
                )
                self.products = [str(self.sensor.render_product.GetPath())]
            elif mode == "tiled":
                product = rep.create.render_product_tiled(
                    paths, (self.width, self.height), name="Live30DiagnosticAtlas"
                )
                self.products, self.handles = [product.path], [product]
            else:
                self.handles = [
                    rep.create.render_product(
                        path, (self.width, self.height), name=f"Live30Diagnostic_{role}"
                    )
                    for role, path in self.paths.items()
                ]
                self.products = [product.path for product in self.handles]
        # Stock RP creation authors exposure defaults on camera0. Restore source
        # camera opinions explicitly; this is a probe-only session-layer change.
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            for path in paths:
                prim = self.stage.GetPrimAtPath(path)
                prim.SetMetadata(
                    "apiSchemas", Sdf.TokenListOp.CreateExplicit(self.before[path]["schemas"])
                )
                for attribute in list(prim.GetAttributes()):
                    name = str(attribute.GetName())
                    if name not in original_attrs[path]:
                        prim.RemoveProperty(name)
                    elif attribute.Get() != original_attrs[path][name]:
                        if original_attrs[path][name] is None:
                            attribute.Clear()
                        else:
                            attribute.Set(original_attrs[path][name])
        self.after = camera_signature(self.stage, paths)
        if self.before != self.after:
            self.close()
            changes = {
                p: {
                    k: [self.before[p].get(k), self.after[p].get(k)]
                    for k in set(self.before[p]) | set(self.after[p])
                    if self.before[p].get(k) != self.after[p].get(k)
                }
                for p in paths
            }
            raise RuntimeError(
                f"Constructing the probe changed camera optics/transform/schema: {changes}"
            )
        self.order = []
        for path in self.products:
            prim = self.stage.GetPrimAtPath(path)
            targets = list(map(str, prim.GetRelationship("camera").GetTargets()))
            self.order.extend(targets)
        if set(self.order) != set(paths) or len(self.order) != 3:
            self.close()
            raise RuntimeError(f"Render-product camera routing wrong: {self.order}")
        self.role_indices = {role: self.order.index(path) for role, path in self.paths.items()}
        columns = math.ceil(math.sqrt(3))
        self.atlas_shape = (2 * self.height, columns * self.width, 4)
        if payload == "h264" or mode != "sensor":
            for product in self.products:
                annotator = rep.AnnotatorRegistry.get_annotator(
                    "LdrColor" if payload == "h264" else "rgb",
                    device="cpu" if payload == "h264" else "cuda",
                    init_params={"compression": "h264"} if payload == "h264" else {},
                )
                annotator.attach(product)
                self.annotators.append(annotator)
        self._observe_completions()
        self.manifest = dict(
            mode=mode,
            payload=payload,
            camera_paths=self.paths,
            observed_camera_order=self.order,
            role_indices=self.role_indices,
            sensor_resolution_hw=[self.height, self.width],
            atlas_shape_hwc=self.atlas_shape,
            padding_tiles=1 if mode != "separate" else 0,
            render_products=self.products,
            camera_signatures=self.before,
            source_receipts=self.sources,
            raw_host_staging=False,
            source_frame_identity_proven=False,
        )

    def _observe_completions(self):
        import carb.eventdispatcher
        import omni.hydratexture

        handles = [self.sensor._hydra_texture] if self.sensor else self.handles
        for product in handles:
            texture = getattr(product, "hydra_texture", None)
            if texture is None or not hasattr(texture, "get_frame_info"):
                continue

            def done(event, texture=texture, path=product.path):
                result = event.payload.get("result_handle")
                if result is not None:
                    value = texture.get_frame_info(result)
                    self.completions[path] = dict(
                        host_monotonic_ns=time.monotonic_ns(),
                        frame_number=value.get("frame_number"),
                        device_mask=value.get("device_mask"),
                        subframe_count=value.get("subframe_count"),
                        pixel_binding_proven=False,
                    )

            subscription = carb.eventdispatcher.get_eventdispatcher().observe_event(
                observer_name=f"Live30Atlas:{id(self)}:{product.path}",
                event_name=omni.hydratexture.GLOBAL_EVENT_DRAWABLE_CHANGED,
                filter=texture.get_event_key(),
                on_event=done,
            )
            self.subscriptions.append(subscription)

    def capture(self, *, producer_metadata=None):
        import warp as wp

        if self.closed or self.busy:
            raise RuntimeError("Closed probe or previous GPU frame not released")
        started = time.perf_counter_ns()
        arrays, info = {}, {}
        if self.payload == "h264":
            import numpy as np

            for index, annotator in enumerate(self.annotators):
                value = annotator.get_data(do_array_copy=True)
                if isinstance(value, dict):
                    info[str(index)] = value.get("info", {})
                    value = value.get("data")
                if value is None or not isinstance(value, np.ndarray) or not value.size:
                    return None
                if value.dtype != np.uint8 or value.ndim != 1:
                    raise RuntimeError("Expected flat compressed uint8 bytes")
                arrays[str(index)] = value.tobytes()
        else:
            if self.mode == "sensor":
                # Warm-up obtains native device/shape; subsequent fetches reuse out.
                value, metadata = self.sensor.get_data(
                    "rgba", tiled=True, out=self.buffers.get("atlas")
                )
                if value is None:
                    return None
                info["atlas"] = metadata
                if "atlas" not in self.buffers:
                    self._check_array(value, self.atlas_shape)
                    self.buffers["atlas"] = wp.empty_like(value)
                    wp.copy(self.buffers["atlas"], value)
                arrays["atlas"] = self.buffers["atlas"]
            else:
                for index, annotator in enumerate(self.annotators):
                    value = annotator.get_data(device="cuda", do_array_copy=False)
                    if isinstance(value, dict):
                        info[str(index)] = value.get("info", {})
                        value = value.get("data")
                    if value is None or getattr(value, "size", 0) == 0:
                        return None
                    shape = (
                        (self.height, self.width, 4)
                        if self.mode == "separate"
                        else self.atlas_shape
                    )
                    self._check_array(value, shape)
                    value = value.reshape(shape)
                    key = str(index)
                    if key not in self.buffers:
                        self.buffers[key] = wp.empty_like(value)
                    wp.copy(self.buffers[key], value)
                    arrays[key] = self.buffers[key]
            for device in {array.device for array in arrays.values()}:
                wp.synchronize_device(device)  # conservative copy-completion baseline
        self.sequence += 1
        self.busy = True
        return dict(
            fetch_sequence=self.sequence,
            host_monotonic_ns=time.monotonic_ns(),
            fetch_ns=time.perf_counter_ns() - started,
            arrays=arrays,
            annotator_info=info,
            producer_metadata=producer_metadata,
            render_completions=dict(self.completions),
            source_frame_identity_proven=False,
        )

    @staticmethod
    def _check_array(value, shape):
        import warp as wp

        if not isinstance(value, wp.array) or not value.device.is_cuda or value.dtype != wp.uint8:
            raise RuntimeError("Expected native CUDA uint8 Warp output; no host promotion accepted")
        if value.size != math.prod(shape):
            raise RuntimeError(f"Output shape/size differs from configured atlas: {value.shape}")

    def cuda_views(self, capture):
        if self.payload != "rgba" or not self.busy or capture["fetch_sequence"] != self.sequence:
            raise RuntimeError("Current owned raw GPU capture required")
        views = {}
        for role, index in self.role_indices.items():
            if self.mode == "separate":
                array = capture["arrays"][str(index)]
                offset, pitch = 0, self.width * 4
            else:
                array = next(iter(capture["arrays"].values()))
                pitch = self.atlas_shape[1] * 4
                offset = (index // 2) * self.height * pitch + (index % 2) * self.width * 4
            views[role] = CudaSubview(array, array.ptr + offset, self.width, self.height, pitch)
        return views

    def release(self, capture):
        if not self.busy or capture["fetch_sequence"] != self.sequence:
            raise RuntimeError("Stale/double release")
        self.busy = False

    def close(self):
        if self.closed:
            return
        self.subscriptions.clear()
        for annotator, product in zip(self.annotators, self.products):
            annotator.detach(product)
        if self.sensor is not None:
            self.sensor._invalidate_sensor()  # audited teardown, no installed source patch
        else:
            for product in self.handles:
                product.destroy()
        self.closed = True
