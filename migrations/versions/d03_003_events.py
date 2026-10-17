"""D03-003: durable evidence, append-only audit and transactional outbox."""

from alembic import op

from migrations.safety import require_test_database

revision = "d03_003"
down_revision = "d03_002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE evidence_records (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments,
        subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL,
        subject_version BIGINT NOT NULL CHECK (subject_version >= 0),
        binding_hash TEXT NOT NULL CHECK (binding_hash ~ '^[a-f0-9]{64}$'),
        fact TEXT NOT NULL, source JSONB NOT NULL,
        valid_from TIMESTAMPTZ NOT NULL, valid_until TIMESTAMPTZ NOT NULL,
        verified_by TEXT NOT NULL REFERENCES principals, verified_at TIMESTAMPTZ NOT NULL,
        CHECK (valid_from < valid_until)
    );
    CREATE TABLE transition_audit (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments,
        kind TEXT NOT NULL, subject_id TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL,
        old_version BIGINT NOT NULL CHECK (old_version >= -1),
        new_version BIGINT NOT NULL CHECK (new_version >= 0),
        event TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES principals,
        evidence_ids JSONB NOT NULL, effects JSONB NOT NULL, trace_id TEXT NOT NULL,
        occurred_at TIMESTAMPTZ NOT NULL,
        UNIQUE (kind,subject_id,new_version), CHECK (new_version = old_version + 1)
    );
    CREATE TABLE outbox_events (
        event_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments,
        experiment_seq BIGINT NOT NULL CHECK (experiment_seq > 0),
        aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL,
        aggregate_seq BIGINT NOT NULL CHECK (aggregate_seq >= 0),
        event_type TEXT NOT NULL, payload JSONB NOT NULL,
        schema_version TEXT NOT NULL CHECK (schema_version = '2.0'),
        producer TEXT NOT NULL, trace_id TEXT NOT NULL,
        occurred_at TIMESTAMPTZ NOT NULL, published_at TIMESTAMPTZ,
        UNIQUE (experiment_id,experiment_seq),
        UNIQUE (aggregate_type,aggregate_id,aggregate_seq)
    );
    CREATE INDEX outbox_pending ON outbox_events (experiment_id,experiment_seq)
        WHERE published_at IS NULL;
    CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON evidence_records
        FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    CREATE TRIGGER immutable_audit BEFORE UPDATE OR DELETE ON transition_audit
        FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    CREATE FUNCTION protect_event() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'immutable event' USING ERRCODE='23514';
        END IF;
        IF (to_jsonb(NEW) - 'published_at') IS DISTINCT FROM
           (to_jsonb(OLD) - 'published_at') THEN
            RAISE EXCEPTION 'immutable event payload' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_event BEFORE UPDATE OR DELETE ON outbox_events
        FOR EACH ROW EXECUTE FUNCTION protect_event();
    """)


def downgrade():
    require_test_database()
    op.execute("""
    DROP TABLE outbox_events;
    DROP TABLE transition_audit;
    DROP TABLE evidence_records;
    DROP FUNCTION protect_event();
    """)
