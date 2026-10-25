"""Durable owner cancellation intent, independent of model checkpoint revision."""

from alembic import op

from migrations.safety import require_test_database

revision = "d12_002"
down_revision = "d12_001"
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE agent_runs ADD COLUMN cancel_requested_at timestamptz")
    op.execute("""
    CREATE OR REPLACE FUNCTION protect_agent_run() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='UPDATE' AND OLD.cancel_requested_at IS NULL
        AND NEW.cancel_requested_at IS NOT NULL
        AND OLD.checkpoint->>'status' IN ('READY','RUNNING')
        AND (to_jsonb(NEW)-'cancel_requested_at') = (to_jsonb(OLD)-'cancel_requested_at') THEN
        RETURN NEW;
      END IF;
      IF TG_OP='DELETE' OR
        (to_jsonb(NEW)-ARRAY['checkpoint','revision']) IS DISTINCT FROM
        (to_jsonb(OLD)-ARRAY['checkpoint','revision']) OR NEW.revision<>OLD.revision+1 THEN
        RAISE EXCEPTION 'immutable agent binding or invalid revision' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    """)


def downgrade():
    require_test_database()
    op.execute("ALTER TABLE agent_runs DROP COLUMN cancel_requested_at")
    op.execute("""
    CREATE OR REPLACE FUNCTION protect_agent_run() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' OR
        (to_jsonb(NEW)-ARRAY['checkpoint','revision']) IS DISTINCT FROM
        (to_jsonb(OLD)-ARRAY['checkpoint','revision']) OR NEW.revision<>OLD.revision+1 THEN
        RAISE EXCEPTION 'immutable agent binding or invalid revision' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    """)
