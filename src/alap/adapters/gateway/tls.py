"""Pinned simulation identities in addition to normal mTLS chain verification."""

import hashlib
import re

from uvicorn.protocols.http.h11_impl import H11Protocol


def fingerprint(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("A lowercase SHA-256 certificate fingerprint is required")
    return value


class PeerIdentityProtocol(H11Protocol):
    """Carry TLS-derived identity into request state, never from HTTP headers.

    This adapter is tied to the locked Uvicorn H11 protocol. Copy per connection:
    mutating the shared application state could authorize another client's socket.
    """

    def connection_made(self, transport):
        super().connection_made(transport)
        tls = transport.get_extra_info("ssl_object")
        cert = tls.getpeercert(binary_form=True) if tls else None
        self.app_state = {
            **self.app_state,
            "tls_peer_sha256": hashlib.sha256(cert).hexdigest() if cert else None,
        }
