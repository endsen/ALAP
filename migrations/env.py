"""Explicit PostgreSQL migrations; service startup never migrates implicitly."""

from alembic import context
from sqlalchemy import create_engine

from alap.adapters.postgres.settings import database_url, migration_url


def migrate(connection):
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


provided = context.config.attributes.get("connection")
if provided is not None:
    migrate(provided)
else:
    with create_engine(migration_url(database_url())).connect() as connection:
        migrate(connection)
