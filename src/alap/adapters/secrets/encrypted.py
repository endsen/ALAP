"""Authenticated encryption at rest; master key supplied by the deployment environment."""

from cryptography.fernet import Fernet, InvalidToken

from alap.application.experiments import require
from alap.domain.rules import DomainError


class EncryptedSecrets:
    def __init__(self, store, key):
        self.store = store
        self.cipher = Fernet(key)

    def put(self, ref, value, expected):
        require(0 < len(value) <= 8192, "VALIDATION_ERROR", "Bounded credential required")
        # Bind ciphertext to its reference to reject swapped database values.
        encrypted = self.cipher.encrypt((ref + "\0" + value).encode())
        with self.store.connect() as db:
            if expected == -1:
                changed = db.execute(
                    """INSERT INTO api_credentials VALUES (%s,%s,0,TRUE)
                  ON CONFLICT DO NOTHING""",
                    (ref, encrypted),
                ).rowcount
            else:
                changed = db.execute(
                    """UPDATE api_credentials SET ciphertext=%s,revision=revision+1,
                  enabled=TRUE WHERE ref=%s AND revision=%s""",
                    (encrypted, ref, expected),
                ).rowcount
            require(changed == 1, "STATE_CONFLICT", "Credential revision changed")
        return {"ref": ref, "revision": expected + 1, "configured": True, "mask": "********"}

    def disable(self, ref, expected):
        with self.store.connect() as db:
            changed = db.execute(
                """UPDATE api_credentials SET enabled=FALSE,revision=revision+1
              WHERE ref=%s AND revision=%s""",
                (ref, expected),
            ).rowcount
            require(changed == 1, "STATE_CONFLICT", "Credential revision changed")
        return {"ref": ref, "revision": expected + 1, "configured": False}

    def list(self):
        with self.store.connect() as db:
            return db.execute(
                "SELECT ref,revision,enabled AS configured FROM api_credentials "
                "ORDER BY ref LIMIT 1000"
            ).fetchall()

    def resolve(self, reference):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT ciphertext FROM api_credentials WHERE ref=%s AND enabled", (reference,)
            ).fetchone()
        require(row is not None, "CREDENTIAL_UNAVAILABLE", "Credential not available")
        try:
            ref, value = self.cipher.decrypt(bytes(row["ciphertext"])).decode().split("\0", 1)
            require(ref == reference, "CREDENTIAL_UNAVAILABLE", "Credential binding mismatch")
            return value
        except (InvalidToken, ValueError) as exc:
            raise DomainError("CREDENTIAL_UNAVAILABLE", "Credential unavailable") from exc
