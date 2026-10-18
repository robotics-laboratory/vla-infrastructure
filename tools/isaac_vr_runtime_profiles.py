"""Explicit opt-in launch compositions for the shared VR control loop.

These names reproduce experiment settings, not their historical throughput or
qualification. ``selected`` continues to use the maintained selected composition.
"""

from __future__ import annotations

from copy import deepcopy


MASTER_COMMIT = "beaedfd1116577fd4d8026232cfb96cba0b030fa"
RUNTIME_NAMES = ("selected", "master", "native-sync", "native-event", "native-proof", "native-live")
_EXPERIMENT = "docs/experiments/20261009_live_camera_recording_30hz/ARCHITECTURE_OVERVIEW.md"
_NATIVE_MEDIA = {
    "capture": "callback", "preview": True, "witness": False, "fast": True,
    "preview_transport": "cuda", "source_proof": False, "bind_sources": False,
    "proof_compact": False, "proof_clock_only": False, "attribute_probe": False,
    "attribute_only": False, "identity_only": False, "cache_helpers": False,
}
_VARIANTS = {
    "native-sync": (5, {}),
    "native-event": (6, {"preview_transport": "cuda-event"}),
    "native-proof": (7, {
        "preview_transport": "cuda-event", "source_proof": True, "bind_sources": True,
    }),
    "native-live": (8, {
        "preview_transport": "cuda-event", "source_proof": True, "bind_sources": True,
        "proof_compact": True, "proof_clock_only": True, "attribute_probe": True,
        "attribute_only": True, "identity_only": True, "cache_helpers": True,
    }),
}


def load_runtime_profile(name: str) -> dict:
    """Return an independent, JSON-serializable profile without importing Kit."""
    if name not in RUNTIME_NAMES:
        raise ValueError(f"Unknown VR runtime {name!r}; choose from {', '.join(RUNTIME_NAMES)}")
    profile = dict(name=name, native=name in _VARIANTS, device=None, media={},
                   early_subscribe=False, overview=None, provenance={}, limitations=[])
    if name == "selected":
        profile["provenance"] = {"composition": "configs/isaac61_vr_runtime.yaml"}
    elif name == "master":
        profile["provenance"] = {"commit": MASTER_COMMIT, "dispatch": "exact_clean_checkout"}
        profile["limitations"] = ["Historical source; current runtime changes are excluded."]
    else:
        overview, overrides = _VARIANTS[name]
        media = {**_NATIVE_MEDIA, **overrides}
        profile.update(device="cpu", media=media, overview=overview,
                       early_subscribe=media["preview_transport"] == "cuda-event")
        profile["provenance"] = {"experiment": _EXPERIMENT, "section": overview,
                                 "physics": "main_kit_native_cpu", "capture": "main_kit_callback"}
        profile["limitations"] = [
            "Experimental opt-in; no selected-profile promotion or gate acceptance.",
            "Historical no-Quest throughput is not a current performance guarantee.",
            "Quest presentation and physical source qualification require separate evidence.",
        ]
        if profile["early_subscribe"]:
            profile["limitations"].append(
                "Preview copy ACK uses an exclusive, version-coupled CUPTI subscription; it is not display ACK."
            )
        if not media["source_proof"]:
            profile["limitations"].append("Exact rendered observation identity and geometry are not checked.")
        elif media["identity_only"]:
            profile["limitations"].append("Per-frame identity is checked; full geometry comparison requires native-proof.")
    return deepcopy(profile)
