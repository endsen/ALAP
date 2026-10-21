"""Run the backend gate against disposable test DBs in the local TLS simulation stack."""

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="reports/d12c2-compose-backend-validation.txt")
    args = parser.parse_args()
    directory = Path(os.environ.get("SIM_ROOT", ROOT / ".local-deploy/simulation"))
    password = (directory / "postgres.password").read_text().strip()
    ca = str(directory / "ca.crt")
    query = urlencode({"sslmode": "verify-full", "sslrootcert": ca})
    base = f"postgresql://postgres:{quote(password, safe='')}@127.0.0.1:55432/"
    database = "alap_test_compose_" + secrets.token_hex(6)
    broker = urlsplit(json.loads((directory / "outbox.json").read_text())["nats_url"])
    broker_url = f"tls://{broker.username}:{broker.password}@127.0.0.1:54222"
    env = os.environ | {
        "ALAP_TEST_DATABASE_URL": base + database + "?" + query,
        "ALAP_TEST_NATS_URL": broker_url,
        "SSL_CERT_FILE": ca,
    }
    report = ROOT / args.report
    raw = ROOT / ".local-deploy/backend-gate.raw"
    with psycopg.connect(base + "postgres?" + query, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            with raw.open("w") as output:
                raw.chmod(0o600)
                result = subprocess.run(
                    [sys.executable, "scripts/check.py"],
                    cwd=ROOT,
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
    text = raw.read_text().replace(password, "[REDACTED]")
    if broker.password:
        text = text.replace(broker.password, "[REDACTED]")
    report.write_text(text)
    raw.unlink()
    print(f"Backend gate exit {result.returncode}; report: {report.relative_to(ROOT)}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
