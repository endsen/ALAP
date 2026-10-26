"""Security boundaries of generated local deployment material (no Docker dependency)."""

import json
import runpy
import stat
from pathlib import Path

import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import ExtendedKeyUsageOID

ROOT = Path(__file__).resolve().parents[1]
prepare = runpy.run_path(str(ROOT / "deploy/simulation/prepare.py"))["prepare"]


def test_prepare_refuses_existing_directory(tmp_path):
    marker = tmp_path / "must-not-change"
    marker.write_text("existing deployment")
    with pytest.raises(FileExistsError):
        prepare(tmp_path)
    assert marker.read_text() == "existing deployment"
    assert list(tmp_path.iterdir()) == [marker]


def test_private_secrets_and_distinct_certificate_purposes(tmp_path):
    root = tmp_path / "private"
    prepare(root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for name in ("master.key", "admin.dsn", "gateway.signing", "api-client.key", "outbox.json"):
        assert stat.S_IMODE((root / name).stat().st_mode) == 0o600
    ca = x509.load_pem_x509_certificate((root / "ca.crt").read_bytes())
    for name, purpose in (
        ("gateway", ExtendedKeyUsageOID.SERVER_AUTH),
        ("engine-client", ExtendedKeyUsageOID.CLIENT_AUTH),
    ):
        cert = x509.load_pem_x509_certificate((root / (name + ".crt")).read_bytes())
        cert.verify_directly_issued_by(ca)
        assert list(cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value) == [
            purpose
        ]

    def pin(name):
        return (
            x509.load_pem_x509_certificate((root / f"{name}.crt").read_bytes())
            .fingerprint(hashes.SHA256())
            .hex()
        )

    for component in ("api", "engine"):
        settings = json.loads((root / f"{component}.json").read_text())
        assert settings["gateway_transport"]["endpoints"]["gw"]["server_sha256"] == pin("gateway")
    settings = json.loads((root / "gateway.json").read_text())
    assert settings["client_sha256"] == [pin("engine-client"), pin("api-client")]
    assert not (root / "ca.key").exists()
    assert not (root / "deployment").exists()  # Preparing files must not provision a database.
    agent = json.loads((root / "agent.json").read_text())
    assert "gateway_transport" not in agent
    assert agent["mode"] == "simulation"


def test_compose_agent_cannot_mount_execution_or_maintenance_credentials():
    stack = yaml.safe_load((ROOT / "deploy/simulation/compose.yaml").read_text())
    services = stack["services"]
    for component in ("api", "engine", "agent", "outbox"):
        mounts = services[component]["volumes"]
        assert any(f"/components/{component}.dsn:" in mount for mount in mounts)
        assert not any("migration.dsn" in mount or "admin.dsn" in mount for mount in mounts)
    for component in ("agent", "outbox"):
        assert "devices" not in services[component]["networks"]
        assert not any("gateway.signing" in mount for mount in services[component]["volumes"])
    assert services["web"]["ports"] == ["127.0.0.1:${WEB_PORT:-3000}:3000"]
    assert all(
        isinstance(value, str) and value.startswith("/") for value in services["agent"]["tmpfs"]
    )
