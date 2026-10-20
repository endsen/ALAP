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
        )
    return auth, ports
