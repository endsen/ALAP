"""Explicit PostgreSQL migrations; no implicit startup migration or credential file."""

import os

from alembic import context
from sqlalchemy import create_engine

url = os.environ["ALAP_DATABASE_URL"]
if not url.startswith("postgresql+psycopg://"):
    raise ValueError("ALAP_DATABASE_URL must use postgresql+psycopg")
with create_engine(url).connect() as connection:
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
