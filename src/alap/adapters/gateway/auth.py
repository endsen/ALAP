"""Payload authentication, independent of the HTTP/TLS transport security boundary."""

import hashlib
import hmac

from alap.domain.rules import DomainError, freeze_revision


class Authenticator:
    def __init__(self, key: bytes):
        if len(key) < 32:
            raise ValueError("At least 256 bits of random key material required")
        self._key = key

    def seal(self, payload: dict) -> dict:
        data = freeze_revision(payload).canonical_bytes
        return {
            "payload": payload,
            "signature": hmac.new(self._key, data, hashlib.sha256).hexdigest(),
        }

    def open(self, message: dict) -> dict:
        expected = self.seal(message["payload"])["signature"]
        if not hmac.compare_digest(expected, message.get("signature", "")):
            raise DomainError("UNAUTHENTICATED", "Transport signature verification failed")
        return message["payload"]
