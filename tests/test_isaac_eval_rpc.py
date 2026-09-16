"""Request identity, deduplication, and Unix transport tests for Isaac EVAL."""

from __future__ import annotations

from pathlib import Path
from threading import Thread
import time

import numpy as np
import pytest

from tools.isaac_eval_rpc import (
    AmbiguousEvalTimeout,
    EvalInfrastructureError,
    EvalProtocolError,
    IsaacEvalEndpoint,
    PROTOCOL_REVISION,
    UnixEvalClient,
    serve_unix_socket,
)


class FakeIsaacEnvironment:
    def __init__(self, *, reset_delay_s: float = 0.0, fail_step: bool = False) -> None:
        self.reset_calls = 0
        self.step_calls = 0
        self.reset_delay_s = reset_delay_s
        self.fail_step = fail_step

    def reset(self, seed: int):
        self.reset_calls += 1
        if self.reset_delay_s:
            time.sleep(self.reset_delay_s)
        return {"observation.state": np.asarray([seed], dtype=np.float32)}

    def step(self, action: np.ndarray):
        self.step_calls += 1
        if self.fail_step:
            raise RuntimeError("native step failed after entry")
        return (
            {"observation.state": action.astype(np.float32)},
            1.0,
            True,
            False,
            {"native_detail_must_not_cross_boundary": True},
        )


def _handshake() -> dict:
    return {
        "protocol_revision": PROTOCOL_REVISION,
        "run_id": "run-1",
        "D0_contract_fingerprint": "d0-sha256",
        "environment_revision": "isaac-s1",
        "PIPER_X_asset_model_revision": "asset-rev",
        "task_id": "task",
        "task_revision": "task-v1",
        "processor_revision": "processor-v1",
        "n_episodes": 2,
        "horizon": 3,
    }


def _reset(request_id: str = "reset-1") -> dict:
    return {
        "operation": "reset",
        "run_id": "run-1",
        "request_id": request_id,
        "episode_id": "episode-1",
        "seed": 7,
        "task_id": "task",
        "task_revision": "task-v1",
    }


def _step(request_id: str = "step-1", value: float = 1.0) -> dict:
    return {
        "operation": "step",
        "run_id": "run-1",
        "request_id": request_id,
        "episode_id": "episode-1",
        "step_index": 0,
        "canonical_D0_action_t": [value] * 14,
    }


def _start_server(tmp_path: Path, environment: FakeIsaacEnvironment):
    socket_path = tmp_path / "eval.sock"
    endpoint = IsaacEvalEndpoint(environment, _handshake())
    thread = Thread(target=serve_unix_socket, args=(endpoint, socket_path), daemon=True)
    thread.start()
    deadline = time.monotonic() + 2.0
    while not socket_path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError("server socket did not appear")
        time.sleep(0.005)
    return socket_path, endpoint, thread


def _finish(client: UnixEvalClient, thread: Thread) -> None:
    client.request("close", "close-1")
    client.disconnect()
    thread.join(timeout=2.0)
    assert not thread.is_alive()


def test_endpoint_deduplicates_non_idempotent_operations_and_binds_payload() -> None:
    environment = FakeIsaacEnvironment()
    endpoint = IsaacEvalEndpoint(environment, _handshake())

    first_reset = endpoint.handle(_reset())
    assert endpoint.handle(_reset()) == first_reset
    assert environment.reset_calls == 1

    first_step = endpoint.handle(_step())
    assert endpoint.handle(_step()) == first_step
    assert environment.step_calls == 1
    assert "native_info" not in first_step

    with pytest.raises(EvalProtocolError, match="different operation or payload"):
        endpoint.handle(_step(value=2.0))
    with pytest.raises(EvalProtocolError, match="step episode_id is not active"):
        endpoint.handle(_step(request_id="new-id"))
    assert environment.step_calls == 1


def test_native_failure_is_cached_and_never_reexecuted_as_task_truncation() -> None:
    environment = FakeIsaacEnvironment(fail_step=True)
    endpoint = IsaacEvalEndpoint(environment, _handshake())
    endpoint.handle(_reset())

    for _ in range(2):
        with pytest.raises(EvalInfrastructureError, match="Isaac step failed"):
            endpoint.handle(_step())

    assert environment.step_calls == 1


