#!/usr/bin/env python3
"""View M1 interactively or render a headless distal-joint diagnostic."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENE = ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml"
DEFAULT_DIAGNOSTIC_DIR = ROOT / "artifacts/mujoco_wrist_diagnostic"


def _render_wrist_diagnostic(
    mujoco, model, data, scene_path: Path, output_dir: Path
) -> None:
    """Render joint 5/6 sweeps without depending on a desktop display."""

    from PIL import Image, ImageDraw

    output_dir.mkdir(parents=True, exist_ok=True)
    home_id = model.key("home").id
    mujoco.mj_resetDataKeyframe(model, data, home_id)
    mujoco.mj_forward(model, data)
    home_qpos = data.qpos.copy()
    home_rotation = {
        side: data.body(f"{side}_gripper_base").xmat.reshape(3, 3).copy()
        for side in ("left", "right")
    }

    poses: list[tuple[str, str | None, int | None, float]] = [
        ("home", None, None, 0.0),
    ]
    for side in ("left", "right"):
        for joint_index in (5, 6):
            for delta_deg in (-20.0, 20.0):
                poses.append(
                    (
                        f"{side}_joint{joint_index}_{delta_deg:+.0f}deg",
                        side,
                        joint_index,
                        delta_deg,
                    )
                )

    width, height = 640, 480
    scene_option = mujoco.MjvOption()
    scene_option.geomgroup[0] = 0  # collision-only geometry
    scene_option.geomgroup[1] = 1  # rendered robot/task geometry
    report: dict[str, object] = {
        "scene": str(scene_path),
        "camera": "scene",
        "delta_deg": 20.0,
        "poses": [],
    }
    frames: list[Image.Image] = []

    renderer = mujoco.Renderer(model, height=height, width=width)
    try:
        for label, side, joint_index, delta_deg in poses:
            data.qpos[:] = home_qpos
            requested_deg = None
            applied_deg = None
            if side is not None and joint_index is not None:
                joint = model.joint(f"{side}_joint{joint_index}")
                qpos_index = int(joint.qposadr[0])
                requested = float(home_qpos[qpos_index] + math.radians(delta_deg))
                applied = min(max(requested, float(joint.range[0])), float(joint.range[1]))
                data.qpos[qpos_index] = applied
                requested_deg = float(math.degrees(requested))
                applied_deg = float(math.degrees(applied))

            data.qvel[:] = 0.0
            mujoco.mj_forward(model, data)
            renderer.update_scene(data, camera="scene", scene_option=scene_option)
            image = Image.fromarray(renderer.render().copy())
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, width, 30), fill=(0, 0, 0))
            draw.text((10, 8), label, fill=(255, 255, 255))
            image.save(output_dir / f"{label}.png")
            frames.append(image)

            pose_report: dict[str, object] = {"label": label}
            if side is not None:
                rotation = data.body(f"{side}_gripper_base").xmat.reshape(3, 3)
                relative = home_rotation[side].T @ rotation
                cosine = min(1.0, max(-1.0, (float(relative.trace()) - 1.0) / 2.0))
                pose_report.update(
                    {
                        "side": side,
                        "joint": joint_index,
                        "requested_joint_deg": requested_deg,
                        "applied_joint_deg": applied_deg,
                        "gripper_rotation_from_home_deg": float(
                            math.degrees(math.acos(cosine))
                        ),
                    }
                )
            report["poses"].append(pose_report)
    finally:
        renderer.close()

    sheet = Image.new("RGB", (width * 3, height * 3), (20, 20, 20))
    for index, frame in enumerate(frames):
        sheet.paste(frame, ((index % 3) * width, (index // 3) * height))
    sheet_path = output_dir / "wrist_joint_diagnostic.png"
    sheet.save(sheet_path)
    (output_dir / "wrist_joint_diagnostic.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Saved headless wrist diagnostic to {sheet_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument(
        "--headless-wrist-diagnostic",
        nargs="?",
        type=Path,
        const=DEFAULT_DIAGNOSTIC_DIR,
        metavar="OUTPUT_DIR",
        help=(
            "render home and +/-20 degree joint 5/6 poses with EGL; "
            "defaults to artifacts/mujoco_wrist_diagnostic"
        ),
    )
    args = parser.parse_args()

    os.environ["MUJOCO_GL"] = (
        "egl" if args.headless_wrist_diagnostic is not None else "glfw"
    )
    import mujoco

    model = mujoco.MjModel.from_xml_path(str(args.scene.resolve()))
    data = mujoco.MjData(model)
    if args.headless_wrist_diagnostic is not None:
        _render_wrist_diagnostic(
            mujoco,
            model,
            data,
            args.scene.resolve(),
            args.headless_wrist_diagnostic.resolve(),
        )
        return

    import mujoco.viewer

    home_id = model.key("home").id
    mujoco.mj_resetDataKeyframe(model, data, home_id)
    mujoco.mj_forward(model, data)
    print(f"Opening {args.scene.resolve()} at keyframe 'home'.")
    print("Use Space to pause/run; close the viewer window to exit.")
    mujoco.viewer.launch(model, data)


if __name__ == "__main__":
    main()
