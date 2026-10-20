"""Prepare a new private simulation directory; never overwrite existing secrets."""

import argparse
import ipaddress
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[2]


def write(root, name, value, mode=0o600):
    path = root / name
    with path.open("xb") as file:
        file.write(value if isinstance(value, bytes) else value.encode())
    path.chmod(mode)


def prepare(root):
    root.mkdir(mode=0o700, parents=False)
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ALAP local simulation CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, None, None),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .sign(ca_key, hashes.SHA256())
    )
    write(root, "ca.crt", ca.public_bytes(serialization.Encoding.PEM), 0o444)
    for name in ("postgres", "nats", "gateway", "engine-client", "api-client"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        client = name.endswith("-client")
        sans = [x509.DNSName(name)]
        if name in {"postgres", "nats"}:
            sans += [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
            .add_extension(
                x509.KeyUsage(True, False, True, False, False, False, False, None, None),
                critical=True,
            )
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(
                x509.ExtendedKeyUsage(
                    [ExtendedKeyUsageOID.CLIENT_AUTH if client else ExtendedKeyUsageOID.SERVER_AUTH]
                ),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        write(root, name + ".crt", cert.public_bytes(serialization.Encoding.PEM), 0o444)
        write(
            root,
            name + ".key",
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            # PostgreSQL copies this single mounted secret into its private data
            # directory as the postgres user. The host parent remains 0700.
            0o444 if name == "postgres" else 0o600,
        )
    password = secrets.token_urlsafe(36)
    write(root, "postgres.password", password, 0o444)
    write(
        root,
        "admin.dsn",
        make_conninfo(
            host="postgres",
            port=5432,
            dbname="postgres",
            user="postgres",
            password=password,
            sslmode="verify-full",
            sslrootcert="/config/ca.crt",
            connect_timeout=10,
        ),
    )
    write(root, "master.key", Fernet.generate_key())
    write(root, "gateway.signing", secrets.token_bytes(32))
    nats_password = secrets.token_urlsafe(36)
    write(
        root,
        "nats.conf",
        f'''port: 4222
http_port: 8222
jetstream {{ store_dir: /data }}
authorization {{ user: events, password: "{nats_password}" }}
tls {{ cert_file: /config/nats.crt, key_file: /run/secrets/nats.key }}
''',
    )
    example = json.loads((ROOT / "contracts/examples/plan_revision.json").read_text())
    common = {
        "mode": "simulation",
        "execution_skills": json.loads(
            (ROOT / "contracts/examples/simulator_skills.json").read_text()
        ),
        "policy_versions": example["policy_versions"],
        "capability_versions": example["capability_versions"],
        "artifact_root": "/artifacts",
        "engine_actor": "engine",
        "poll_s": 0.5,
    }
    for component in ("api", "engine", "agent"):
        settings = dict(common)
        if component != "agent":
            settings["gateway_transport"] = {
                "signing_key_file": "/run/secrets/gateway.signing",
                "endpoints": {
                    "gw": {
                        "url": "https://gateway:8091",
                        "ca_file": "/config/ca.crt",
                        "client_cert_file": f"/config/{component}-client.crt",
                        "client_key_file": f"/run/secrets/{component}-client.key",
                    }
                },
            }
        else:
            settings.update(agent_actor="worker", experiment_ids=["EXP-SIM-001"])
        write(root, component + ".json", json.dumps(settings))
    write(
        root,
        "gateway.json",
        json.dumps(
            common
            | {
                "gateway_id": "gw",
                "journal_path": "/data/journal.sqlite",
                "physical_path": "/data/physical.sqlite",
                "signing_key_file": "/run/secrets/gateway.signing",
            }
        ),
    )
    write(
        root,
        "outbox.json",
        json.dumps(
            {
                "events_actor": "events",
                "nats_url": f"tls://events:{nats_password}@nats:4222",
                "stream": "ALAP_EVENTS",
                "subject": "alap.events",
                "poll_s": 0.5,
            }
        ),
    )
    write(root, "prepared", "simulation only; no model credentials or device approvals\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    prepare(args.directory.resolve())
    print("Private simulation files prepared; no services started")
