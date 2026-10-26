"""Explicit network ports for API/engine assembly; no discovery or device grants."""

import ssl
from pathlib import Path

from alap.adapters.gateway.auth import Authenticator
from alap.adapters.gateway.transport import HTTPGateway


def build_gateway_ports(settings):
    """One simulation trust domain. Per-Gateway credentials need a later key registry."""
    auth = Authenticator(Path(settings["signing_key_file"]).read_bytes())
    ports = {}
    for identity, config in settings["endpoints"].items():
        context = None
        if config["url"].startswith("https:"):
            context = ssl.create_default_context(cafile=config["ca_file"])
            context.load_cert_chain(config["client_cert_file"], config["client_key_file"])
        ports[identity] = HTTPGateway(
            identity,
            config["url"],
            auth,
            timeout=config.get("timeout_s", 60),
            tls_context=context,
            server_sha256=config.get("server_sha256"),
        )
        ports[identity].supervision_auth = None
        if key_file := config.get("heartbeat_key_file"):
            key = Path(key_file).read_bytes()
            if key == Path(settings["signing_key_file"]).read_bytes():
                raise ValueError("Engine heartbeat requires a separate key")
            ports[identity].supervision_auth = Authenticator(key)
        ports[identity].maintenance_auth = None
        if key_file := config.get("maintenance_key_file"):
            key = Path(key_file).read_bytes()
            forbidden = [Path(settings["signing_key_file"]).read_bytes()]
            if heartbeat_file := config.get("heartbeat_key_file"):
                forbidden.append(Path(heartbeat_file).read_bytes())
            if key in forbidden:
                raise ValueError("Maintenance requires an independent API-only key")
            ports[identity].maintenance_auth = Authenticator(key)
    return auth, ports
