"""Concrete Unix-socket EVAL boundary for the isolated PIPER-X Isaac process."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import math
from pathlib import Path
import socket
import stat
from threading import Lock
from typing import Any, Mapping
import uuid

import numpy as np


PROTOCOL_REVISION = "piper_x_eval_boundary_v2"
HANDSHAKE_FIELDS = (
    "protocol_revision",
    "run_id",
    "D0_contract_fingerprint",
    "environment_revision",
    "PIPER_X_asset_model_revision",
    "task_id",
    "task_revision",
    "processor_revision",
    "n_episodes",
    "horizon",
)
REQUEST_FIELDS = {
    "reset": ("run_id", "request_id", "episode_id", "seed", "task_id", "task_revision"),
    "step": ("run_id", "request_id", "episode_id", "step_index", "canonical_D0_action_t"),
    "abort": ("run_id", "request_id", "episode_id", "reason"),
    "close": ("run_id", "request_id"),
}


class EvalProtocolError(ValueError):
    """A request is invalid and was not executed."""


class EvalInfrastructureError(RuntimeError):
    """Transport or endpoint identity failure, never task truncation."""


class AmbiguousEvalTimeout(EvalInfrastructureError):
    """The caller cannot know whether the request executed."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise EvalProtocolError("non-finite floats are forbidden by the JSON codec")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise EvalProtocolError(f"value is not JSON serializable: {type(value).__name__}")


