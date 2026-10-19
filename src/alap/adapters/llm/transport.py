"""Small standard-library HTTPS transport; no redirects, proxies or custom hosts."""

import http.client
import json
import os
import re
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Event, Thread
from urllib.parse import urlsplit

from alap.application.models import ProviderConnection


class ModelFailure(Exception):
    """Only fixed public codes cross the adapter boundary, never remote messages."""

    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class EnvironmentSecrets:
    def resolve(self, reference: str) -> str:
        if not re.fullmatch(r"env:[A-Z][A-Z0-9_]{0,127}", reference):
            raise ModelFailure("missing_credentials")
        value = os.environ.get(reference[4:], "")
        if not value or any(c.isspace() for c in value):
            raise ModelFailure("missing_credentials")
        return value


def endpoint(connection: ProviderConnection) -> tuple[str, str]:
    allowed = {
        "openai": ("api.openai.com", "/v1"),
        "deepseek": ("api.deepseek.com", ""),
    }
    if connection.vendor not in allowed:
        raise ModelFailure("unsupported")
    host, path = allowed[connection.vendor]
    parsed = urlsplit(connection.base_url)
    valid_paths = {path, path + "/"}
    if connection.vendor == "deepseek":
        valid_paths |= {"/v1", "/v1/"}
    if (
        parsed.scheme != "https"
        or parsed.netloc != host
        or parsed.path not in valid_paths
        or parsed.query
        or parsed.fragment
        or connection.network_policy != "official-https-only"
        or connection.protocol != "chat-completions-v1"
    ):
        raise ModelFailure("endpoint_denied")
    return host, parsed.path.rstrip("/") + "/chat/completions"


@dataclass
class Response:
    status: int
    request_id: str | None
    lines: Iterator[bytes]


class HTTPSChatTransport:
    @contextmanager
    def open(self, connection, secret, payload, timeout, cancel):
        host, path = endpoint(connection)
        client = http.client.HTTPSConnection(host, timeout=timeout)
        stopped = Event()
        active_socket = [None]
        deadline = time.monotonic() + timeout

        def interrupt():
            while not stopped.wait(0.05):
                if cancel.is_set() or time.monotonic() >= deadline:
                    sock = active_socket[0] or client.sock
                    if sock is not None:
                        try:
                            sock.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                    return

        watcher = Thread(target=interrupt, daemon=True)
        watcher.start()
        try:
            client.request(
                "POST",
                path,
                json.dumps(payload).encode(),
                {"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
            )
            active_socket[0] = client.sock
            response = client.getresponse()

            # Bounded readline protects against a single hostile, unbounded SSE line.
            def lines():
                while line := response.readline(65537):
                    if len(line) > 65536:
                        raise ModelFailure("response_limit")
                    yield line

            yield Response(response.status, response.getheader("x-request-id"), lines())
        finally:
            stopped.set()
            client.close()
            watcher.join(timeout=0.1)
