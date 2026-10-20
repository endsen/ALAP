"""Secret file configuration is explicit and incompatible with a second DSN source."""

import pytest

from alap.adapters.postgres.settings import database_url, migration_url


def test_database_file_and_ambiguous_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("ALAP_DATABASE_URL", raising=False)
    monkeypatch.delenv("ALAP_DATABASE_URL_FILE", raising=False)
    with pytest.raises(ValueError):
        database_url()
    file = tmp_path / "database.dsn"
    file.write_text("dbname=test user=runtime\n")
    monkeypatch.setenv("ALAP_DATABASE_URL_FILE", str(file))
    assert database_url() == "dbname=test user=runtime"
    monkeypatch.setenv("ALAP_DATABASE_URL", "dbname=other")
    with pytest.raises(ValueError):
        database_url()
    monkeypatch.delenv("ALAP_DATABASE_URL")
    file.write_text("\n")
    with pytest.raises(ValueError):
        database_url()


def test_migration_url_preserves_escaped_password_and_session_options():
    url = migration_url(
        "dbname=alap user=migrator password='a@b:c/ %' "
        "host=/tmp/pg port=55432 options='-csearch_path=alap,pg_catalog'"
    )
    assert url.password == "a@b:c/ %"
    assert url.query["host"] == "/tmp/pg"
    assert url.query["port"] == "55432"
    assert url.query["options"] == "-csearch_path=alap,pg_catalog"
    assert migration_url(url.render_as_string(hide_password=False)) == url


@pytest.mark.parametrize(
    "extra",
    [
        "service=admin",
        "options=-csearch_path=public",
        "passfile=/private/admin",
        "sslkey=/private/admin.key",
    ],
)
def test_initialization_rejects_inherited_admin_identity(extra, tmp_path):
    from alap.adapters.postgres.deployment import initialize

    with pytest.raises(ValueError, match="unsupported"):
        initialize("dbname=admin " + extra, "alap_safety", tmp_path / "unused")
    assert not (tmp_path / "unused").exists()
