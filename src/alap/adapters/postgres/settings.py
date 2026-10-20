"""Database credentials may be mounted as a file instead of a process environment value."""

import os
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict


def database_url():
    value = os.environ.get("ALAP_DATABASE_URL")
    filename = os.environ.get("ALAP_DATABASE_URL_FILE")
    if bool(value) == bool(filename):
        raise ValueError("Set exactly one database URL or database URL file")
    result = Path(filename).read_text().strip() if filename else value
    if not result:
        raise ValueError("Database connection configuration is empty")
    return result


def migration_url(value):
    from sqlalchemy.engine import URL, make_url

    if value.startswith("postgresql+psycopg://"):
        return make_url(value)
    params = conninfo_to_dict(value)
    return URL.create(
        "postgresql+psycopg",
        username=params.pop("user", None),
        password=params.pop("password", None),
        database=params.pop("dbname", None),
        query=params,
    )
