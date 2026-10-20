"""Authenticated Gateway RPC. Each invocation makes exactly one HTTP attempt.

HTTP is restricted to literal loopback addresses for local simulation. Remote
endpoints require verified TLS; deployments must also configure mutual TLS at
the server. The inner command/receipt signatures remain unchanged.
"""

import asyncio
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

    def __init__(self, identity, url, authenticator, *, timeout=60, tls_context=None):
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
        self.identity, self.auth = identity, authenticator
        self.origin, self.timeout, self.tls_context = parsed, timeout, tls_context

    def _call(self, operation, body=None):
        binding = {"gateway_id": self.identity, "request_id": str(uuid4()), "operation": operation}
        data = json.dumps(self.auth.seal({**binding, "body": body}), allow_nan=False).encode()
        if len(data) > REQUEST_LIMIT:
            raise DomainError("GATEWAY_REQUEST_LIMIT", "RPC request exceeds configured limit")
        origin = self.origin
        if origin.scheme == "https":
            connection = http.client.HTTPSConnection(
                origin.hostname, origin.port, timeout=self.timeout, context=self.tls_context
            )
        else:
            connection = http.client.HTTPConnection(
                origin.hostname, origin.port, timeout=self.timeout
            )
        try:
            connection.request("POST", "/rpc", data, {"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise ConnectionError("Gateway transport rejected request")
            raw = response.read(RESPONSE_LIMIT + 1)
            if len(raw) > RESPONSE_LIMIT:
                raise ConnectionError("Gateway response exceeds limit")
            result = self.auth.open(_decode(raw))
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


def create_gateway_app(gateway, *, max_window_s=30, max_samples=10000):
    """Serve one journal owner with bounded admission and explicit RPC dispatch.

    Busy requests fail rather than queue behind a device operation indefinitely.
    A disconnected caller does not cancel an already admitted physical operation.
    """
    if not math.isfinite(max_window_s) or max_window_s <= 0 or max_samples < 2:
        raise ValueError("Positive window and sample limits required")
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

    return app
