"""Author a derived fixed-root USD overlay; no runtime imports or simulation.

Run with declared production Python (pxr available). Preserve original input.
This adapts root authoring for OVPhysX0.6.3, not physics parity qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path

SOURCE_SHA = "03453f4d22eedb40c77cee68aabab241d0c0bf58b824f9c72afb59bef27b812b"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if digest(args.source) != SOURCE_SHA:
        raise RuntimeError("Source preimage changed")
    if args.out.exists() or args.out.with_suffix(".manifest.json").exists():
        raise RuntimeError("Refusing to overwrite an existing derived artifact")
    from pxr import Sdf, Usd, UsdGeom, UsdPhysics
    source = Usd.Stage.Open(str(args.source.resolve()))
    before = UsdGeom.XformCache()
    xforms = {str(pr.GetPath()): tuple(float(v) for row in before.GetLocalToWorldTransform(pr) for v in row)
              for pr in source.Traverse() if pr.IsA(UsdGeom.Xformable)}
    layer = Sdf.Layer.CreateNew(str(args.out.resolve()))
    layer.subLayerPaths = [str(args.source.resolve())]
    stage = Usd.Stage.Open(layer)
    edits = []
    for side in ["Left", "Right"]:
        base_path = f"/World/{side}Piper/Geometry/world/base_link"
        joint_path = f"/World/{side}Piper/Physics/world_to_base_link"
        base = stage.GetPrimAtPath(base_path)
        joint = stage.GetPrimAtPath(joint_path)
        root = UsdPhysics.ArticulationRootAPI(base)
        if not root or not joint.IsA(UsdPhysics.FixedJoint):
            raise RuntimeError("Missing exact original root/world joint")
        b0 = [str(x) for x in joint.GetRelationship("physics:body0").GetTargets()]
        b1 = [str(x) for x in joint.GetRelationship("physics:body1").GetTargets()]
        if b0 != [f"/World/{side}Piper"] or b1 != [base_path]:
            raise RuntimeError(f"Unexpected world anchor relationships: {b0}, {b1}")
        removed = Sdf.TokenListOp()
        removed.deletedItems = ["PhysicsArticulationRootAPI", "PhysxArticulationAPI"]
        base.SetMetadata("apiSchemas", removed)
        added = Sdf.TokenListOp()
        added.prependedItems = ["PhysicsArticulationRootAPI", "PhysxArticulationAPI"]
        joint.SetMetadata("apiSchemas", added)
        # An empty side explicitly denotes world; the non-rigid namespace Xform
        # is not a native static body. Fixed-base root frames are ignored by
        # this parser, and the existing root-link world pose remains unchanged.
        joint.GetRelationship("physics:body0").SetTargets([])
        moved = {}
        for attribute in base.GetAttributes():
            if attribute.GetName().startswith("physxArticulation:"):
                value = attribute.Get()
                if value is not None:
                    joint.CreateAttribute(attribute.GetName(), attribute.GetTypeName(),
                                          custom=attribute.IsCustom()).Set(value)
                    moved[attribute.GetName()] = str(value)
        edits.append(dict(old_root=base_path, new_root=joint_path,
                          original_body0=b0, original_body1=b1,
                          derived_body0=[], derived_body1=b1,
                          articulation_attributes=moved))
    layer.Save()
    reloaded = Usd.Stage.Open(str(args.out.resolve()))
    after = UsdGeom.XformCache()
    for path, matrix in xforms.items():
        current = tuple(float(v) for row in after.GetLocalToWorldTransform(reloaded.GetPrimAtPath(path)) for v in row)
        if current != matrix:
            raise RuntimeError(f"Authored initial world transform changed: {path}")
    roots = [str(pr.GetPath()) for pr in reloaded.Traverse() if pr.HasAPI(UsdPhysics.ArticulationRootAPI)]
    expected = [e["new_root"] for e in edits]
    if roots != expected:
        raise RuntimeError(f"Unexpected derived root inventory: {roots}")
    manifest = dict(schema="live30_ovphysx_fixedbase_overlay_v1", source=str(args.source.resolve()),
                    source_sha256=SOURCE_SHA, overlay=str(args.out.resolve()),
                    overlay_sha256=digest(args.out), overlay_only=True,
                    sdk_source_commit="da950a3537927784951853c66618036f332ca0ce",
                    edits=edits, initial_world_transforms_unchanged=len(xforms),
                    articulation_roots=roots, fixed_base_runtime_verified=False,
                    canonical_physics_parity_verified=False, physical=False,
                    scope="Root-authoring adaptation to fixed-base intent; no new constraint, no geometry/drive/source edits")
    args.out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2))
    if digest(args.source) != SOURCE_SHA:
        raise RuntimeError("Original bytes changed during authoring")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
