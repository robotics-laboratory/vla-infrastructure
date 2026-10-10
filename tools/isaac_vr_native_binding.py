"""Pure diagnostic join of rendered publications to immutable canonical observations.

No HDF, SDK, label/action mutation, pixel readback, or lag prediction. One observer
belongs to one reset epoch; the caller persists returned bindings and receipts.
"""
from collections import OrderedDict
from copy import deepcopy
from numbers import Integral

ROLES = ("left_wrist", "right_wrist", "scene")
TOKEN_FIELDS = (
    "capture_sequence", "physics_step", "state_generation", "reset_epoch",
    "scene_state_snapshot_id", "scene_state_snapshot_sha256",
)


def _integer(value, name):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f"Invalid nonnegative integer {name}")
    return int(value)


class NativeSourceBinding:
    def __init__(self, capacity=256, *, clock_only=False, attribute_only=False, identity_only=False):
        if attribute_only and not clock_only:
            raise ValueError("Attribute camera proof requires clock-only coverage")
        if identity_only and not attribute_only:
            raise ValueError("Identity-only proof requires native publication attribute")
        self.proof_scope = ("publication_attribute" if identity_only else
                            "publication_attribute_camera" if attribute_only else
                            "publication_clock_camera" if clock_only else "full_native_body_camera")
        self.capacity = _integer(capacity, "capacity")
        if not self.capacity:
            raise ValueError("History capacity must be positive")
        self._history = OrderedDict()
        self._current = None
        self._packet = -1
        self._last_publication = None
        self._last_source_step = None
        self._counts = dict(registered=0, bindings=0, duplicates=0, evictions=0,
                            evicted_unbound=0)

    def register(self, token):
        """Freeze a canonical token; return any evicted identity for caller logging."""
        value = {name: getattr(token, name) for name in TOKEN_FIELDS}
        for name in TOKEN_FIELDS[:4]:
            value[name] = _integer(value[name], name)
        if value["state_generation"] != value["physics_step"]:
            raise ValueError("Canonical state generation differs from physics step")
        if not isinstance(value["scene_state_snapshot_id"], str) or not value["scene_state_snapshot_id"]:
            raise ValueError("Missing canonical snapshot identity")
        digest = value["scene_state_snapshot_sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid canonical snapshot SHA256")
        key = (value["reset_epoch"], value["physics_step"])
        if self._current is not None:
            if value == self._current:
                return None
            if value["reset_epoch"] != self._current["reset_epoch"]:
                raise ValueError("Reset epoch boundary requires a new binding observer")
            if value["capture_sequence"] != self._current["capture_sequence"] + 1:
                raise ValueError("Canonical capture sequence gap or regression")
            if value["physics_step"] <= self._current["physics_step"]:
                raise ValueError("Canonical physics step is ambiguous or regressed")
        if key in self._history:
            raise ValueError("Ambiguous canonical observation identity")
        eviction = None
        if len(self._history) == self.capacity:
            _, old = self._history.popitem(last=False)
            self._counts["evictions"] += 1
            self._counts["evicted_unbound"] += old["bindings"] == 0
            eviction = dict(kind="binding_history_eviction", token=dict(old["token"]),
                            bindings=old["bindings"], dataset_admissible=False)
        self._history[key] = dict(token=value, bindings=0)
        self._current = value
        self._counts["registered"] += 1
        return eviction

    def bind(self, packet_ordinal, proofs):
        """Bind an encoded triplet ordinal to its actual historical observation."""
        ordinal = _integer(packet_ordinal, "packet ordinal")
        if self._current is None:
            raise ValueError("Register the current canonical observation before binding")
        if ordinal != self._packet + 1:
            raise ValueError("Packet ordinal gap or regression")
        if set(proofs) != set(ROLES):
            raise ValueError("Binding requires exactly the three camera roles")
        identities, geometry, optical, frame_ids = [], {}, {}, {}
        for role in ROLES:
            proof = proofs[role]
            if not isinstance(proof, dict) or proof.get("role") != role:
                raise ValueError(f"Source proof role mismatch: {role}")
            scope = proof.get("proof_scope", "full_native_body_camera")
            if scope != self.proof_scope:
                raise ValueError(f"Source proof scope mismatch: {role}")
            if scope == "publication_attribute":
                if (proof.get("history_join_matched") is not True or
                        proof.get("geometry_matched") is not False or
                        proof.get("camera_geometry_checked") is not False):
                    raise ValueError(f"Source identity coverage mismatch: {role}")
            elif proof.get("geometry_matched") is not True:
                raise ValueError(f"Source geometry is not matched: {role}")
            if proof.get("failed_paths") or proof.get("unresolved"):
                raise ValueError(f"Source proof is unresolved: {role}")
            count = _integer(proof.get("compared_bodies"), "compared body count")
            if (scope == "full_native_body_camera" and count == 0
                    or scope in ("publication_clock_camera", "publication_attribute_camera", "publication_attribute") and
                    (count != 0 or proof.get("body_geometry_checked") is not False)):
                raise ValueError(f"Source proof body coverage mismatch: {role}")
            if scope in ("publication_attribute_camera", "publication_attribute") and (
                    proof.get("attribute_clock_matched") is not True or
                    _integer(proof.get("attribute_publication_id"), "attribute publication") !=
                    _integer(proof.get("publication_id"), "publication")):
                raise ValueError(f"Native attribute source identity mismatch: {role}")
            identity = tuple(_integer(proof.get(name), name)
                             for name in ("publication_id", "reset_epoch", "physics_step"))
            if not identity[0]:
                raise ValueError("Publication identity must be positive")
            identities.append(identity)
            if not isinstance(proof.get("frame_identifier"), dict) or not proof["frame_identifier"]:
                raise ValueError(f"Missing native result identity: {role}")
            frame_ids[role] = deepcopy(proof["frame_identifier"])
            geometry[role] = {key: proof[key] for key in
                              ("compared_bodies", "body_matrix_max_error", "camera_matrix_max_error")
                              if key in proof}
            optical[role] = deepcopy(proof.get("optical"))
        if len(set(identities)) != 1:
            raise ValueError("Camera roles disagree on rendered publication/epoch/step")
        publication, epoch, step = identities[0]
        if epoch != self._current["reset_epoch"] or step > self._current["physics_step"]:
            raise ValueError("Rendered source crosses epoch/current-time boundary")
        entry = self._history.get((epoch, step))
        if entry is None:
            raise ValueError("Rendered source has no exact retained canonical observation")
        if self._last_publication is not None:
            if publication < self._last_publication or step < self._last_source_step:
                raise ValueError("Rendered publication or physical source regressed")
            if (publication == self._last_publication) != (step == self._last_source_step):
                raise ValueError("Publication identity changed its physical source")
        actual = entry["token"]
        duplicate = entry["bindings"] > 0
        requested = [value is not None for value in optical.values()]
        optical_field = ("optical_and_source_matched" if self.proof_scope == "publication_attribute"
                         else "optical_and_geometry_matched")
        optical_passed = all(requested) and all(
            isinstance(value, dict) and value.get(optical_field) is True
            for value in optical.values())
        row = dict(
            schema="native_rendered_source_binding_v1", packet_ordinal=ordinal,
            proof_scope=self.proof_scope,
            body_geometry_checked=self.proof_scope == "full_native_body_camera",
            camera_geometry_checked=self.proof_scope != "publication_attribute",
            source_identity_matched=True,
            current_capture_sequence=self._current["capture_sequence"],
            actual_capture_sequence=actual["capture_sequence"], publication_id=publication,
            reset_epoch=epoch, physics_step=step, state_generation=actual["state_generation"],
            scene_state_snapshot_id=actual["scene_state_snapshot_id"],
            scene_state_snapshot_sha256=actual["scene_state_snapshot_sha256"],
            observed_lag_physics_steps=self._current["physics_step"] - step,
            duplicate_source=duplicate, source_binding_ordinal=entry["bindings"],
            native_result_identifiers=frame_ids,
            camera_geometry_quality=dict(checked=self.proof_scope != "publication_attribute",
                                         matched=None if self.proof_scope == "publication_attribute" else True,
                                         roles=geometry),
            optical_quality=("not_requested" if not any(requested) else
                             "passed" if optical_passed else "failed"),
            optical_quality_passed=optical_passed, optical_alignment_proven=False,
            dataset_admissible=False,
        )
        # Commit only after every check; failed attempts cannot consume an ordinal.
        entry["bindings"] += 1
        self._counts["bindings"] += 1
        self._counts["duplicates"] += duplicate
        self._packet, self._last_publication, self._last_source_step = ordinal, publication, step
        return row

    def receipt(self):
        return dict(
            **self._counts, retained=len(self._history), capacity=self.capacity,
            proof_scope=self.proof_scope,
            body_geometry_checked=self.proof_scope == "full_native_body_camera",
            camera_geometry_checked=self.proof_scope != "publication_attribute",
            unbound_retained=[dict(entry["token"]) for entry in self._history.values()
                              if not entry["bindings"]],
            dataset_admissible=False, optical_alignment_proven=False,
        )
