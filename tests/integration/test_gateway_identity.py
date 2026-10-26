"""Independent mTLS Gateway: same-CA identity substitution and resource denial."""

import ipaddress
import json
import secrets
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from alap.adapters.gateway.config import build_gateway_ports
from alap.adapters.gateway.transport import HTTPGateway
from alap.domain.rules import DomainError

from .conftest import rows
from .test_execution import execution, prepare  # noqa: F401

pytestmark = pytest.mark.postgres


def certificates(root):
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "identity test CA")])

    def builder(subject, key):
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=1))
        )

    ca = (
        builder(name, ca_key)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, None, None), True
        )
        .sign(ca_key, hashes.SHA256())
    )
    (root / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    pins = {}
    for identity in ("gateway", "other-gateway", "engine", "other-client"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        client = identity in {"engine", "other-client"}
        cert = (
            builder(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, identity)]), key)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                False,
            )
            .add_extension(
                x509.ExtendedKeyUsage(
                    [ExtendedKeyUsageOID.CLIENT_AUTH if client else ExtendedKeyUsageOID.SERVER_AUTH]
                ),
                False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        cert.verify_directly_issued_by(ca)
        (root / f"{identity}.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        private = root / f"{identity}.key"
        private.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        private.chmod(0o600)
        pins[identity] = cert.fingerprint(hashes.SHA256()).hex()
    return pins


@pytest.mark.parametrize("fault", ["wrong-server", "wrong-client", "unmapped-resource", "none"])
def test_certificate_and_resource_bindings_before_physical_write(
    execution,  # noqa: F811
    tmp_path,
    fault,
):
    engine, gateway, simulator, _, scenario = execution
    command = prepare(execution)
    pins = certificates(tmp_path)
    gateway.close()
    key_file = tmp_path / "signing.key"
    # Use the actual fixture authenticator through a new explicit test key.
    key_file.write_bytes(secrets.token_bytes(32))
    key_file.chmod(0o600)
    from alap.adapters.gateway.auth import Authenticator

    engine.auth = Authenticator(key_file.read_bytes())
    server_identity = "other-gateway" if fault == "wrong-server" else "gateway"
    config = {
        "mode": "simulation",
        "gateway_id": "gw",
        "signing_key_file": str(key_file),
        "journal_path": str(gateway.path),
        "physical_path": str(simulator.path),
        "execution_skills": gateway.skills,
        "policy_versions": dict(gateway.policies),
        "capability_versions": dict(gateway.capabilities),
        "client_sha256": [pins["engine"]],
    }
    if fault == "unmapped-resource":
        config["policy_versions"].pop("sim-temp")
        config["capability_versions"].pop("sim-temp")
    path = tmp_path / "gateway.json"
    path.write_text(json.dumps(config))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"https://127.0.0.1:{port}"

    def context(identity):
        result = ssl.create_default_context(cafile=str(tmp_path / "ca.crt"))
        result.load_cert_chain(tmp_path / f"{identity}.crt", tmp_path / f"{identity}.key")
        return result

    ready = HTTPGateway(
        "gw", url, engine.auth, tls_context=context("engine"), server_sha256=pins[server_identity]
    )
    client_identity = "other-client" if fault == "wrong-client" else "engine"
    _, engine.gateways = build_gateway_ports(
        {
            "signing_key_file": str(key_file),
            "endpoints": {
                "gw": {
                    "url": url,
                    "ca_file": str(tmp_path / "ca.crt"),
                    "client_cert_file": str(tmp_path / f"{client_identity}.crt"),
                    "client_key_file": str(tmp_path / f"{client_identity}.key"),
                    "server_sha256": pins["gateway"],
                }
            },
        }
    )
    log_path = tmp_path / "gateway.log"
    with log_path.open("wb") as log:
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "alap.adapters.gateway.server",
                "--config",
                str(path),
                "--port",
                str(port),
                "--cert",
                str(tmp_path / f"{server_identity}.crt"),
                "--key",
                str(tmp_path / f"{server_identity}.key"),
                "--client-ca",
                str(tmp_path / "ca.crt"),
            ],
            stdout=log,
            stderr=log,
        )
    try:
        deadline = time.monotonic() + 30
        while True:
            assert child.poll() is None, log_path.read_text()
            try:
                ready.challenge()
                break
            except ConnectionError:
                assert time.monotonic() < deadline, log_path.read_text()
                time.sleep(0.05)
        if fault == "none":
            engine.dispatch("engine", command)
            expected = 1
        else:
            error = DomainError if fault == "unmapped-resource" else ConnectionError
            with pytest.raises(error):
                engine.dispatch("engine", command)
            assert rows(scenario[3], "SELECT state FROM command_ledger") == [{"state": "UNKNOWN"}]
            expected = 0
        assert simulator.action_count(command) == expected
        with sqlite3.connect(gateway.path) as journal:
            assert journal.execute("SELECT count(*) FROM commands").fetchone()[0] == expected
        # A valid connection before/after the rogue peer must not lend it identity.
        assert engine.auth.open(ready.challenge())["gateway_id"] == "gw"
        if fault == "wrong-client":
            with pytest.raises(ConnectionError):
                engine.gateways["gw"].challenge()
        assert child.poll() is None
    finally:
        child.terminate()
        assert child.wait(timeout=10) == 0, log_path.read_text()
