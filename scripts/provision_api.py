"""Trusted local identity bootstrap. Writes a short-lived token to a new private file."""

import argparse
import os
from pathlib import Path

from alap.adapters.postgres.api import PostgresAPIStore
from alap.adapters.postgres.settings import database_url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", required=True)
    parser.add_argument("--role", choices=["admin", "researcher", "observer"], required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    store = PostgresAPIStore(database_url())
    # Exclusive creation first; never overwrite a user's existing credential file.
    fd = os.open(args.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with store.connect() as db:
            db.execute(
                "INSERT INTO principals(id,issuer,external_subject,kind) "
                "VALUES (%s,'alap-local',%s,'user') ON CONFLICT DO NOTHING",
                (args.actor, args.actor),
            )
            db.execute(
                "INSERT INTO platform_roles VALUES (%s,%s) "
                "ON CONFLICT(actor_id) DO UPDATE SET role=excluded.role",
                (args.actor, args.role),
            )
        token = store.issue_token(args.actor)
        with os.fdopen(fd, "w") as file:
            fd = None
            file.write(token + "\n")
        print(
            "Provisioned local identity; token written to the requested private file (1 hour TTL)."
        )
    finally:
        if fd is not None:
            os.close(fd)


if __name__ == "__main__":
    main()
