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
    journal = Path(settings["journal_path"]).resolve()
    physical = Path(settings["physical_path"]).resolve()
    if journal == physical:
        parser.error("Journal and simulated physical state require separate files")
    # Raw random bytes: stripping whitespace would corrupt some valid random keys.
    auth = Authenticator(Path(settings["signing_key_file"]).read_bytes())
    gateway = Gateway(
        settings["gateway_id"],
        journal,
        authenticator=auth,
        catalog=ContractCatalog(Path(__file__).resolve().parents[4] / "contracts"),
        simulator=Simulator(physical, WallClock()),
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
            create_gateway_app(gateway),
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
