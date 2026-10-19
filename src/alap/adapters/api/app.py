"""Contract-driven FastAPI boundary with bounded bodies, uniform errors and durable replay."""

import asyncio
import hashlib
import hmac
import json
import re
import time
from collections import OrderedDict
from pathlib import Path
from uuid import uuid4

import yaml
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from psycopg import IntegrityError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response, StreamingResponse

from alap.application.agent_context import redact
from alap.application.experiments import require
from alap.domain.rules import DomainError

MESSAGES = {
    401: "Authentication required",
    403: "Access denied",
    404: "Resource not found",
    409: "State conflict; refresh or inspect the operation",
    422: "Request validation failed",
    429: "Request limit exceeded",
    503: "Service unavailable",
    500: "Internal service error",
}


def error_status(code):
    if code == "UNAUTHENTICATED":
        return 401
    if code == "FORBIDDEN":
        return 403
    if code == "NOT_FOUND":
        return 404
    if code == "RATE_LIMITED":
        return 429
    if code in {"INVALID_STATE", "ILLEGAL_TRANSITION", "APPROVAL_INVALID", "DATASET_NOT_COMMITTED"}:
        return 409
    if code == "SERVICE_UNAVAILABLE":
        return 503
    if any(
        word in code
        for word in ("CONFLICT", "STALE", "EXPIRED", "UNKNOWN", "RESYNC", "BUSY", "DISABLED")
    ):
        return 409
    return 422


def failure(code, request_id, status=None):
    status = status or error_status(code)
    headers = {"X-Request-ID": request_id, "Cache-Control": "no-store"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if status == 429:
        headers["Retry-After"] = "60"
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": MESSAGES[status],
                "request_id": request_id,
                "retryable": status in {429, 503},
            }
        },
        status_code=status,
        headers=headers,
    )


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return redact(value) if isinstance(value, str) else value


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "VALIDATION_ERROR", "Duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise DomainError("VALIDATION_ERROR", "Nonfinite JSON")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeDecodeError) as exc:
        raise DomainError("VALIDATION_ERROR", "Invalid JSON") from exc