def _canonical_fingerprint(operation: str, request: Mapping[str, Any]) -> str:
    payload = {
        key: _jsonable(value)
        for key, value in request.items()
        if key not in {"run_id", "request_id", "operation"}
    }
    encoded = json.dumps(
        {"operation": operation, "payload": payload},
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def bind_runtime_handshake(requested: Mapping[str, Any], runtime_identity: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the caller's run request to facts collected by the loaded S1 runtime."""
    handshake = IsaacEvalEndpoint._validate_handshake(requested)
    identity_fields = set(HANDSHAKE_FIELDS) - {"protocol_revision", "run_id", "n_episodes"}
    if set(runtime_identity) != identity_fields:
        raise EvalInfrastructureError("runtime identity fields are incomplete")
    differences = [key for key in sorted(identity_fields) if handshake[key] != runtime_identity[key]]
    if differences:
        raise EvalProtocolError(f"manifest differs from loaded runtime: {differences}")
    return handshake


class IsaacEvalEndpoint:
    """Episode-sensitive request execution around one concrete Isaac environment."""

    def __init__(self, environment: Any, handshake: Mapping[str, Any]) -> None:
        self.environment = environment
        self.handshake = self._validate_handshake(handshake)
        self.endpoint_instance_id = uuid.uuid4().hex
        self._lock = Lock()
        self._cache: OrderedDict[
            tuple[str, str],
            tuple[str, dict[str, Any] | EvalProtocolError | EvalInfrastructureError],
        ] = OrderedDict()
        self._active_episode: str | int | None = None
        self._next_step_index = 0
        self._started_episodes: set[str | int] = set()
        self.closed = False
        # reset + every possible step + abort per episode + final close
        self._capacity = self.handshake["n_episodes"] * (self.handshake["horizon"] + 2) + 1

    @staticmethod
    def _validate_handshake(value: Mapping[str, Any]) -> dict[str, Any]:
        if set(value) != set(HANDSHAKE_FIELDS):
            raise EvalProtocolError("handshake fields do not match the protocol")
        result = {key: _jsonable(value[key]) for key in HANDSHAKE_FIELDS}
        if result["protocol_revision"] != PROTOCOL_REVISION:
            raise EvalProtocolError("unsupported protocol_revision")
        if not isinstance(result["run_id"], str) or not result["run_id"]:
            raise EvalProtocolError("run_id must be a non-empty string")
        for key in (
            "D0_contract_fingerprint",
            "environment_revision",
            "PIPER_X_asset_model_revision",
            "task_id",
            "task_revision",
            "processor_revision",
        ):
            if not isinstance(result[key], str) or not result[key]:
                raise EvalProtocolError(f"{key} must be a non-empty string")
        for key in ("n_episodes", "horizon"):
            if (
                isinstance(result[key], bool)
                or not isinstance(result[key], int)
                or result[key] <= 0
            ):
                raise EvalProtocolError(f"{key} must be a positive integer")
        return result

    def accept_handshake(self, request: Mapping[str, Any]) -> dict[str, Any]:
        candidate = {key: request.get(key) for key in HANDSHAKE_FIELDS}
        if (
            set(request) != {"operation", *HANDSHAKE_FIELDS}
            or request.get("operation") != "handshake"
        ):
            raise EvalProtocolError("invalid handshake envelope")
        if self._validate_handshake(candidate) != self.handshake:
            raise EvalProtocolError("handshake does not identify the active run")
        return {
            "operation": "handshake",
            "run_id": self.handshake["run_id"],
            "endpoint_instance_id": self.endpoint_instance_id,
            "accepted": True,
        }

    def handle(self, request: Mapping[str, Any]) -> dict[str, Any]:
        operation = request.get("operation")
        if operation == "handshake":
            return self.accept_handshake(request)
        if operation not in REQUEST_FIELDS:
            raise EvalProtocolError(f"unknown operation: {operation!r}")
        expected = {"operation", *REQUEST_FIELDS[operation]}
        if set(request) != expected:
            raise EvalProtocolError(
                f"{operation} fields mismatch: missing={sorted(expected - set(request))} "
                f"extra={sorted(set(request) - expected)}"
            )
        run_id = request["run_id"]
        request_id = request["request_id"]
        if run_id != self.handshake["run_id"]:
            raise EvalInfrastructureError("request belongs to an inactive run")
        if not isinstance(request_id, str) or not request_id:
            raise EvalProtocolError("request_id must be a non-empty string")
        fingerprint = _canonical_fingerprint(operation, request)
        key = (run_id, request_id)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                if cached[0] != fingerprint:
                    raise EvalProtocolError(
                        "request_id was reused with a different operation or payload"
                    )
                if isinstance(cached[1], (EvalProtocolError, EvalInfrastructureError)):
                    raise type(cached[1])(str(cached[1]))
                return dict(cached[1])
            if self.closed:
                raise EvalInfrastructureError("run is already closed")
            if len(self._cache) >= self._capacity:
                raise EvalInfrastructureError("declared run request capacity exceeded")
            try:
                native_response = self._execute(operation, request)
            except (EvalProtocolError, EvalInfrastructureError) as exc:
                self._cache[key] = (fingerprint, exc)
                raise
            try:
                response = {"request_id": request_id, **_jsonable(native_response)}
            except EvalProtocolError as exc:
                failure = EvalInfrastructureError(f"invalid Isaac response: {exc}")
                self._cache[key] = (fingerprint, failure)
                raise failure from exc
            self._cache[key] = (fingerprint, response)
            return dict(response)

    def _execute(self, operation: str, request: Mapping[str, Any]) -> dict[str, Any]:
        if operation == "reset":
            return self._reset(request)
        if operation == "step":
            return self._step(request)
        if operation == "abort":
            return self._abort(request)
        if self._active_episode is not None:
            raise EvalProtocolError("close requires the active episode to finish or abort")
        self.closed = True
        return {"close_state": "closed"}

    def _reset(self, request: Mapping[str, Any]) -> dict[str, Any]:
        episode_id = request["episode_id"]
        if not isinstance(episode_id, str) or not episode_id:
            raise EvalProtocolError("episode_id must be a non-empty string")
        seed = request["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise EvalProtocolError("seed must be an integer")
        if self._active_episode is not None:
            raise EvalProtocolError("reset while another episode is active")
        if episode_id in self._started_episodes:
            raise EvalProtocolError("episode_id was already used with another request_id")
        if len(self._started_episodes) >= self.handshake["n_episodes"]:
            raise EvalProtocolError("declared n_episodes exceeded")
        if (
            request["task_id"] != self.handshake["task_id"]
            or request["task_revision"] != self.handshake["task_revision"]
        ):
            raise EvalProtocolError("reset task identity differs from handshake")
        try:
            observation = self.environment.reset(seed)
        except Exception as exc:
            raise EvalInfrastructureError(f"Isaac reset failed: {exc}") from exc
        self._active_episode = episode_id
        self._started_episodes.add(episode_id)
        self._next_step_index = 0
        return {"canonical_D0_obs_0": observation, "effective_seed": seed}

    def _step(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if request["episode_id"] != self._active_episode:
            raise EvalProtocolError("step episode_id is not active")
        step_index = request["step_index"]
        if isinstance(step_index, bool) or not isinstance(step_index, int):
            raise EvalProtocolError("step_index must be an integer")
        if step_index != self._next_step_index:
            raise EvalProtocolError(
                f"step_index={request['step_index']} expected={self._next_step_index}"
            )
        if self._next_step_index >= self.handshake["horizon"]:
            raise EvalProtocolError("declared episode horizon exceeded")
        action = np.asarray(request["canonical_D0_action_t"], dtype=np.float64)
        if action.shape != (14,) or not np.isfinite(action).all():
            raise EvalProtocolError("canonical_D0_action_t must be a finite 14-vector")
        try:
            observation, reward, terminated, truncated, _native_info = self.environment.step(action)
        except Exception as exc:
            raise EvalInfrastructureError(f"Isaac step failed: {exc}") from exc
        success = bool(terminated)
        self._next_step_index += 1
        if terminated or truncated:
            self._active_episode = None
        reason = "success" if success else "time_limit" if truncated else None
        return {
            "canonical_D0_obs_t_plus_1": observation,
            "reward_t": float(reward),
            "terminated_t": bool(terminated),
            "truncated_t": bool(truncated),
            "success_t": success,
            "termination_reason": reason,
        }

    def _abort(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if request["episode_id"] != self._active_episode:
            raise EvalProtocolError("abort episode_id is not active")
        if not isinstance(request["reason"], str) or not request["reason"]:
            raise EvalProtocolError("abort reason must be a non-empty string")
        self._active_episode = None
        return {"abort_state": "aborted"}


def _error_response(exc: Exception) -> dict[str, Any]:
    classification = (
        "protocol_error" if isinstance(exc, EvalProtocolError) else "infrastructure_failure"
    )
    return {"error": {"classification": classification, "message": str(exc)}}


def serve_unix_socket(endpoint: IsaacEvalEndpoint, socket_path: Path) -> None:
    """Serve one endpoint until a deduplicated close request succeeds."""

    if socket_path.exists():
        mode = socket_path.stat().st_mode
        if stat.S_ISSOCK(mode):
            raise EvalInfrastructureError(f"socket already exists: {socket_path}")
        raise EvalInfrastructureError(f"refusing to replace non-socket path: {socket_path}")
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(socket_path))
        server.listen(1)
        while not endpoint.closed:
            connection, _ = server.accept()
            stream = connection.makefile("rwb")
            try:
                for raw in stream:
                    try:
                        request = json.loads(raw)
                        if not isinstance(request, dict):
                            raise EvalProtocolError("request must be a JSON object")
                        response = endpoint.handle(request)
                    except (EvalProtocolError, EvalInfrastructureError, ValueError) as exc:
                        response = _error_response(exc)
                    try:
                        stream.write(json.dumps(response, allow_nan=False).encode() + b"\n")
                        stream.flush()
                    except BrokenPipeError:
                        break
                    if endpoint.closed:
                        break
            finally:
                try:
                    stream.close()
                except OSError:
                    pass
                connection.close()
    finally:
        server.close()
        if socket_path.exists() and stat.S_ISSOCK(socket_path.stat().st_mode):
            socket_path.unlink()


class UnixEvalClient:
    """Single-in-flight client with explicit, same-ID retry only."""

    def __init__(self, socket_path: Path, handshake: Mapping[str, Any], timeout_s: float) -> None:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.socket_path = socket_path
        self.handshake = dict(handshake)
        self.timeout_s = timeout_s
        self.endpoint_instance_id: str | None = None
        self._socket: socket.socket | None = None
        self._stream: Any = None
        self._lock = Lock()

    def connect(self) -> None:
        self.disconnect()
        transport = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        transport.settimeout(self.timeout_s)
        try:
            transport.connect(str(self.socket_path))
            stream = transport.makefile("rwb")
            self._socket, self._stream = transport, stream
            response = self._exchange({"operation": "handshake", **self.handshake})
        except OSError as exc:
            transport.close()
            self._socket = self._stream = None
            raise EvalInfrastructureError(f"failed to connect to Isaac endpoint: {exc}") from exc
        except Exception:
            transport.close()
            self._socket = self._stream = None
            raise
        instance = response.get("endpoint_instance_id")
        if self.endpoint_instance_id is not None and instance != self.endpoint_instance_id:
            self.disconnect()
            raise EvalInfrastructureError("endpoint restarted; the active run is invalid")
        self.endpoint_instance_id = instance

    def disconnect(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
        if self._socket is not None:
            self._socket.close()
        self._stream = self._socket = None

    def request(self, operation: str, request_id: str, **payload: Any) -> dict[str, Any]:
        with self._lock:
            if self._stream is None:
                raise EvalInfrastructureError("client is not connected")
            request = {
                "operation": operation,
                "run_id": self.handshake["run_id"],
                "request_id": request_id,
                **payload,
            }
            try:
                response = self._exchange(request)
            except (TimeoutError, socket.timeout) as exc:
                self.disconnect()
                raise AmbiguousEvalTimeout(
                    "request timed out; do not retry automatically, reconnect and reuse request_id"
                ) from exc
            except OSError as exc:
                self.disconnect()
                raise EvalInfrastructureError(f"Isaac transport failed: {exc}") from exc
            if "error" in response:
                error = response["error"]
                exception = (
                    EvalProtocolError
                    if error["classification"] == "protocol_error"
                    else EvalInfrastructureError
                )
                raise exception(error["message"])
            if response.get("request_id") != request_id:
                raise EvalProtocolError("response request_id mismatch")
            return response

    def _exchange(self, request: Mapping[str, Any]) -> dict[str, Any]:
        assert self._stream is not None
        try:
            encoded = json.dumps(_jsonable(request), allow_nan=False).encode() + b"\n"
        except (TypeError, ValueError) as exc:
            raise EvalProtocolError(f"request is not valid JSON: {exc}") from exc
        self._stream.write(encoded)
        self._stream.flush()
        raw = self._stream.readline()
        if not raw:
            raise EvalInfrastructureError("endpoint closed before responding")
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EvalProtocolError("endpoint returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise EvalProtocolError("response must be a JSON object")
        if "error" in response:
            error = response["error"]
            exception = (
                EvalProtocolError
                if error["classification"] == "protocol_error"
                else EvalInfrastructureError
            )
            raise exception(error["message"])
        return response
