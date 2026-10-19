"""D05b: publisher claims and transactionally deduplicated consumer projections."""

from alembic import op

from migrations.safety import require_test_database

revision = "d05_002"
down_revision = "d05_001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE event_delivery_claims (
      event_id TEXT PRIMARY KEY REFERENCES outbox_events, token TEXT NOT NULL,
      expires_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE consumer_inbox (
      consumer_id TEXT NOT NULL, event_id TEXT NOT NULL REFERENCES outbox_events,
      payload_hash TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL,
      PRIMARY KEY(consumer_id,event_id)
    );
    CREATE TRIGGER immutable_inbox BEFORE UPDATE OR DELETE ON consumer_inbox
      FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    CREATE TABLE event_projections (
      consumer_id TEXT NOT NULL, experiment_id TEXT NOT NULL REFERENCES experiments,
      aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL,
      aggregate_seq BIGINT NOT NULL, event_id TEXT NOT NULL REFERENCES outbox_events,
      payload JSONB NOT NULL,
      PRIMARY KEY(consumer_id,experiment_id,aggregate_type,aggregate_id)
    );
    """)


def downgrade():
    require_test_database()
    op.execute("DROP TABLE event_projections,consumer_inbox,event_delivery_claims")
