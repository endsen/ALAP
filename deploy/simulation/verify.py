"""Read-only acceptance checks against the actual running simulation containers."""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from manage import DEPLOY, ROOT, environment


def main():
    directory = Path(os.environ.get("SIM_ROOT", ROOT / ".local-deploy/simulation"))
    env = environment(directory)
    compose = [str(ROOT / ".local-deploy/bin/docker-compose"), "-f", str(DEPLOY / "compose.yaml")]
    results = []

    def check(service, code):
        subprocess.run(
            compose + ["exec", "-T", service, "python", "-"],
            input=code,
            text=True,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        results.append(service)

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = "http://127.0.0.1:" + env.get("WEB_PORT", "3000")
    deadline = time.monotonic() + 60
    while True:
        try:
            with opener.open(url, timeout=3) as response:
                assert response.status == 200
            break
        except OSError, urllib.error.URLError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    try:
        opener.open(url + "/api/v1/me", timeout=5)
        raise AssertionError("Unauthenticated API request was accepted")
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    request = urllib.request.Request(
        url + "/api/v1/me",
        headers={
            "Authorization": "Bearer " + (directory / "admin.token").read_text().strip(),
        },
    )
    with opener.open(request, timeout=10) as response:
        assert response.status == 200
    results.append("web_authenticated_proxy")
    check(
        "api",
        """
import errno, json, ssl
from pathlib import Path
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from alap.adapters.gateway.config import build_gateway_ports
from alap.adapters.gateway.transport import HTTPGateway
p=conninfo_to_dict(Path('/run/secrets/database.dsn').read_text())
with psycopg.connect(**p) as db:
    assert db.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone()[0]
    mode=db.execute("SELECT mode FROM control_generation WHERE id='current'").fetchone()[0]
    assert mode=='ACTIVE'
    assert db.execute('SELECT count(*) FROM command_ledger').fetchone()[0]==0
    published=db.execute(
        'SELECT count(*) FROM outbox_events WHERE published_at IS NOT NULL').fetchone()[0]
    assert published>0
try:
    psycopg.connect(make_conninfo(**(p | {'password':'wrong-password-for-validation'}))).close()
except psycopg.OperationalError:
    pass
else:
    raise AssertionError('Incorrect database password accepted')
try:
    psycopg.connect(make_conninfo(**(p | {'sslmode':'disable'}))).close()
except psycopg.OperationalError:
    pass
else:
    raise AssertionError('Unencrypted database connection accepted')
settings=json.loads(Path('/config/api.json').read_text())
auth, ports=build_gateway_ports(settings['gateway_transport'])
assert auth.open(ports['gw'].challenge())['gateway_id']=='gw'
try:
    HTTPGateway('gw','https://gateway:8091',auth,
        tls_context=ssl.create_default_context(cafile='/config/ca.crt')).challenge()
except ConnectionError:
    pass
else:
    raise AssertionError('Gateway accepted missing client certificate')
try:
    with open('/artifacts/permission-probe','x') as f:
        f.write('must not be writable')
except OSError as e:
    assert e.errno in (errno.EROFS,errno.EACCES)
else:
    Path('/artifacts/permission-probe').unlink()
    raise AssertionError('API artifacts mount is writable')
""",
    )
    for service, statement in (
        ("agent", "INSERT INTO command_ledger(id) VALUES ('forbidden')"),
        ("engine", "SELECT * FROM api_credentials"),
        ("outbox", "UPDATE outbox_events SET payload='{}'"),
    ):
        check(
            service,
            f"""
from pathlib import Path
import psycopg
assert not Path('/run/secrets/migration.dsn').exists()
with psycopg.connect(Path('/run/secrets/database.dsn').read_text()) as db:
    try:
        db.execute({statement!r})
    except psycopg.errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError('Component permission violation')
""",
        )
    check(
        "outbox",
        """
import asyncio,json
from pathlib import Path
import nats
async def verify():
    settings=json.loads(Path('/config/outbox.json').read_text())
    connection=await nats.connect(settings['nats_url'])
    try:
        info=await connection.jetstream().stream_info(settings['stream'])
        assert info.state.messages>0
    finally:
        await connection.close()
asyncio.run(verify())
""",
    )
    print(json.dumps({"event": "compose_acceptance_passed", "checks": results}))


if __name__ == "__main__":
    main()
