"""Authenticated Gateway RPC. Each invocation makes exactly one HTTP attempt.

HTTP is restricted to literal loopback addresses for local simulation. Remote
endpoints require verified TLS; deployments must also configure mutual TLS at
the server. The inner command/receipt signatures remain unchanged.
"""

import asyncio
import hashlib
import http.client
import ipaddress
import json
import math
import ssl
from threading import Lock
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from jsonschema import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from alap.adapters.gateway.maintenance import GatewayMaintenance
from alap.adapters.gateway.tls import fingerprint
from alap.domain.rules import DomainError, require_json_value

REQUEST_LIMIT = 1024 * 1024
RESPONSE_LIMIT = 32 * 1024 * 1024
OPERATIONS = frozenset(
    {
        "accept",
        "query",
        "confirm_dataset",
        "stop",
        "recover_command",
        "telemetry",
        "challenge",
        "bind_epoch",
    }
)


def _decode(data):
    value = json.loads(data)
    require_json_value(value)
    if not isinstance(value, dict):
        raise ValueError("Object required")
    return value


class HTTPGateway:
    """GatewayPort network adapter; never retry a potentially executed request."""

    def __init__(
        self, identity, url, authenticator, *, timeout=60, tls_context=None, server_sha256=None
    ):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Gateway origin required, without credentials or path")
        if parsed.scheme == "http":
            try:
                local = ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                local = False
            if not local:
                raise ValueError("Plain HTTP is allowed only on literal loopback")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Finite positive timeout required")
        if tls_context is not None and (
            tls_context.verify_mode != ssl.CERT_REQUIRED or not tls_context.check_hostname
        ):
            raise ValueError("TLS certificate and hostname verification required")
        self.server_sha256 = fingerprint(server_sha256) if parsed.scheme == "https" else None
        if parsed.scheme == "http" and server_sha256 is not None:
            raise ValueError("Certificate binding requires HTTPS")
        self.identity, self.auth = identity, authenticator
        self.origin, self.timeout, self.tls_context = parsed, timeout, tls_context

    def _call(self, operation, body=None, *, authenticator=None, path="/rpc", timeout=None):
        auth = authenticator or self.auth
        timeout = self.timeout if timeout is None else timeout
        binding = {"gateway_id": self.identity, "request_id": str(uuid4()), "operation": operation}
        data = json.dumps(auth.seal({**binding, "body": body}), allow_nan=False).encode()
        if len(data) > REQUEST_LIMIT:
            raise DomainError("GATEWAY_REQUEST_LIMIT", "RPC request exceeds configured limit")
        origin = self.origin
        if origin.scheme == "https":
            connection = http.client.HTTPSConnection(
                origin.hostname, origin.port, timeout=timeout, context=self.tls_context
            )
        else:
            connection = http.client.HTTPConnection(origin.hostname, origin.port, timeout=timeout)
        try:
            if origin.scheme == "https":
                connection.connect()
                actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
                if actual != self.server_sha256:
                    raise ConnectionError("Gateway certificate identity mismatch")
            connection.request("POST", path, data, {"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise ConnectionError("Gateway transport rejected request")
            raw = response.read(RESPONSE_LIMIT + 1)
            if len(raw) > RESPONSE_LIMIT:
                raise ConnectionError("Gateway response exceeds limit")
            result = auth.open(_decode(raw))
            if any(result.get(key) != value for key, value in binding.items()):
                raise ConnectionError("Gateway response binding mismatch")
            if result.get("error") is not None:
                code = result["error"]
                if not isinstance(code, str) or len(code) > 100:
                    raise ConnectionError("Malformed Gateway error")
                raise DomainError(code, "Gateway rejected operation")
            if not isinstance(result.get("result"), dict):
                raise ConnectionError("Malformed Gateway result")
            return result["result"]
        except DomainError:
            raise
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError) as exc:
            # ExecutionService marks a lost/untrusted response UNKNOWN and reconciles.
            raise ConnectionError("Gateway response unavailable or invalid") from exc
        finally:
            connection.close()

    def maintenance(self, operation, body):
        auth = getattr(self, "maintenance_auth", None)
        if auth is None:
            raise DomainError("SERVICE_UNAVAILABLE", "Maintenance credentials not configured")
        return self._call(operation, body, authenticator=auth, path="/maintenance", timeout=5)

    def accept(self, signed):
        return self._call("accept", signed)

    def query(self, command_id):
        return self._call("query", command_id)

    def confirm_dataset(self, signed):
        return self._call("confirm_dataset", signed)

    def stop(self, signed):
        return self._call("stop", signed)

    def recover_command(self, signed):
        return self._call("recover_command", signed)

    def telemetry(self, condition):
        return self._call("telemetry", condition)

    def challenge(self):
        return self._call("challenge")

    def bind_epoch(self, signed):
        return self._call("bind_epoch", signed)

    def close(self):
        """No pooled connections or ownership of the remote journal."""


def create_gateway_app(
    gateway,
    *,
    max_window_s=30,
    max_samples=10000,
    client_sha256=None,
    supervision_auth=None,
    maintenance_auth=None,
):
    """Serve one journal owner with bounded admission and explicit RPC dispatch.

    Busy requests fail rather than queue behind a device operation indefinitely.
    A disconnected caller does not cancel an already admitted physical operation.
    """
    if not math.isfinite(max_window_s) or max_window_s <= 0 or max_samples < 2:
        raise ValueError("Positive window and sample limits required")
    allowed = None
    if client_sha256 is not None:
        if not isinstance(client_sha256, list) or not client_sha256:
            raise ValueError("Explicit client certificate identities required")
        allowed = frozenset(fingerprint(value) for value in client_sha256)
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    admission = Lock()
    methods = {name: getattr(gateway, name) for name in OPERATIONS}

    def windows(conditions):
        if not isinstance(conditions, list) or len(conditions) > 32:
            raise ValueError("At most 32 stable conditions allowed")
        if not conditions:
            return
        for condition in conditions:
            gateway.catalog.validate("stable_condition", condition)
        duration = max(item["min_duration_s"] for item in conditions)
        interval = min(item["max_age_s"] for item in conditions) / 2
        if (
            duration > max_window_s
            or interval == 0
            or duration / interval > max_samples / len(conditions) - 1
        ):
            raise DomainError("GATEWAY_WINDOW_LIMIT", "Telemetry budget exceeded")

    def invoke(operation, body):
        if operation == "challenge":
            if body is not None:
                raise ValueError("Challenge has no arguments")
            return methods[operation]()
        if operation == "query":
            if not isinstance(body, str) or not 1 <= len(body) <= 256:
                raise ValueError("Command identity required")
        elif not isinstance(body, dict):
            raise ValueError("Object required")
        if operation == "telemetry":
            windows(body.get("conditions", [body]))
        if operation == "accept":
            inner = gateway.auth.open(body)
            task = inner["task"]
            gateway.catalog.validate("plan_task", task)
            conditions = list(task["preconditions"])
            if task["success_condition"]["kind"] == "stable_window":
                conditions.append(task["success_condition"])
            windows(conditions)
        return methods[operation](body)

    @app.post("/rpc")
    async def rpc(request: Request):
        if (
            allowed is not None
            and request.scope.get("state", {}).get("tls_peer_sha256") not in allowed
        ):
            return JSONResponse({"error": "GATEWAY_CLIENT_IDENTITY"}, status_code=403)
        if not admission.acquire(blocking=False):
            return JSONResponse({"error": "GATEWAY_BUSY"}, status_code=503)
        try:
            raw = bytearray()
            try:
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw) > REQUEST_LIMIT:
                            return JSONResponse({"error": "REQUEST_LIMIT"}, status_code=413)
            except TimeoutError:
                return JSONResponse({"error": "REQUEST_TIMEOUT"}, status_code=408)
            try:
                envelope = gateway.auth.open(_decode(raw))
                if set(envelope) != {"gateway_id", "request_id", "operation", "body"}:
                    raise ValueError("Unexpected RPC fields")
                if envelope["gateway_id"] != gateway.identity:
                    raise ValueError("Wrong Gateway")
                UUID(envelope["request_id"])
                operation = envelope["operation"]
                if operation not in OPERATIONS:
                    raise ValueError("Unsupported operation")
            except ValueError, KeyError, TypeError, AttributeError:
                return JSONResponse({"error": "INVALID_REQUEST"}, status_code=400)
            binding = {key: envelope[key] for key in ("gateway_id", "request_id", "operation")}
            try:
                value = await run_in_threadpool(invoke, operation, envelope["body"])
                result = {**binding, "result": value, "error": None}
            except DomainError as exc:
                result = {**binding, "error": exc.code}
            except ValueError, KeyError, TypeError, ValidationError:
                result = {**binding, "error": "INVALID_ARGUMENT"}
            # Unexpected failures deliberately return HTTP 500: the caller must reconcile.
            return JSONResponse(gateway.auth.seal(result))
        finally:
            admission.release()

    if supervision_auth is not None:

        @app.post("/supervision")
        async def supervision(request: Request):
            if (
                allowed is not None
                and request.scope.get("state", {}).get("tls_peer_sha256") not in allowed
            ):
                return JSONResponse({"error": "GATEWAY_CLIENT_IDENTITY"}, status_code=403)
            try:
                raw = bytearray()
                async with asyncio.timeout(2):
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw) > 8192:
                            return JSONResponse({"error": "REQUEST_LIMIT"}, status_code=413)
                envelope = supervision_auth.open(_decode(raw))
                if (
                    set(envelope) != {"gateway_id", "request_id", "operation", "body"}
                    or envelope["gateway_id"] != gateway.identity
                ):
                    raise ValueError("Wrong binding")
                UUID(envelope["request_id"])
            except DomainError, ValueError, TypeError, KeyError, AttributeError, TimeoutError:
                return JSONResponse({"error": "INVALID_SUPERVISION"}, status_code=403)
            binding = {key: envelope[key] for key in ("gateway_id", "request_id", "operation")}
            try:
                edge = gateway.simulator.edge
                if envelope["operation"] == "edge_status":
                    value = await run_in_threadpool(edge.status, envelope["body"]["command_id"])
                elif envelope["operation"] == "edge_heartbeat":
                    value = await run_in_threadpool(edge.pulse, envelope["body"])
                else:
                    raise ValueError("Unsupported supervision operation")
                result = {**binding, "result": value, "error": None}
            except DomainError as exc:
                result = {**binding, "error": exc.code}
            except ValueError, TypeError, KeyError:
                result = {**binding, "error": "SUPERVISION_ARGUMENT_INVALID"}
            return JSONResponse(supervision_auth.seal(result))

    if maintenance_auth is not None:
        maintenance = GatewayMaintenance(gateway)

        @app.post("/maintenance")
        async def maintenance_rpc(request: Request):
            if (
                allowed is not None
                and request.scope.get("state", {}).get("tls_peer_sha256") not in allowed
            ):
                return JSONResponse({"error": "GATEWAY_CLIENT_IDENTITY"}, status_code=403)
            try:
                raw = bytearray()
                async with asyncio.timeout(2):
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw) > 16384:
                            return JSONResponse({"error": "REQUEST_LIMIT"}, status_code=413)
                envelope = maintenance_auth.open(_decode(raw))
                if (
                    set(envelope) != {"gateway_id", "request_id", "operation", "body"}
                    or envelope["gateway_id"] != gateway.identity
                ):
                    raise ValueError("Wrong binding")
                UUID(envelope["request_id"])
            except DomainError, ValueError, TypeError, KeyError, AttributeError, TimeoutError:
                return JSONResponse({"error": "INVALID_MAINTENANCE"}, status_code=403)
            binding = {key: envelope[key] for key in ("gateway_id", "request_id", "operation")}
            try:
                if envelope["operation"] == "edge_review" and envelope["body"] is None:
                    value = await run_in_threadpool(maintenance.snapshot)
                elif envelope["operation"] == "edge_acknowledge":
                    value = await run_in_threadpool(maintenance.acknowledge, envelope["body"])
                else:
                    raise ValueError("Unsupported maintenance operation")
                result = {**binding, "result": value, "error": None}
            except DomainError as exc:
                result = {**binding, "error": exc.code}
            except ValueError, TypeError, KeyError, ValidationError:
                result = {**binding, "error": "MAINTENANCE_ARGUMENT_INVALID"}
            return JSONResponse(maintenance_auth.seal(result))

    return app
