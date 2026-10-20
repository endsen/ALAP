"""Explicit fresh database initialization and migration; never run by application startup."""

import argparse
import json
import os
import re
import secrets
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from alap.adapters.postgres.settings import database_url, migration_url


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"alap_[a-z0-9_]{1,32}", value):
        raise ValueError("Deployment name must match alap_[a-z0-9_]{1,32}")
    return value


def _write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(value + "\n")
        output.flush()
        os.fsync(output.fileno())


def initialize(admin_dsn, name, output):
    """Create only a new database and new roles. Failures retain recovery credentials."""
    name = _name(name)
    owner, runtime = name + "_migrator", name + "_runtime"
    output = Path(output)
    params = conninfo_to_dict(admin_dsn)
    # Copy only shared transport parameters, never admin passfiles/client identities.
    supported = {
        "host",
        "hostaddr",
        "port",
        "dbname",
        "user",
        "password",
        "connect_timeout",
        "sslmode",
        "sslrootcert",
        "channel_binding",
        "target_session_attrs",
    }
    if set(params) - supported:
        raise ValueError("Administrative DSN uses unsupported identity or session indirection")
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        if admin.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s UNION ALL "
            "SELECT 1 FROM pg_roles WHERE rolname=ANY(%s)",
            (name, [owner, runtime]),
        ).fetchone():
            raise ValueError("Database or role already exists; refusing to modify it")
        # Exclusive directory creation also prevents overwriting another deployment's secrets.
        output.mkdir(mode=0o700)
        passwords = {owner: secrets.token_urlsafe(36), runtime: secrets.token_urlsafe(36)}
        for role, filename in ((owner, "migration.dsn"), (runtime, "runtime.dsn")):
            connection = {
                **params,
                "dbname": name,
                "user": role,
                "password": passwords[role],
                "options": "-csearch_path=alap,pg_catalog",
                "connect_timeout": "5",
            }
            _write(output / filename, make_conninfo(**connection))
        manifest = {
            "version": 1,
            "database": name,
            "schema": "alap",
            "owner": owner,
            "runtime": runtime,
        }
        _write(output / "deployment.json", json.dumps(manifest, indent=2))
        with admin.transaction():
            admin.execute("SET LOCAL password_encryption='scram-sha-256'")
            for role in (owner, runtime):
                admin.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(passwords[role]))
                )
        admin.execute(
            sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0").format(
                sql.Identifier(name), sql.Identifier(owner)
            )
        )
        with psycopg.connect(make_conninfo(admin_dsn, dbname=name)) as db:
            db.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
            )
            db.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(name), sql.Identifier(runtime)
                )
            )
            db.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            db.execute(sql.SQL("CREATE SCHEMA alap AUTHORIZATION {}").format(sql.Identifier(owner)))
            for role in (owner, runtime):
                db.execute(
                    sql.SQL("ALTER ROLE {} IN DATABASE {} SET search_path=alap,pg_catalog").format(
                        sql.Identifier(role), sql.Identifier(name)
                    )
                )
            db.execute(sql.SQL("GRANT USAGE ON SCHEMA alap TO {}").format(sql.Identifier(runtime)))
            # Only explicitly granted application functions are callable by the runtime.
            db.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES FOR ROLE {} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
                ).format(sql.Identifier(owner))
            )
    _write(
        output / "initialized",
        "Initialization complete; schema revision is recorded in alembic_version",
    )
    return manifest


