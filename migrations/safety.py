"""Destructive rollback exists only for disposable integration databases."""

from alembic import op


def require_test_database():
    name = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if not name.startswith("alap_test"):
        raise RuntimeError(
            "Downgrade is restricted to disposable alap_test databases; use forward repair"
        )
