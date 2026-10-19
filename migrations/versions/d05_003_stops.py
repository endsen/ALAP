"""D05c: durable stop confirmation and immutable stop identity."""

from alembic import op

from migrations.safety import require_test_database

revision = "d05_003"
down_revision = "d05_002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE stop_requests ADD COLUMN result_json JSONB;
    CREATE FUNCTION protect_stop() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable stop' USING ERRCODE='23514'; END IF;
      IF (to_jsonb(NEW)-ARRAY['state','result_json']) IS DISTINCT FROM
         (to_jsonb(OLD)-ARRAY['state','result_json']) OR OLD.state='CONFIRMED' THEN
        RAISE EXCEPTION 'immutable stop identity or confirmed result' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_stop BEFORE UPDATE OR DELETE ON stop_requests
      FOR EACH ROW EXECUTE FUNCTION protect_stop();
    """)


def downgrade():
    require_test_database()
    op.execute("""DROP TRIGGER immutable_stop ON stop_requests;
      DROP FUNCTION protect_stop(); ALTER TABLE stop_requests DROP COLUMN result_json;""")