def migrate(directory):
    """Explicit schema upgrade under the migration role, then refresh runtime grants."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    directory = Path(directory)
    if not (directory / "initialized").is_file():
        raise ValueError("Incomplete initialization; administrator inspection required")
    manifest = json.loads((directory / "deployment.json").read_text())
    name = _name(manifest["database"])
    if manifest != {
        "version": 1,
        "database": name,
        "schema": "alap",
        "owner": name + "_migrator",
        "runtime": name + "_runtime",
    }:
        raise ValueError("Unexpected deployment manifest")
    dsn = (directory / "migration.dsn").read_text().strip()
    with psycopg.connect(dsn) as db:
        identity = db.execute("SELECT current_database(),current_user,current_schema()").fetchone()
        if identity != (name, manifest["owner"], "alap"):
            raise ValueError("Migration connection does not match manifest")
    engine = create_engine(migration_url(dsn))
    try:
        with engine.connect() as connection:
            config = Config(str(Path(__file__).resolve().parents[4] / "alembic.ini"))
            config.set_main_option(
                "script_location", str(Path(__file__).resolve().parents[4] / "migrations")
            )
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()
    with psycopg.connect(dsn) as db:
        runtime = sql.Identifier(manifest["runtime"])
        db.execute(
            sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA alap TO {}").format(
                runtime
            )
        )
        db.execute(
            sql.SQL("REVOKE INSERT,UPDATE,DELETE ON alap.alembic_version FROM {}").format(runtime)
        )
        db.execute(
            sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA alap TO {}").format(runtime)
        )
        db.execute("REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA alap FROM PUBLIC")
        db.execute(sql.SQL("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA alap TO {}").format(runtime))
        if (directory / "components").exists():
            if not (directory / "components" / "initialized").is_file():
                raise ValueError(
                    "Incomplete component provisioning requires administrator inspection"
                )
            from alap.adapters.postgres.component_roles import apply_components

            apply_components(db, manifest)


def provision_components(admin_dsn, directory):
    """One-time opt-in: replace the legacy shared runtime with four component identities."""
    from alap.adapters.postgres.component_roles import PERMISSIONS, apply_components

    directory = Path(directory)
    # Validate and upgrade the original deployment before creating any new identities.
    migrate(directory)
    manifest = json.loads((directory / "deployment.json").read_text())
    name = manifest["database"]
    roles = {component: name + "_" + component for component in PERMISSIONS}
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        owner = admin.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s", (name,)
        ).fetchone()
        if owner != (manifest["owner"],):
            raise ValueError("Administrative connection does not target deployment cluster")
        if admin.execute(
            "SELECT 1 FROM pg_roles WHERE rolname=ANY(%s)", (list(roles.values()),)
        ).fetchone():
            raise ValueError("Component role already exists")
        target = directory / "components"
        target.mkdir(mode=0o700)
        params = conninfo_to_dict((directory / "runtime.dsn").read_text())
        passwords = {component: secrets.token_urlsafe(36) for component in roles}
        for component, role in roles.items():
            _write(
                target / (component + ".dsn"),
                make_conninfo(**(params | {"user": role, "password": passwords[component]})),
            )
        with admin.transaction():
            admin.execute("SET LOCAL password_encryption='scram-sha-256'")
            for component, role in roles.items():
                admin.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(passwords[component]))
                )
        with psycopg.connect((directory / "migration.dsn").read_text()) as db:
            apply_components(db, manifest)
        admin.execute(sql.SQL("ALTER ROLE {} NOLOGIN").format(sql.Identifier(manifest["runtime"])))
    _write(target / "initialized", "Component capabilities installed; legacy runtime disabled")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    init = commands.add_parser("init")
    init.add_argument("--name", required=True)
    init.add_argument("--output", type=Path, required=True)
    upgrade = commands.add_parser("migrate")
    upgrade.add_argument("--directory", type=Path, required=True)
    components = commands.add_parser("components")
    components.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "init":
            initialize(database_url(), args.name, args.output)
        elif args.operation == "components":
            provision_components(database_url(), args.directory)
        else:
            migrate(args.directory)
        print(json.dumps({"event": "database_" + args.operation + "_completed"}))
        return 0
    except Exception:
        # Never echo DSNs, generated role passwords or driver exception SQL.
        print(
            json.dumps(
                {"event": "database_" + args.operation + "_failed", "code": "DEPLOYMENT_ERROR"}
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
