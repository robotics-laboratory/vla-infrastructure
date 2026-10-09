"""Optional real CPU OVPhysX tests, never launched by ordinary core collection.

Run with the isolated ovphysx Python, ROBOSYN_OVPHYSX_CPU_TEST_SEED pointing
to a reviewed fixture, and ROBOSYN_OVPHYSX_CPU_TEST_ARTIFACTS to retain every
worker log/receipt/seed. No GPU or Kit process is imported by these tests.
"""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
import uuid
from multiprocessing.connection import Connection

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from tools.isaac_vr_standalone_ik import piper_ik_state  # noqa: E402


@unittest.skipUnless(
    os.environ.get("ROBOSYN_OVPHYSX_CPU_TEST_SEED"), "optional native CPU fixture not selected"
)
class NativeCpuWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.metadata.version("ovphysx") != "0.6.3":
            raise RuntimeError("Native tests require isolated pinned ovphysx0.6.3 Python")
        cls.seed = json.loads(Path(os.environ["ROBOSYN_OVPHYSX_CPU_TEST_SEED"]).read_text())
        cls.output = Path(
            os.environ.get("ROBOSYN_OVPHYSX_CPU_TEST_ARTIFACTS", "/tmp/ovphysx-cpu-tests")
        )
        cls.output.mkdir(parents=True, exist_ok=True)

    def launch(self, label, seed=None, expected_op="ready"):
        folder = self.output / (label + "-" + uuid.uuid4().hex[:8])
        folder.mkdir()
        file = folder / "seed.json"
        file.write_text(json.dumps(seed or self.seed, indent=2) + "\n")
        left, right = socket.socketpair()
        log = (folder / "worker.log").open("w")
        process = subprocess.Popen(
            [
                sys.executable,
                str(REPO / "tools/isaac_vr_standalone_worker.py"),
                "--fd",
                str(right.fileno()),
                "--seed",
                str(file),
                "--receipt",
                str(folder / "receipt.json"),
            ],
            pass_fds=(right.fileno(),),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        right.close()
        connection = Connection(left.detach())

        def cleanup():
            connection.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
            log.close()

        self.addCleanup(cleanup)
        self.assertTrue(connection.poll(25), f"worker startup timeout: {folder}")
        ready = connection.recv()
        self.assertEqual(ready["op"], expected_op, (folder, ready))
        return connection, process, ready, folder

    def step(self, connection, seq, targets):
        connection.send(dict(op="step", seq=seq, native_targets=targets))
        self.assertTrue(connection.poll(25), "native step timeout")
        message = connection.recv()
        self.assertEqual(message["op"], "captured", message)
        self.assertEqual(message["snapshot"]["seq"], seq)
        self.assertEqual(message["snapshot"]["physics_steps"], (seq + 1) * 4)
        self.assertAlmostEqual(message["snapshot"]["sim_time_s"], (seq + 1) / 30.0)
        return message

    def close(self, connection, process, folder):
        connection.send(dict(op="close"))
        self.assertTrue(connection.poll(10))
        self.assertEqual(connection.recv()["op"], "closed")
        process.wait(timeout=10)
        self.assertEqual(process.returncode, 0)
        receipt = json.loads((folder / "receipt.json").read_text())
        self.assertEqual(receipt["cleanup_errors"], [])
        self.assertFalse(receipt["gpu_execution"])
        return receipt

    def test_seed_schema_and_units_reject_before_logical_physics(self):
        for key, value in [("schema", "wrong_schema"), ("dof_units", ["deg"] * 6 + ["m"] * 3)]:
            with self.subTest(key=key):
                seed = copy.deepcopy(self.seed)
                seed[key] = value
                c, p, error, folder = self.launch("bad-seed-" + key, seed, expected_op="error")
                self.assertEqual(error["controls"], 0)
                self.assertEqual(error["physics_steps"], 0)
                p.wait(timeout=10)
                self.assertNotEqual(p.returncode, 0)
                receipt = json.loads((folder / "receipt.json").read_text())
                self.assertEqual(receipt["cleanup_errors"], [])

    def test_rejects_boolean_sequence_and_malformed_targets_before_physics(self):
        for seq, targets in [
            (True, self.seed["initial"]["q"]),
            (0, [[0.0] * 8] * 2),
            (0, [[float("nan")] * 9] * 2),
        ]:
            with self.subTest(seq=seq, shape=np.asarray(targets).shape):
                c, p, ready, folder = self.launch("bad-step")
                c.send(dict(op="step", seq=seq, native_targets=targets))
                self.assertTrue(c.poll(10))
                error = c.recv()
                self.assertEqual(error["op"], "error")
                self.assertEqual(error["controls"], 0)
                self.assertEqual(error["physics_steps"], 0)
                p.wait(timeout=10)
                self.assertNotEqual(p.returncode, 0)
                receipt = json.loads((folder / "receipt.json").read_text())
                self.assertEqual(receipt["cleanup_errors"], [])

    def test_initial_state_current_vr_drives_and_all_props_roundtrip(self):
        c, p, ready, folder = self.launch("initial-roundtrip")
        s = ready["snapshot"]
        np.testing.assert_allclose(s["q"], self.seed["initial"]["q"], atol=2e-5, rtol=0)
        np.testing.assert_allclose(s["dq"], self.seed["initial"]["dq"], atol=2e-5, rtol=0)
        self.assertEqual(s["rigid_body_world_pose"].shape, (27, 7))
        self.assertEqual(s["articulation_body_com_local_pose"].shape, (2, 12, 7))
        self.assertEqual(s["jacobian"].shape, (2, 66, 9))
        for name, values in self.seed["dof_properties"].items():
            np.testing.assert_allclose(ready["dof_properties"][name], values, atol=1e-6, rtol=1e-5)
        np.testing.assert_array_equal(ready["dof_properties"]["stiffness"][:, 7:], 0)
        np.testing.assert_array_equal(ready["dof_properties"]["damping"][:, 7:], 0)
        for index, path in enumerate(self.seed["dynamic_body_paths"]):
            row = ready["rigid_body_paths"].index(path)
            np.testing.assert_allclose(
                s["rigid_body_world_pose"][row, :3],
                self.seed["initial"]["dynamic_body_pose"][index][:3],
                atol=2e-5,
                rtol=0,
            )
        receipt = self.close(c, p, folder)
        self.assertEqual(receipt["physics_steps"], 0)

    def test_all_three_dynamic_prop_velocities_survive_seed_restore(self):
        seed = copy.deepcopy(self.seed)
        for i, pose in enumerate(seed["initial"]["dynamic_body_pose"]):
            pose[2] = 2.0 + 0.2 * i  # freefall, above collision surfaces
        velocities = [
            [0.25, -0.15, 0.0, 0.0, 0.0, 0.0],
            [-0.35, 0.2, 0.0, 0.0, 0.0, 0.0],
            [0.1, 0.3, 0.0, 0.0, 0.0, 0.0],
        ]
        seed["initial"]["dynamic_body_velocity"] = velocities
        c, p, ready, folder = self.launch("dynamic-velocity", seed)
        snapshot = self.step(c, 0, np.asarray(seed["initial"]["q"], np.float32))["snapshot"]
        measured = []
        for i, path in enumerate(seed["dynamic_body_paths"]):
            row = ready["rigid_body_paths"].index(path)
            initial = np.asarray(seed["initial"]["dynamic_body_pose"][i][:3])
            final = snapshot["rigid_body_world_pose"][row, :3]
            expected_xy = initial[:2] + np.asarray(velocities[i][:2]) / 30.0
            np.testing.assert_allclose(final[:2], expected_xy, atol=2e-5, rtol=0)
            self.assertLess(float(final[2]), float(initial[2]))
            self.assertGreater(float(final[2]), float(initial[2]) - 0.01)
            measured.append(final.copy())
        np.savez(
            folder / "freefall.npz",
            positions=np.asarray(measured),
            initial=seed["initial"]["dynamic_body_pose"],
            velocities=velocities,
        )
        self.close(c, p, folder)

    def test_passive_newton_mimic_follows_both_signs_not_position_targets(self):
        c, p, ready, folder = self.launch("passive-mimic")
        command = np.asarray(self.seed["initial"]["q"], np.float32).copy()
        frozen_initial = ready["snapshot"]["q"].copy()
        residuals, positions = [], []
        for seq in range(90):
            command[:, 6] = 0.08 if seq < 45 else 0.02
            command[:, 7:] = 0  # deliberately inconsistent targets on passive followers
            message = self.step(c, seq, command)
            snapshot = message["snapshot"]
            residuals.append(snapshot["mimic_residual"].copy())
            positions.append(snapshot["q"][:, 6:].copy())
            self.assertTrue(snapshot["fixed_base"])
            self.assertTrue(np.isfinite(snapshot["jacobian"]).all())
        residuals, positions = np.asarray(residuals), np.asarray(positions)
        np.savez(folder / "motion.npz", residuals=residuals, gripper_positions=positions)
        np.testing.assert_array_equal(
            ready["snapshot"]["q"], frozen_initial
        )  # retained snapshot ownership
        self.assertLess(float(np.abs(residuals).max()), 2e-4)
        self.assertGreater(float(positions[:45, :, 0].max() - positions[45:, :, 0].min()), 0.03)
        self.assertTrue((positions[:, :, 1] >= -2e-5).all())
        self.assertTrue((positions[:, :, 2] <= 2e-5).all())
        receipt = self.close(c, p, folder)
        self.assertEqual(receipt["controls"], 90)
        self.assertEqual(receipt["physics_steps"], 360)

    def test_rejects_out_of_order_sequence_before_another_physics_step(self):
        c, p, ready, folder = self.launch("wrong-sequence")
        command = np.asarray(self.seed["initial"]["q"], np.float32)
        self.step(c, 0, command)
        c.send(dict(op="step", seq=2, native_targets=command))
        self.assertTrue(c.poll(10))
        error = c.recv()
        self.assertEqual(error["op"], "error")
        self.assertEqual(error["controls"], 1)
        self.assertEqual(error["physics_steps"], 4)
        self.assertIn("consecutive integer", error["error"])
        p.wait(timeout=10)
        self.assertNotEqual(p.returncode, 0)
        receipt = json.loads((folder / "receipt.json").read_text())
        self.assertEqual(receipt["cleanup_errors"], [])

    def test_com_to_origin_jacobian_matches_native_fk_finite_difference(self):
        c, p, ready, folder = self.launch("jacobian-baseline")
        # Explicitly reconstruct by native body_names, independent of interleaved rigid view ordering.
        poses = np.stack(
            [
                [
                    ready["snapshot"]["rigid_body_world_pose"][
                        ready["rigid_body_paths"].index(
                            next(
                                path
                                for path in ready["rigid_body_paths"]
                                if f"/{side}Piper/" in path and path.rsplit("/", 1)[-1] == name
                            )
                        )
                    ]
                    for name in ready["body_names"]
                ]
                for side in ("Left", "Right")
            ]
        )
        state = piper_ik_state(
            q=ready["snapshot"]["q"],
            link_poses_xyzw=poses,
            com_poses_xyzw=ready["snapshot"]["articulation_body_com_local_pose"],
            jacobian_com=ready["snapshot"]["jacobian"],
            limits=ready["dof_properties"]["limits"],
            body_names=ready["body_names"],
            dof_names=ready["dof_names"],
            fixed_base=True,
        )
        expected = state["jacobian"].copy()
        self.close(c, p, folder)
        epsilon, measured = 1e-3, np.empty((2, 6, 6), np.float32)
        for joint in range(6):
            endpoints = []
            for sign in (1, -1):
                seed = copy.deepcopy(self.seed)
                values = np.asarray(seed["initial"]["q"], np.float32)
                values[:, joint] += sign * epsilon
                seed["initial"]["q"] = values.tolist()
                pc, pp, pr, pf = self.launch(f"jacobian-joint{joint}-sign{sign}", seed)
                paths = pr["rigid_body_paths"]
                endpoints.append(
                    np.stack(
                        [
                            pr["snapshot"]["rigid_body_world_pose"][
                                paths.index(
                                    next(
                                        path
                                        for path in paths
                                        if f"/{side}Piper/" in path
                                        and path.endswith("/gripper_base")
                                    )
                                )
                            ]
                            for side in ("Left", "Right")
                        ]
                    )
                )
                self.close(pc, pp, pf)
            measured[:, :3, joint] = (endpoints[0][:, :3] - endpoints[1][:, :3]) / (2 * epsilon)
            plus, minus = endpoints[0][:, 3:].copy(), endpoints[1][:, 3:].copy()
            minus[np.sum(plus * minus, axis=1) < 0] *= -1  # same quaternion hemisphere
            vp, wp, vm, wm = plus[:, :3], plus[:, 3:], -minus[:, :3], minus[:, 3:]
            # q_plus * conjugate(q_minus), expressed in world coordinates.
            measured[:, 3:, joint] = (wp * vm + wm * vp + np.cross(vp, vm)) / epsilon
        np.savez(
            folder / "jacobian-fd.npz",
            expected=expected,
            measured=measured,
            error=expected - measured,
        )
        np.testing.assert_allclose(expected, measured, atol=1.5e-4, rtol=8e-4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
