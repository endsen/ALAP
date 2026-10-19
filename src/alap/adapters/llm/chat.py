"""OpenAI and DeepSeek Chat Completions normalization with fail-closed proposals."""

import http.client
import json
import math
import re
import time
from collections.abc import Iterator
from threading import Event
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from alap.application.models import (
    ModelEvent,
    ModelMessage,
    ModelProfile,
    ModelRequest,
    ProviderConnection,
)

from .transport import EnvironmentSecrets, HTTPSChatTransport, ModelFailure, endpoint


def strict_json(value):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ModelFailure("invalid_structure")
            result[key] = value
        return result

    def constant(_):
        raise ModelFailure("invalid_structure")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)


def schema(value):
    result = strict_json(value)
    Draft202012Validator.check_schema(result)

    # Only local references. Schema validation must never initiate network I/O.
    def check(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key in {"$ref", "$dynamicRef"} and not str(child).startswith("#"):
                    raise ModelFailure("invalid_request")
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)

    check(result)
    return result


def safe_id(value, secret):
    if isinstance(value, str) and secret not in value and re.fullmatch(r"[\w.:-]{1,200}", value):
        return value
    return None


def sse(lines, limit, check):
    parts = []
    size = 0
    for raw in lines:
        check()
        size += len(raw)
        if size > limit:
            raise ModelFailure("response_limit")
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if parts:
                yield "\n".join(parts)
                parts = []
        elif line.startswith("data:"):
            parts.append(line[5:].removeprefix(" "))
    if parts:
        raise ModelFailure("invalid_structure")