def create_app(
    service, *, contract_path=None, replay_key: bytes, stream_seconds=15, rate_limit=120
):
    require(len(replay_key) >= 32, "INVALID_CONFIG", "Strong replay HMAC key required")
    contract_path = contract_path or Path(__file__).resolve().parents[4] / "contracts/openapi.yaml"
    contract = yaml.safe_load(Path(contract_path).read_text())
    app = FastAPI(title="ALAP", docs_url=None, redoc_url=None, openapi_url=None)
    app.openapi = lambda: contract
    buckets = OrderedDict()

    def resolve(node):
        while "$ref" in node:
            target = contract
            for part in node["$ref"][2:].split("/"):
                target = target[part]
            node = target
        return node

    def validate(schema, value):
        schema = dict(schema, components=contract["components"])
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)

    @app.middleware("http")
    async def boundary(request, call_next):
        identity = str(uuid4())
        request.state.request_id = identity
        try:
            authorization = request.headers.get("authorization", "")
            require(authorization.startswith("Bearer "), "UNAUTHENTICATED", "Bearer required")
            token = authorization[7:]
            principal = await run_in_threadpool(service.store.authenticate, token)
            request.state.actor, request.state.token = principal["id"], token
            now = int(time.monotonic() // 60)
            bucket = (principal["id"], now)
            buckets[bucket] = buckets.get(bucket, 0) + 1
            buckets.move_to_end(bucket)
            while len(buckets) > 10000:
                buckets.popitem(last=False)
            require(buckets[bucket] <= rate_limit, "RATE_LIMITED", "Request rate exceeded")
            # Streaming read bounds chunked requests as well as Content-Length requests.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                require(len(body) <= 1_048_576, "VALIDATION_ERROR", "Body too large")
            request._body = bytes(body)
            response = await call_next(request)
            response.headers["X-Request-ID"] = identity
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        except DomainError as exc:
            return failure(exc.code, identity)
        except Exception:
            return failure("INTERNAL_ERROR", identity, 500)

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return failure(exc.code, request.state.request_id)

    @app.exception_handler(ValidationError)
    async def validation_error(request, exc):
        return failure("VALIDATION_ERROR", request.state.request_id)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return failure("STATE_CONFLICT", request.state.request_id)

    from starlette.exceptions import HTTPException

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return failure("NOT_FOUND", request.state.request_id, 404)

    async def event_response(request, path, query):
        actor, token = request.state.actor, request.state.token
        e = path["experiment_id"]
        header = request.headers.get("last-event-id")
        require(
            header is None or re.fullmatch(r"[0-9]{1,18}", header),
            "VALIDATION_ERROR",
            "Invalid cursor",
        )
        cursor = int(header) if header is not None else query.get("after", 0)
        require(
            header is None or "after" not in query or cursor == query["after"],
            "VALIDATION_ERROR",
            "Ambiguous cursor",
        )
        await run_in_threadpool(
            service.snapshot, actor, e
        )  # Full resource scope for event payloads.
        first = await run_in_threadpool(service.events.after, actor, e, cursor)

        async def stream():
            page = first
            current = cursor
            deadline = time.monotonic() + stream_seconds
            while True:
                if await request.is_disconnected():
                    return
                try:
                    await run_in_threadpool(service.store.authenticate, token)
                    await run_in_threadpool(service.snapshot, actor, e)
                    # Fetch again after authorization; never hold the initial page across a wait.
                    page = await run_in_threadpool(service.events.after, actor, e, current)
                except DomainError as exc:
                    payload = {"code": exc.code, "request_id": request.state.request_id}
                    yield "event: stream.error\ndata: " + json.dumps(payload) + "\n\n"
                    return
                except Exception:
                    yield 'event: stream.error\ndata: {"code":"SERVICE_UNAVAILABLE"}\n\n'
                    return
                for event in page["events"]:
                    yield (
                        f"id: {event['experiment_seq']}\nevent: {event['event_type']}\ndata: "
                        + json.dumps(clean(event))
                        + "\n\n"
                    )
                current = page["next_cursor"]
                if current < page["head_cursor"]:
                    continue
                yield ": heartbeat\n\n"
                if time.monotonic() >= deadline:
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    def endpoint(operation, method):
        async def route(request: Request):
            actor, path = request.state.actor, request.path_params
            op = operation["operationId"]
            query = {}
            expected = None
            key = ""
            known_query = set()
            for original in operation.get("parameters", []):
                param = resolve(original)
                name, location = param["name"], param["in"]
                source = (
                    request.query_params
                    if location == "query"
                    else request.headers
                    if location == "header"
                    else path
                )
                if location == "query":
                    known_query.add(name)
                    require(
                        len(request.query_params.getlist(name)) <= 1,
                        "VALIDATION_ERROR",
                        "Duplicate query",
                    )
                raw = source.get(name)
                require(
                    raw is not None or not param.get("required"),
                    "VALIDATION_ERROR",
                    "Missing parameter",
                )
                if raw is None:
                    continue
                schema = param["schema"]
                if schema.get("type") == "integer":
                    require(
                        re.fullmatch(r"[0-9]{1,18}", str(raw)),
                        "VALIDATION_ERROR",
                        "Integer required",
                    )
                    raw = int(raw)
                validate(schema, raw)
                if location == "query":
                    query[name] = raw
                if name == "If-Match":
                    require(
                        re.fullmatch(r'"(?:-1|[0-9]{1,18})"', raw),
                        "VALIDATION_ERROR",
                        "Quoted revision ETag",
                    )
                    expected = int(raw[1:-1])
                if name == "Idempotency-Key":
                    key = raw
            require(set(request.query_params) <= known_query, "VALIDATION_ERROR", "Unknown query")
            body = {}
            raw = await request.body()
            if "requestBody" in operation:
                require(
                    request.headers.get("content-type", "").split(";")[0] == "application/json",
                    "VALIDATION_ERROR",
                    "JSON content type required",
                )
                body = parse_json(raw)
                validate(operation["requestBody"]["content"]["application/json"]["schema"], body)
            else:
                require(not raw, "VALIDATION_ERROR", "Unexpected request body")
            await run_in_threadpool(service.authorize, actor, op, path, body)
            if op == "streamExperimentEvents":
                return await event_response(request, path, query)
            mutation = method != "get" and op not in {"searchKnowledge", "analyzeDataset"}
            operation_key = op + ":" + json.dumps(path, sort_keys=True)
            if mutation:
                fingerprint = hmac.new(
                    replay_key,
                    json.dumps([body, expected], sort_keys=True).encode(),
                    hashlib.sha256,
                ).hexdigest()
                cached = await run_in_threadpool(
                    service.store.request_claim, actor, operation_key, key, fingerprint
                )
                if cached is not None:
                    if op == "createAgentRun":
                        await run_in_threadpool(service.store.load, actor, cached["id"])
                    return JSONResponse(cached, status_code=success_code(operation))
            try:
                result = await run_in_threadpool(
                    service.execute, actor, op, path, body, query, expected, key
                )
                if isinstance(result, bytes):
                    return Response(
                        result,
                        media_type="application/x-hdf5",
                        headers={"Content-Disposition": 'attachment; filename="dataset.h5"'},
                    )
                result = clean(jsonable_encoder(result))
                if mutation:
                    await run_in_threadpool(
                        service.store.audit, actor, op, json.dumps(path, sort_keys=True)
                    )
                    await run_in_threadpool(
                        service.store.request_finish, actor, operation_key, key, result
                    )
                headers = (
                    {"ETag": f'"{result["revision"]}"'}
                    if isinstance(result, dict) and "revision" in result
                    else {}
                )
                return JSONResponse(result, status_code=success_code(operation), headers=headers)
            except (DomainError, ValidationError, IntegrityError) as exc:
                if mutation:
                    code = (
                        exc.code
                        if isinstance(exc, DomainError)
                        else "STATE_CONFLICT"
                        if isinstance(exc, IntegrityError)
                        else "VALIDATION_ERROR"
                    )
                    await run_in_threadpool(
                        service.store.request_finish, actor, operation_key, key, error=code
                    )
                raise

        return route

    def success_code(operation):
        return next(int(code) for code in operation["responses"] if str(code).startswith("2"))

    for path, operations in contract["paths"].items():
        for method, operation in operations.items():
            app.add_api_route(
                "/api/v1" + path,
                endpoint(operation, method),
                methods=[method.upper()],
                name=operation["operationId"],
            )
    return app
