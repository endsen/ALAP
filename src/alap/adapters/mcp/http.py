"""MCP 2025-11-25 Streamable HTTP, explicit destination pins, no replay/fallback."""

import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from threading import Timer
from urllib.parse import urlsplit
from uuid import uuid4

from alap.application.experiments import require
from alap.domain.rules import DomainError, require_json_value

PROTOCOL = "2025-11-25"


def decode_json(body):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "MCP_PROTOCOL", "Duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(body, object_pairs_hook=pairs)
    require_json_value(value)
    return value


@dataclass(frozen=True)
class MCPConnection:
    id: str
    version: int
    url: str
    address: str
    secret_ref: str | None = field(default=None, repr=False)
    allow_loopback: bool = False
    timeout: float = 15
    response_limit: int = 1_048_576

    def endpoint(self):
        url = urlsplit(self.url)
        address = ipaddress.ip_address(self.address)
        require(
            url.hostname is not None
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and 0 < self.timeout <= 60
            and 0 < self.response_limit <= 4_194_304
            and self.version > 0,
            "MCP_ENDPOINT",
            "Invalid controlled endpoint",
        )
        require(
            address.is_global or (self.allow_loopback and address.is_loopback),
            "MCP_ENDPOINT",
            "Destination requires a public address or explicit loopback grant",
        )
        require(
            url.scheme == "https"
            or (
                url.scheme == "http"
                and self.allow_loopback
                and address.is_loopback
                and url.hostname in {"localhost", "127.0.0.1", "::1"}
            ),
            "MCP_ENDPOINT",
            "TLS required outside explicit local test endpoints",
        )
        require(
            not self.secret_ref or url.scheme == "https", "MCP_ENDPOINT", "Credentials require TLS"
        )
        return url


class StreamableHTTP:
    def __init__(self, connection: MCPConnection, secrets=None):
        self.config = connection
        self.secrets = secrets
        self.session = None
        self.deadline = None

    def _post(self, method, params=None, *, notification=False):
        url = self.config.endpoint()
        remaining = min(self.config.timeout, self.deadline - time.monotonic())
        require(remaining > 0, "MCP_TIMEOUT", "MCP operation deadline exceeded")
        identity = None if notification else str(uuid4())
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if identity:
            payload["id"] = identity
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
        }
        if self.session:
            headers["MCP-Session-Id"] = self.session
        if self.config.secret_ref:
            headers["Authorization"] = "Bearer " + self.secrets.resolve(self.config.secret_ref)
        conn = http.client.HTTPConnection(
            url.hostname, url.port or (443 if url.scheme == "https" else 80), timeout=remaining
        )
        sock = None
        response = None
        timer = None
        try:
            # Resolve no DNS during dispatch: connect to the admin-reviewed numeric address,
            # retaining the original hostname for TLS validation and the HTTP Host header.
            sock = socket.create_connection((self.config.address, conn.port), remaining)
            if url.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=url.hostname)
            conn.sock = sock
            remaining = min(remaining, self.deadline - time.monotonic())
            require(remaining > 0, "MCP_TIMEOUT", "MCP operation deadline exceeded")
            sock.settimeout(remaining)

            def abort():
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            timer = Timer(remaining, abort)
            timer.daemon = True
            timer.start()
            conn.request("POST", url.path or "/", json.dumps(payload), headers)
            response = conn.getresponse()
            require(
                response.status == (202 if notification else 200),
                "MCP_HTTP",
                "Remote HTTP failure; redirects and error bodies are not exposed",
            )
            session = response.getheader("MCP-Session-Id")
            if session:
                require(re.fullmatch(r"[!-~]{1,256}", session), "MCP_PROTOCOL", "Invalid session")
                require(
                    self.session is None or self.session == session,
                    "MCP_PROTOCOL",
                    "Session changed",
                )
                self.session = session
            if notification:
                return None
            content_type = response.getheader("Content-Type", "").split(";")[0]
            if content_type == "application/json":
                body = response.read(self.config.response_limit + 1)
                require(len(body) <= self.config.response_limit, "MCP_LIMIT", "Response too large")
                return self._response(decode_json(body), identity)
            require(content_type == "text/event-stream", "MCP_PROTOCOL", "Unsupported media type")
            used, parts = 0, []
            while raw := response.readline(65537):
                used += len(raw)
                require(
                    used <= self.config.response_limit and len(raw) <= 65536,
                    "MCP_LIMIT",
                    "SSE response too large",
                )
                line = raw.decode().rstrip("\r\n")
                if line.startswith("data:"):
                    parts.append(line[5:].removeprefix(" "))
                elif not line and parts:
                    data = "\n".join(parts)
                    parts = []
                    if not data:
                        continue
                    message = decode_json(data)
                    # Sampling/elicitation and asynchronous server requests are not granted.
                    if "method" in message:
                        require(
                            message["method"] == "notifications/progress" and "id" not in message,
                            "MCP_SERVER_REQUEST",
                            "Server-initiated action not authorized",
                        )
                        continue
                    return self._response(message, identity)
            raise DomainError("MCP_INTERRUPTED", "No terminal JSON-RPC response")
        except DomainError:
            raise
        except Exception:
            raise DomainError(
                "MCP_TRANSPORT", "Transport or protocol failed; no automatic replay"
            ) from None
        finally:
            if timer:
                timer.cancel()
            if response:
                response.close()
            conn.close()
            if sock:
                sock.close()

    def _response(self, value, identity):
        if self.config.secret_ref:
            secret = self.secrets.resolve(self.config.secret_ref)
            require(secret not in json.dumps(value), "MCP_SECRET_ECHO", "Credential echo rejected")
        require(
            isinstance(value, dict)
            and value.get("jsonrpc") == "2.0"
            and value.get("id") == identity
            and "error" not in value
            and isinstance(value.get("result"), dict),
            "MCP_PROTOCOL",
            "Invalid RPC response",
        )
        return value["result"]

    def initialize(self):
        self.session = None
        self.deadline = time.monotonic() + self.config.timeout
        value = self._post(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "alap", "version": "0.1.0"},
            },
        )
        require(
            value.get("protocolVersion") == PROTOCOL and "tools" in value.get("capabilities", {}),
            "MCP_VERSION",
            "Unsupported protocol or missing tools capability",
        )
        self._post("notifications/initialized", notification=True)

    def list_tools(self):
        found, cursors = [], set()
        cursor = None
        for _ in range(20):
            result = self._post("tools/list", {"cursor": cursor} if cursor else {})
            require(isinstance(result.get("tools"), list), "MCP_PROTOCOL", "Invalid tools list")
            found.extend(result["tools"])
            require(len(found) <= 200, "MCP_LIMIT", "Tool catalog too large")
            cursor = result.get("nextCursor")
            if not cursor:
                return found
            require(
                isinstance(cursor, str) and cursor not in cursors, "MCP_PROTOCOL", "Cursor cycle"
            )
            cursors.add(cursor)
        raise DomainError("MCP_LIMIT", "Too many tool pages")

    def call_tool(self, name, arguments):
        result = self._post("tools/call", {"name": name, "arguments": arguments})
        require(result.get("isError", False) is False, "MCP_TOOL_ERROR", "Remote tool failed")
        require(
            isinstance(result.get("structuredContent"), dict),
            "MCP_STRUCTURE",
            "Only structured, locally validated results are accepted",
        )
        return result["structuredContent"]
