"""Real HTTP boundary, including lost responses with no transport retries."""

import asyncio
import ipaddress
import secrets
import socket
import ssl
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Thread

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse, RedirectResponse

from alap.adapters.gateway.auth import Authenticator
from alap.adapters.gateway.journal import Gateway
from alap.adapters.gateway.simulator import Simulator, WallClock
from alap.adapters.gateway.transport import HTTPGateway, create_gateway_app
from alap.domain.rules import DomainError


@contextmanager
def serve(app, **options):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    scheme = "https" if options else "http"
    url = f"{scheme}://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=5, **options)
    )
    thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("Test server did not start")
            time.sleep(0.01)
        yield url
    finally:
        server.should_exit = True
        thread.join(7)
        sock.close()
        assert not thread.is_alive()


@pytest.fixture
def gateway(tmp_path, catalog, example, skills):
    revision = example("plan_revision")
    gateway = Gateway(
        "gw",
        tmp_path / "journal.sqlite",
        authenticator=Authenticator(secrets.token_bytes(32)),
        catalog=catalog,
        simulator=Simulator(tmp_path / "physical.sqlite", WallClock()),
        skills=skills,
        policy_versions=revision["policy_versions"],
        capability_versions=revision["capability_versions"],
    )
    try:
        yield gateway
    finally:
        gateway.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "http://example.com",
        "ftp://127.0.0.1",
        "http://u:p@127.0.0.1",
        "https://example.com/rpc",
    ],
)
def test_reject_unsafe_origins(url):
    with pytest.raises(ValueError):
        HTTPGateway("gw", url, Authenticator(b"x" * 32))


def test_reject_unverified_tls():
    with pytest.raises(ValueError, match="verification"):
        HTTPGateway(
            "gw",
            "https://example.com",
            Authenticator(b"x" * 32),
            tls_context=ssl._create_unverified_context(),
        )


def test_signed_handshake_and_bounded_telemetry(gateway, example):
    with serve(create_gateway_app(gateway)) as url:
        client = HTTPGateway("gw", url, gateway.auth)
        challenge = gateway.auth.open(client.challenge())
        assert challenge["gateway_id"] == "gw"
        condition = example("stable_condition")
        condition["resource_id"] = "sim-temp"
        condition["min_duration_s"] = 0.01
        result = gateway.auth.open(client.telemetry(condition))
        assert result["windows"][0]["condition"] == condition
        condition["min_duration_s"] = 3600
        with pytest.raises(DomainError, match="GATEWAY_WINDOW_LIMIT"):
            client.telemetry(condition)
        condition["min_duration_s"] = 1
        condition["max_age_s"] = 1e-9
        with pytest.raises(DomainError, match="GATEWAY_WINDOW_LIMIT"):
            client.telemetry(condition)
        with pytest.raises(ConnectionError):
            HTTPGateway("other", url, gateway.auth).challenge()
        with pytest.raises(ConnectionError):
            HTTPGateway("gw", url, Authenticator(b"z" * 32)).challenge()


@pytest.mark.parametrize("fault", ["redirect", "binding", "signature", "disconnect"])
def test_untrusted_or_lost_response_never_retries(fault):
    auth = Authenticator(b"x" * 32)
    app, calls = FastAPI(), []

    @app.post("/rpc")
    async def rpc(request: Request):
        value = auth.open(await request.json())
        calls.append(value)
        if fault == "redirect":
            return RedirectResponse("/rpc")
        if fault == "disconnect":
            # Fail after request acceptance, just as a lost physical-action response.
            return JSONResponse({}, status_code=503)
        result = auth.seal({**value, "result": {}, "error": None})
        if fault == "binding":
            result = auth.seal({**value, "request_id": "wrong", "result": {}, "error": None})
        if fault == "signature":
            result["signature"] = "wrong"
        return JSONResponse(result)

    with serve(app) as url:
        with pytest.raises((ConnectionError, DomainError)):
            HTTPGateway("gw", url, auth).accept({"test": "one attempt"})
        assert len(calls) == 1


def test_mutual_tls_requires_client_certificate(gateway, tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ALAP test CA")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert, private = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private.chmod(0o600)
    with serve(
        create_gateway_app(gateway),
        ssl_certfile=str(cert),
        ssl_keyfile=str(private),
        ssl_ca_certs=str(cert),
        ssl_cert_reqs=ssl.CERT_REQUIRED,
    ) as url:
        context = ssl.create_default_context(cafile=str(cert))
        with pytest.raises(ConnectionError):
            HTTPGateway(
                "gw",
                url,
                gateway.auth,
                tls_context=context,
                server_sha256=certificate.fingerprint(hashes.SHA256()).hex(),
            ).challenge()
        context.load_cert_chain(cert, private)
        client = HTTPGateway(
            "gw",
            url,
            gateway.auth,
            tls_context=context,
            server_sha256=certificate.fingerprint(hashes.SHA256()).hex(),
        )
        assert gateway.auth.open(client.challenge())["gateway_id"] == "gw"


def test_timeout_never_retries():
    calls = []
    auth = Authenticator(b"x" * 32)
    app = FastAPI()

    @app.post("/rpc")
    async def delayed(request: Request):
        calls.append(await request.json())
        await asyncio.sleep(0.1)
        return {}

    with serve(app) as url:
        with pytest.raises(ConnectionError):
            HTTPGateway("gw", url, auth, timeout=0.02).accept({"test": "timeout"})
        assert len(calls) == 1


def test_invalid_requests_cannot_invoke_arbitrary_methods(gateway):
    from uuid import uuid4

    with TestClient(create_gateway_app(gateway)) as client:
        for body in ({}, {"payload": []}, {"payload": {}, "signature": []}):
            assert client.post("/rpc", json=body).status_code == 400
        envelope = gateway.auth.seal(
            {
                "gateway_id": "gw",
                "request_id": str(uuid4()),
                "operation": "close",
                "body": None,
            }
        )
        assert client.post("/rpc", json=envelope).status_code == 400
        assert gateway.auth.open(gateway.challenge())["gateway_id"] == "gw"


@pytest.mark.parametrize("pin", [None, "", "abc", "F" * 64, ["a" * 64]])
def test_https_requires_explicit_valid_gateway_certificate_binding(pin):
    with pytest.raises(ValueError, match="fingerprint"):
        HTTPGateway("gw", "https://127.0.0.1", Authenticator(b"x" * 32), server_sha256=pin)


def test_http_headers_cannot_impersonate_a_tls_client(gateway):
    pin = "a" * 64
    with TestClient(create_gateway_app(gateway, client_sha256=[pin])) as client:
        response = client.post(
            "/rpc",
            json={},
            headers={"x-client-cert-sha256": pin, "x-forwarded-client-cert": pin},
        )
        assert response.status_code == 403
        assert response.json()["error"] == "GATEWAY_CLIENT_IDENTITY"


@pytest.mark.parametrize("pins", [[], "a" * 64, [None]])
def test_gateway_rejects_invalid_client_identity_configuration(gateway, pins):
    with pytest.raises(ValueError):
        create_gateway_app(gateway, client_sha256=pins)
