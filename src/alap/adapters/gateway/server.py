"""Independent simulation Gateway process; never instantiates a hardware driver."""

import argparse
import ipaddress
import json
import signal
import ssl
from pathlib import Path

import uvicorn

from alap.adapters.gateway.auth import Authenticator
from alap.adapters.gateway.journal import Gateway
from alap.adapters.gateway.simulator import Simulator, WallClock
from alap.adapters.gateway.supervised import SupervisedSimulator
from alap.adapters.gateway.tls import PeerIdentityProtocol
from alap.adapters.gateway.transport import create_gateway_app
from alap.contracts import ContractCatalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--client-ca")
    args = parser.parse_args()
    local = ipaddress.ip_address(args.host).is_loopback
    tls = (args.cert, args.key, args.client_ca)
    if (any(tls) and not all(tls)) or (not local and not all(tls)):
        parser.error("Non-loopback listeners require --cert, --key and --client-ca (mTLS)")
    settings = json.loads(args.config.read_text())
    if settings["mode"] != "simulation":
        parser.error("Only explicit simulation mode is implemented")
    clients = settings.get("client_sha256")
    if all(tls) and not clients:
        parser.error("mTLS requires registered client_sha256 identities")
    if clients is not None and not all(tls):
        parser.error("Client certificate identities require mTLS")
    journal = Path(settings["journal_path"]).resolve()
    physical = Path(settings["physical_path"]).resolve()
    if journal == physical:
        parser.error("Journal and simulated physical state require separate files")
    # Raw random bytes: stripping whitespace would corrupt some valid random keys.
    auth = Authenticator(Path(settings["signing_key_file"]).read_bytes())
    simulator = Simulator(physical, WallClock())
    supervision_auth = None
    maintenance_auth = None
    if config := settings.get("supervision"):
        edge_path = Path(config["state_path"]).resolve()
        if edge_path in {journal, physical}:
            parser.error("Monitor state requires a separate file")
        key = Path(config["heartbeat_key_file"]).read_bytes()
        if key == Path(settings["signing_key_file"]).read_bytes():
            parser.error("Engine heartbeat requires a separate key")
        supervision_auth = Authenticator(key)
        simulator = SupervisedSimulator(
            physical, WallClock(), edge_path, config["sample_interval_s"]
        )
        simulator.edge.snapshot()
        if maintenance_file := config.get("maintenance_key_file"):
            maintenance_key = Path(maintenance_file).read_bytes()
            if maintenance_key in {key, Path(settings["signing_key_file"]).read_bytes()}:
                parser.error("Maintenance requires an independent API-only key")
            maintenance_auth = Authenticator(maintenance_key)
    gateway = Gateway(
        settings["gateway_id"],
        journal,
        authenticator=auth,
        catalog=ContractCatalog(Path(__file__).resolve().parents[4] / "contracts"),
        simulator=simulator,
        skills=settings["execution_skills"],
        policy_versions=settings["policy_versions"],
        capability_versions=settings["capability_versions"],
    )

    def terminated(signum, frame):
        # Uvicorn re-raises captured signals after graceful shutdown. Preserve
        # Python finally cleanup instead of invoking the OS default SIGTERM exit.
        raise SystemExit(0)

    previous = signal.signal(signal.SIGTERM, terminated)
    try:
        uvicorn.run(
            create_gateway_app(
                gateway,
                client_sha256=clients,
                supervision_auth=supervision_auth,
                maintenance_auth=maintenance_auth,
            ),
            http=PeerIdentityProtocol,
            host=args.host,
            port=args.port,
            access_log=False,
            timeout_graceful_shutdown=70,
            ssl_certfile=args.cert,
            ssl_keyfile=args.key,
            ssl_ca_certs=args.client_ca,
            ssl_cert_reqs=ssl.CERT_REQUIRED if all(tls) else ssl.CERT_NONE,
        )
    finally:
        gateway.close()
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    main()
