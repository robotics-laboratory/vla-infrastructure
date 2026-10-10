"""Bounded observational probe for native USD/SD/Hydra event association.

No casts/dereferences: SD renderResults and NEW_FRAME.results are numeric receipts
only. Drawable result_handle is used solely with that texture's public methods,
inside its immediate observer. Different native pointer types never interchange.
Scalar joins and resource retention are diagnostic; they do not prove pixel
identity, render/state alignment, or presentation of a recorded frame.

Instantiate on the Kit owner thread after products exist; register before warmup.
Pass {role: (existing_product_path, existing_hydra_texture)}. Feed the existing
NativeResultConsumer result to observe_sd(result). close() stops observation but
intentionally keeps held providers/resources: anchor the probe until
SimulationApp.close() returns. Histories and managed holders have finite budgets.
This module was only syntax checked by its author; parent owns GPU experiments.
"""

from collections import deque
import threading
import time


def _scalar(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (tuple, list)):
        return [_scalar(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _scalar(item) for key, item in value.items()}
    if hasattr(value, "tolist"):
        return _scalar(value.tolist())
    if hasattr(value, "name") and hasattr(value, "value"):
        return {"enum_name": str(value.name), "enum_value": _scalar(value.value)}
    # Never retain opaque metadata/capsules/resource wrappers in event receipts.
    return {"unserialized_type": type(value).__name__}


def _event_value(event, key):
    try:
        return event.get(key)
    except AttributeError:
        try:
            return event[key]
        except (KeyError, IndexError):
            return None


class ManagedEventProbe:
    def __init__(self, products_by_role, *, max_events_per_stream=2048,
                 retain_managed=False, max_managed_per_role=300):
        import carb.eventdispatcher
        import omni.hydratexture
        import omni.usd

        if max_events_per_stream < 1 or max_managed_per_role < 1:
            raise ValueError("Probe histories and resource retention must be bounded")
        self.products = dict(products_by_role)
        self.lock = threading.RLock()
        self.closed = False
        self.errors = []
        self.counters = {name: 0 for name in ("new_frame", "drawable", "sd")}
        self.dropped_history = dict.fromkeys(self.counters, 0)
        self.history = {name: deque(maxlen=max_events_per_stream) for name in self.counters}
        self.holders = {role: [] for role in self.products}
        self.retain_managed = retain_managed
        self.max_managed_per_role = max_managed_per_role
        self.subscriptions = []
        dispatcher = carb.eventdispatcher.get_eventdispatcher()
        context = omni.usd.get_context()
        try:
            self.subscriptions.append(dispatcher.observe_event(
                observer_name="native_managed_probe_new_frame_immediate",
                event_name=context.stage_rendering_event_name(
                    omni.usd.StageRenderingEventType.NEW_FRAME, True
                ),
                on_event=self._on_new_frame,
            ))
            for role, (_, texture) in self.products.items():
                self.subscriptions.append(dispatcher.observe_event(
                    observer_name=f"native_managed_probe_drawable_{role}",
                    event_name=omni.hydratexture.GLOBAL_EVENT_DRAWABLE_CHANGED,
                    filter=texture.get_event_key(),
                    on_event=lambda event, role=role: self._on_drawable(role, event),
                ))
        except BaseException:
            self.close()
            raise

    def _append(self, stream, receipt):
        self.counters[stream] += 1
        receipt["observer_sequence"] = self.counters[stream]
        receipt["observer_monotonic_ns"] = time.perf_counter_ns()
        queue = self.history[stream]
        if len(queue) == queue.maxlen:
            self.dropped_history[stream] += 1
        queue.append(receipt)

    def _on_new_frame(self, event):
        with self.lock:
            if self.closed:
                return
            try:
                fields = (
                    "viewport_handle", "swh_frame_number", "results",
                    "product_path_handle", "frame_number", "render_status", "progression",
                )
                receipt = {key: _scalar(_event_value(event, key)) for key in fields}
                receipt["results_native_type"] = "omni::usd::hydra::HydraRenderProduct*"
                receipt["pointer_use"] = "opaque integer equality only; never dereferenced"
                self._append("new_frame", receipt)
            except Exception as error:
                self.errors.append({"stream": "new_frame", "error": str(error)})

    def _on_drawable(self, role, event):
        with self.lock:
            if self.closed:
                return
            try:
                expected_path, texture = self.products[role]
                # Only the current immediate observer's result_handle is consumed.
                result_handle = event["result_handle"]
                info = texture.get_frame_info(result_handle, include_aov_list=True)
                aovs = texture.get_aov_info(result_handle, "LdrColor", include_texture=True)
                fields = (
                    "frame_number", "swh_frame_number", "resolution", "subframe_count",
                    "progression", "device_mask", "view", "projection", "fps", "aovs",
                )
                receipt = {
                    "role": role, "expected_render_product": str(expected_path),
                    "actual_render_product": texture.get_render_product_path(),
                    "viewport_handle": _scalar(_event_value(event, "viewport_handle")),
                    "presentation_key": _scalar(_event_value(event, "presentation_key")),
                    "result_handle_diagnostic": int(result_handle),
                    "result_handle_native_type": "omni::usd::hydra::ViewportHydraRenderResults*",
                    "frame_info": {key: _scalar(info.get(key)) for key in fields},
                    "ldr_available": bool(aovs),
                    "managed_retention_requested": self.retain_managed,
                    "sd_join_proven": False,
                    "pixel_identity_proven": False,
                }
                if aovs:
                    texture_info = aovs[0]["texture"]
                    receipt["ldr_texture_info"] = {
                        key: _scalar(texture_info.get(key))
                        for key in ("resolution", "format", "device_mask")
                    }
                if self.retain_managed:
                    if not aovs:
                        raise RuntimeError("LdrColor resource unavailable")
                    if len(self.holders[role]) >= self.max_managed_per_role:
                        raise RuntimeError("Finite managed resource retention budget exhausted")
                    import omni.ui as ui
                    holder = ui.ImageProvider(name=f"NativeManagedHeld_{role}_{len(self.holders[role])}")
                    # Retain the holder before any native call can fail partially.
                    self.holders[role].append(holder)
                    # Explicit API retains the GpuResource on success. Key zero locks
                    # current content as in upstream OverlayViewportDisplayDelegate.
                    holder.set_image_data(texture_info["rp_resource"], presentation_key=0)
                    receipt["managed_reference_valid"] = bool(holder.is_reference_valid)
                    receipt["managed_resource_available"] = holder.get_managed_resource() is not None
                    receipt["held_presentation_key"] = 0
                    receipt["holder_index"] = len(self.holders[role]) - 1
                    if not (receipt["managed_reference_valid"] and receipt["managed_resource_available"]):
                        raise RuntimeError("Managed ImageProvider did not retain a usable resource")
                self._append("drawable", receipt)
            except Exception as error:
                self.errors.append({"stream": "drawable", "role": role, "error": str(error)})

    def observe_sd(self, result):
        with self.lock:
            if self.closed:
                raise RuntimeError("Managed event probe closed")
            geometry = result.get("result_geometry", {})
            receipt = {
                "role": result["role"], "render_product": result["render_product"],
                "render_results_diagnostic": int(result["render_result_handle_diagnostic"]),
                "frame_identifier": _scalar(result["frame_identifier"]),
                "producer_cuda_stream_diagnostic": int(result["producer_cuda_stream"]),
                "semantic_update_time": _scalar(geometry.get("semantic_update_time")),
                "camera_view": _scalar(geometry.get("camera_view")),
                "camera_projection": _scalar(geometry.get("camera_projection")),
                "camera_resolution": _scalar(geometry.get("camera_resolution")),
                "source_proof": _scalar(result.get("source_proof")),
                "native_type_evidence": "SdOnNewRenderProductFrame selects HydraRenderProduct pointer inputs",
                "pixel_identity_proven": False,
            }
            self._append("sd", receipt)

    def receipt(self):
        """Copy bounded history; evaluate candidate joins without dereferencing pointers."""
        with self.lock:
            histories = {name: list(queue) for name, queue in self.history.items()}
            joins = []
            native_by_pointer = {}
            drawable_by_key = {}
            for native in histories["new_frame"]:
                native_by_pointer.setdefault(native["results"], []).append(native)
            for drawable in histories["drawable"]:
                frame = drawable["frame_info"]
                key = (drawable["role"], drawable["viewport_handle"], frame["frame_number"], frame["swh_frame_number"])
                drawable_by_key.setdefault(key, []).append(drawable)
            for sd in histories["sd"]:
                # Pointer equality is diagnostic and may collide through address reuse.
                # Preserve *all* candidates and report ambiguity; never choose nearest.
                natives = native_by_pointer.get(sd["render_results_diagnostic"], [])
                candidates = []
                for native in natives:
                    keys = (native["viewport_handle"], native["frame_number"], native["swh_frame_number"])
                    if None in keys:
                        continue
                    for drawable in drawable_by_key.get((sd["role"], *keys), []):
                        candidates.append({
                                "new_frame_sequence": native["observer_sequence"],
                                "drawable_sequence": drawable["observer_sequence"],
                                "viewport_frame_swh": list(keys),
                                "sd_identifier_frame_number": sd["frame_identifier"].get("frameNumber"),
                                "sd_identifier_matches_new_swh": sd["frame_identifier"].get("frameNumber") == keys[2],
                                "pixel_identity_proven": False,
                            })
                joins.append({
                    "role": sd["role"], "sd_sequence": sd["observer_sequence"],
                    "pointer_equal_new_frame_candidates": len(natives),
                    "scalar_matching_drawable_candidates": candidates,
                    "ambiguous_or_missing": len(candidates) != 1,
                    "identifier_confirmed_candidates": [item for item in candidates if item["sd_identifier_matches_new_swh"]],
                    "public_scalar_semantics_exactly_proven": False,
                    "pixel_identity_proven": False,
                })
            return {
                "kind": "native_managed_event_probe", "closed": self.closed,
                "counters": dict(self.counters), "dropped_history": dict(self.dropped_history),
                "errors": list(self.errors), "histories": histories, "candidate_joins": joins,
                "held_managed_providers": {role: len(items) for role, items in self.holders.items()},
                "actual_ui_presented": False, "source_binding_proven": False,
                "same_recorded_preview_pixels_proven": False,
                "ownership_lifetime": "Keep probe until SimulationApp.close returns; close only unsubscribes",
            }

    def close(self):
        with self.lock:
            self.closed = True
            self.subscriptions.clear()
            # Histories and ImageProvider holders intentionally survive observer close.
