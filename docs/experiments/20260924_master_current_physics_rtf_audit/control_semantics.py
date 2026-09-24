"""Offline processor check for absolute grip and relative arm deltas at 8/30 Hz."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


def _module(root, name):
    path = root / "tools/isaac_s2_processor.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sample(module, dx, trigger):
    return module.ControllerDeltaSample(np.array([dx, 0.0, 0.0]), np.zeros(3),
                                        True, True, 0.0, trigger, 0.0)


def check(module, hz):
    processor = module.BimanualS2TeleopProcessor()
    initial = _sample(module, 0.0, 0.0)
    processor.advance(initial, initial)
    targets = []
    deltas = []
    for _ in range(hz):
        sample = _sample(module, 0.1 / hz, 1.0)
        command = processor.advance(sample, sample)
        targets.append(command.left.gripper_aperture_m)
        deltas.append(float(command.left.delta_pose[0]))
    return {"input_samples_per_second": hz, "first_arm_delta_m": deltas[0],
            "sum_arm_delta_m": sum(deltas), "gripper_target_m_each_tick": targets,
            "input_pose_change_m": 0.1}


def main():
    old = Path("/home/ebulochkin/vla_infrastructure")
    current = Path("/home/ebulochkin/vla_infrastructure/.worktrees/vr-record-runtime-optimization-audit")
    output = Path(__file__).with_name("control-semantics.json")
    result = {label: {str(hz): check(_module(root, f"processor_{label}_{hz}"), hz)
                      for hz in (8, 30)} for label, root in (("old", old), ("current", current))}
    for cases in result.values():
        for case in cases.values():
            assert abs(case["sum_arm_delta_m"] - 0.2) < 1e-12
            assert all(abs(value) < 1e-12 for value in case["gripper_target_m_each_tick"])
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