class ChatModelClient:
    def __init__(
        self, connection: ProviderConnection, profile: ModelProfile, *, secrets=None, transport=None
    ):
        self.connection = connection
        self.profile = profile
        self.secrets = secrets or EnvironmentSecrets()
        self.transport = transport or HTTPSChatTransport()

    def _prepare(self, request):
        c, p = self.connection, self.profile
        endpoint(c)
        if not c.enabled:
            raise ModelFailure("unavailable")
        if (p.connection_id, p.connection_version) != (c.id, c.version):
            raise ModelFailure("config_version_mismatch")
        numbers = (p.timeout_seconds, request.total_seconds)
        if (
            any(not math.isfinite(n) or n <= 0 for n in numbers)
            or not 1 <= p.max_attempts <= 3
            or not 0 < p.output_tokens < p.context_tokens
            or min(c.version, p.version, request.max_response_bytes, request.token_budget) <= 0
            or not p.model
            or not request.trace_id
            or not request.messages
            or p.temperature is not None
            and not 0 <= p.temperature <= 2
        ):
            raise ModelFailure("invalid_request")
        required = ["streaming"]
        if request.tools:
            required.append("tools")
        if request.output_schema_json:
            required.append("structured")
            if not request.json_object_mode:
                raise ModelFailure("unsupported")
        for capability in required:
            if getattr(p.capabilities, capability) not in {"tested", "declared"}:
                raise ModelFailure("unsupported")
        if request.json_object_mode and not request.output_schema_json:
            raise ModelFailure("invalid_request")
        if request.tools and request.output_schema_json:
            raise ModelFailure("unsupported")
        messages = []
        pending = set()
        used = set()
        for message in request.messages:
            if not isinstance(message, ModelMessage):
                if message[0] == "tool":
                    raise ModelFailure("unsupported")
                message = ModelMessage(*message)
            role, content = message.role, message.content
            if role not in {"system", "user", "assistant", "tool"} or not isinstance(content, str):
                raise ModelFailure("unsupported")
            item = {"role": role, "content": content}
            if role == "tool":
                if message.tool_call_id not in pending or message.tool_calls:
                    raise ModelFailure("invalid_request")
                pending.remove(message.tool_call_id)
                item["tool_call_id"] = message.tool_call_id
            else:
                if pending or message.tool_call_id is not None:
                    raise ModelFailure("invalid_request")
                if message.tool_calls:
                    if role != "assistant":
                        raise ModelFailure("invalid_request")
                    item["tool_calls"] = []
                    for call in message.tool_calls:
                        if not call.id or call.id in used or not call.name:
                            raise ModelFailure("invalid_request")
                        strict_json(call.arguments_json)
                        used.add(call.id)
                        pending.add(call.id)
                        item["tool_calls"].append(
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {"name": call.name, "arguments": call.arguments_json},
                            }
                        )
            messages.append(item)
        if pending:
            raise ModelFailure("invalid_request")
        tools = {}
        for tool in request.tools:
            if tool.name in tools or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]{0,63}", tool.name):
                raise ModelFailure("invalid_request")
            tools[tool.name] = schema(tool.schema_json)
        output = schema(request.output_schema_json) if request.output_schema_json else None
        payload = {
            "model": p.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        # Vendor-specific output limit; no hidden reasoning or model fallback.
        payload["max_completion_tokens" if c.vendor == "openai" else "max_tokens"] = p.output_tokens
        if p.temperature is not None:
            payload["temperature"] = p.temperature
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": tools[t.name],
                    },
                }
                for t in request.tools
            ]
        if output is not None:
            payload["response_format"] = {"type": "json_object"}
        # Byte count plus framing reserve intentionally overestimates text token use.
        reservation = len(json.dumps(payload, ensure_ascii=False).encode()) + 256 + p.output_tokens
        if reservation > p.context_tokens:
            raise ModelFailure("context_limit")
        if reservation > request.token_budget:
            raise ModelFailure("budget_exceeded")
        return payload, tools, output, reservation

    def stream(self, request: ModelRequest, cancel: Event | None = None) -> Iterator[ModelEvent]:
        cancel = cancel or Event()
        c, p = self.connection, self.profile
        start = time.monotonic()
        attempt_id = "preflight"
        actual_model = p.model

        def event(kind, **data):
            return ModelEvent(kind, request.trace_id, attempt_id, c.vendor, actual_model, data)

        def check():
            if cancel.is_set():
                raise ModelFailure("cancelled")
            if time.monotonic() - start >= request.total_seconds:
                raise ModelFailure("timeout")

        try:
            check()
            payload, tools, output, reservation = self._prepare(request)
            secret = self.secrets.resolve(c.secret_ref)
        except ModelFailure as exc:
            yield event("error", code=exc.code)
            return
        except ValueError, TypeError, SchemaError, RecursionError:
            yield event("error", code="invalid_request")
            return
        spent = 0
        for number in range(1, p.max_attempts + 1):
            attempt_id = str(uuid4())
            actual_model = p.model
            began = time.monotonic()
            emitted = False
            request_id = None
            usage = None
            try:
                check()
                if spent + reservation > request.token_budget:
                    raise ModelFailure("budget_exceeded")
                spent += reservation
                yield event(
                    "attempt",
                    number=number,
                    profile_id=p.id,
                    profile_version=p.version,
                    connection_version=c.version,
                    reserved_tokens=reservation,
                )
                timeout = min(p.timeout_seconds, request.total_seconds - (time.monotonic() - start))
                with self.transport.open(c, secret, payload, timeout, cancel) as response:
                    request_id = safe_id(response.request_id, secret)
                    status = response.status
                    if status != 200:
                        code = {
                            401: "authentication",
                            403: "authentication",
                            429: "rate_limit",
                            408: "timeout",
                        }.get(status, "provider")
                        if status == 400:
                            body = bytearray()
                            for line in response.lines:
                                check()
                                body.extend(line)
                                if len(body) > 16384:
                                    break
                            try:
                                remote_code = strict_json(body).get("error", {}).get("code")
                                if remote_code in {
                                    "context_length_exceeded",
                                    "context_window_exceeded",
                                }:
                                    code = "context_limit"
                                elif remote_code == "unsupported_parameter":
                                    code = "unsupported"
                            except ValueError, TypeError, AttributeError, ModelFailure:
                                pass
                        raise ModelFailure(code, retryable=status in {429, 408, 500, 502, 503, 504})
                    text = ""
                    calls = {}
                    finished = None
                    observed_model = None
                    done = False

                    def stream_check(began=began, timeout=timeout):
                        check()
                        if time.monotonic() - began >= timeout:
                            raise ModelFailure("timeout")

                    for data in sse(response.lines, request.max_response_bytes, stream_check):
                        if data == "[DONE]":
                            done = True
                            break
                        chunk = strict_json(data)
                        if "error" in chunk:
                            raise ModelFailure("provider")
                        model = safe_id(chunk.get("model"), secret)
                        if not model or (observed_model is not None and model != observed_model):
                            raise ModelFailure("invalid_structure")
                        actual_model = model
                        observed_model = model
                        if chunk.get("usage") is not None:
                            candidate = chunk["usage"]
                            keys = ("prompt_tokens", "completion_tokens", "total_tokens")
                            if any(
                                type(candidate.get(k)) is not int or candidate[k] < 0 for k in keys
                            ):
                                raise ModelFailure("invalid_structure")
                            if candidate["total_tokens"] != sum(candidate[k] for k in keys[:2]):
                                raise ModelFailure("invalid_structure")
                            usage = {k: candidate[k] for k in keys}
                        choices = chunk.get("choices")
                        if not isinstance(choices, list) or len(choices) > 1:
                            raise ModelFailure("invalid_structure")
                        if not choices:
                            continue
                        choice = choices[0]
                        if choice.get("index") != 0 or finished is not None:
                            raise ModelFailure("invalid_structure")
                        delta = choice.get("delta", {})
                        if delta.get("refusal"):
                            raise ModelFailure("refusal")
                        content = delta.get("content")
                        if content:
                            if not isinstance(content, str):
                                raise ModelFailure("invalid_structure")
                            text += content
                            emitted = True
                            yield event("text_delta", text=content)
                        for part in delta.get("tool_calls") or []:
                            index = part["index"]
                            if type(index) is not int or not 0 <= index < 128:
                                raise ModelFailure("invalid_structure")
                            call = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                            if part.get("id"):
                                if call["id"]:
                                    raise ModelFailure("invalid_structure")
                                call["id"] = part["id"]
                            function = part.get("function", {})
                            for key in ("name", "arguments"):
                                value = function.get(key) or ""
                                if not isinstance(value, str):
                                    raise ModelFailure("invalid_structure")
                                call[key] += value
                            emitted = True
                            yield event(
                                "tool_call_delta",
                                index=index,
                                arguments=function.get("arguments", ""),
                                executable=False,
                            )
                        finished = choice.get("finish_reason")
                    stream_check()
                    if not done or finished not in {"stop", "tool_calls"}:
                        raise ModelFailure(
                            "refusal" if finished == "content_filter" else "invalid_structure"
                        )
                    if bool(calls) != (finished == "tool_calls"):
                        raise ModelFailure("invalid_structure")
                    validated = []
                    seen = set()
                    for call in calls.values():
                        call_id = safe_id(call["id"], secret)
                        if not call_id or call_id in seen or call["name"] not in tools:
                            raise ModelFailure("invalid_structure")
                        seen.add(call_id)
                        arguments = strict_json(call["arguments"])
                        Draft202012Validator(tools[call["name"]]).validate(arguments)
                        validated.append(
                            {"id": call_id, "name": call["name"], "arguments": arguments}
                        )
                    structured = None
                    if output is not None:
                        structured = strict_json(text)
                        Draft202012Validator(output).validate(structured)
                    check()
                    yield event("usage", known=usage is not None, tokens=usage)
                    yield event(
                        "finish",
                        reason=finished,
                        tool_proposals=validated,
                        structured=structured,
                        request_id=request_id,
                        elapsed_ms=round((time.monotonic() - began) * 1000),
                        usage=usage,
                    )
                    return
            except ModelFailure as exc:
                failure = exc
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                code = "connection"
                if isinstance(exc, TimeoutError) or time.monotonic() - began >= timeout:
                    code = "timeout"
                if cancel.is_set():
                    code = "cancelled"
                failure = ModelFailure(code, retryable=code in {"timeout", "connection"})
            except ValueError, TypeError, KeyError, AttributeError, ValidationError, RecursionError:
                failure = ModelFailure("invalid_structure")
            except Exception:
                failure = ModelFailure("invalid_structure")
            retry = failure.retryable and not emitted and number < p.max_attempts
            retry = retry and spent + reservation <= request.token_budget
            yield event(
                "error",
                code=failure.code,
                retrying=retry,
                request_id=request_id,
                elapsed_ms=round((time.monotonic() - began) * 1000),
                usage=usage,
            )
            if not retry:
                return
            # Cancellable bounded backoff; no partial stream concatenation or failover.
            cancel.wait(
                min(
                    0.25 * 2 ** (number - 1),
                    max(0, request.total_seconds - (time.monotonic() - start)),
                )
            )
