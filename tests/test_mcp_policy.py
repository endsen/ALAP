"""Numeric endpoint pins and strict local-only plaintext policy."""

from dataclasses import replace

import pytest

from alap.adapters.mcp.http import MCPConnection
from alap.domain.rules import DomainError


@pytest.mark.parametrize(
    "changes",
    [
        {"address": "127.0.0.1"},
        {"address": "10.0.0.1"},
        {"address": "169.254.169.254"},
        {"url": "http://example.org/mcp"},
        {"url": "https://user:pass@example.org/mcp"},
        {"url": "https://example.org/mcp?key=private"},
        {"url": "https://example.org/mcp#fragment"},
        {"timeout": 0},
        {"response_limit": 0},
        {"version": 0},
    ],
)
def test_unreviewed_private_destinations_and_url_credentials_are_rejected(changes):
    connection = MCPConnection("test", 1, "https://example.org/mcp", "8.8.8.8")
    with pytest.raises(DomainError):
        replace(connection, **changes).endpoint()


def test_loopback_requires_explicit_flag_and_forbids_plaintext_credentials():
    connection = MCPConnection(
        "test", 1, "http://127.0.0.1:43210/mcp", "127.0.0.1", allow_loopback=True
    )
    assert connection.endpoint().port == 43210
    with pytest.raises(DomainError):
        replace(connection, secret_ref="env:TEST_SECRET").endpoint()
    with pytest.raises(DomainError):
        replace(connection, url="http://example.org/mcp").endpoint()


@pytest.mark.parametrize("payload", ['{"id":1,"id":2}', '{"result":NaN}', '{"result":Infinity}'])
def test_rpc_rejects_ambiguous_or_nonfinite_json(payload):
    from alap.adapters.mcp.http import decode_json

    with pytest.raises(DomainError):
        decode_json(payload)


def test_credentials_echoed_by_remote_server_are_not_returned():
    from alap.adapters.mcp.http import StreamableHTTP

    class Secrets:
        def resolve(self, ref):
            return "synthetic-bearer-credential"

    connection = MCPConnection(
        "test", 1, "https://example.org/mcp", "8.8.8.8", secret_ref="env:TEST"
    )
    client = StreamableHTTP(connection, Secrets())
    with pytest.raises(DomainError) as exc:
        client._response(
            {"jsonrpc": "2.0", "id": "request", "result": {"text": "synthetic-bearer-credential"}},
            "request",
        )
    assert exc.value.code == "MCP_SECRET_ECHO"
    assert "synthetic-bearer-credential" not in str(exc.value)