def test_rejected_request_id_is_bound_and_cannot_be_repaired_with_new_payload() -> None:
    environment = FakeIsaacEnvironment()
    endpoint = IsaacEvalEndpoint(environment, _handshake())
    endpoint.handle(_reset())
    invalid = _step(request_id="invalid-action")
    invalid["canonical_D0_action_t"] = [1.0]

    with pytest.raises(EvalProtocolError, match="finite 14-vector"):
        endpoint.handle(invalid)
    with pytest.raises(EvalProtocolError, match="different operation or payload"):
        endpoint.handle(_step(request_id="invalid-action"))

    assert environment.step_calls == 0


def test_abort_and_close_are_deduplicated_lifecycle_operations() -> None:
    endpoint = IsaacEvalEndpoint(FakeIsaacEnvironment(), _handshake())
    endpoint.handle(_reset())
    abort = {
        "operation": "abort",
        "run_id": "run-1",
        "request_id": "abort-1",
        "episode_id": "episode-1",
        "reason": "operator_stop",
    }
    first_abort = endpoint.handle(abort)
    assert endpoint.handle(abort) == first_abort
    with pytest.raises(EvalProtocolError, match="different operation or payload"):
        endpoint.handle({**abort, "reason": "different"})

    close = {"operation": "close", "run_id": "run-1", "request_id": "close-1"}
    first_close = endpoint.handle(close)
    assert endpoint.handle(close) == first_close


def test_reconnect_reuses_endpoint_cache_without_reexecution(tmp_path: Path) -> None:
    environment = FakeIsaacEnvironment()
    socket_path, _endpoint, thread = _start_server(tmp_path, environment)
    client = UnixEvalClient(socket_path, _handshake(), timeout_s=1.0)
    client.connect()
    first = client.request(
        "reset",
        "reset-1",
        episode_id="episode-1",
        seed=7,
        task_id="task",
        task_revision="task-v1",
    )
    client.disconnect()
    client.connect()
    duplicate = client.request(
        "reset",
        "reset-1",
        episode_id="episode-1",
        seed=7,
        task_id="task",
        task_revision="task-v1",
    )
    assert duplicate == first
    assert environment.reset_calls == 1
    client.request(
        "step",
        "step-1",
        episode_id="episode-1",
        step_index=0,
        canonical_D0_action_t=[1.0] * 14,
    )
    _finish(client, thread)


def test_ambiguous_timeout_requires_explicit_same_id_retry(tmp_path: Path) -> None:
    environment = FakeIsaacEnvironment(reset_delay_s=0.08)
    socket_path, _endpoint, thread = _start_server(tmp_path, environment)
    client = UnixEvalClient(socket_path, _handshake(), timeout_s=0.02)
    client.connect()
    with pytest.raises(AmbiguousEvalTimeout, match="do not retry automatically"):
        client.request(
            "reset",
            "reset-1",
            episode_id="episode-1",
            seed=7,
            task_id="task",
            task_revision="task-v1",
        )
    time.sleep(0.1)
    assert environment.reset_calls == 1

    client.timeout_s = 1.0
    client.connect()
    client.request(
        "reset",
        "reset-1",
        episode_id="episode-1",
        seed=7,
        task_id="task",
        task_revision="task-v1",
    )
    assert environment.reset_calls == 1
    client.request(
        "step",
        "step-1",
        episode_id="episode-1",
        step_index=0,
        canonical_D0_action_t=[1.0] * 14,
    )
    _finish(client, thread)


def test_client_detects_endpoint_restart_and_invalidates_run(tmp_path: Path) -> None:
    socket_path, _endpoint, first_thread = _start_server(tmp_path, FakeIsaacEnvironment())
    client = UnixEvalClient(socket_path, _handshake(), timeout_s=1.0)
    client.connect()
    _finish(client, first_thread)

    socket_path, _endpoint, second_thread = _start_server(tmp_path, FakeIsaacEnvironment())
    with pytest.raises(EvalInfrastructureError, match="endpoint restarted"):
        client.connect()

    cleanup = UnixEvalClient(socket_path, _handshake(), timeout_s=1.0)
    cleanup.connect()
    _finish(cleanup, second_thread)
