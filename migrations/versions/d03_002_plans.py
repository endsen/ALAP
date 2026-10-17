"""D03-002: immutable plans, approval envelopes, ready runs and deduplication."""

from alembic import op

from migrations.safety import require_test_database

revision = "d03_002"
down_revision = "d03_001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE plan_revisions (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments,
        revision BIGINT NOT NULL CHECK (revision > 0),
        snapshot_version BIGINT NOT NULL CHECK (snapshot_version >= 0),
        canonical_bytes BYTEA NOT NULL, plan_json JSONB NOT NULL,
        plan_hash TEXT NOT NULL CHECK (plan_hash ~ '^[a-f0-9]{64}$'),
        created_by TEXT NOT NULL REFERENCES principals,
        UNIQUE (experiment_id, revision), UNIQUE (experiment_id, id),
        UNIQUE (experiment_id, id, plan_hash),
        CHECK (encode(sha256(canonical_bytes), 'hex') = plan_hash),
        CHECK (convert_from(canonical_bytes, 'UTF8')::jsonb = plan_json),
        CHECK (plan_json->>'plan_revision_id' = id),
        CHECK (plan_json->'proposal'->>'experiment_id' = experiment_id)
    );
    CREATE TABLE approvals (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments,
        plan_revision_id TEXT NOT NULL, plan_hash TEXT NOT NULL,
        scope_json JSONB NOT NULL, binding_hash TEXT NOT NULL
            CHECK (binding_hash ~ '^[a-f0-9]{64}$'),
        state TEXT NOT NULL CHECK (state IN
            ('PENDING','APPROVED','REJECTED','EXPIRED','REVOKED','SUPERSEDED')),
        state_version BIGINT NOT NULL DEFAULT 0 CHECK (state_version >= 0),
        requested_by TEXT NOT NULL REFERENCES principals, decided_by TEXT REFERENCES principals,
        expires_at TIMESTAMPTZ NOT NULL,
        UNIQUE (experiment_id, id), UNIQUE (experiment_id, id, plan_revision_id, plan_hash),
        FOREIGN KEY (experiment_id,plan_revision_id,plan_hash)
            REFERENCES plan_revisions(experiment_id,id,plan_hash)
    );
    CREATE TABLE runs (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments,
        plan_revision_id TEXT NOT NULL, approval_id TEXT NOT NULL, plan_hash TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('READY','WAITING_RESOURCE','RUNNING','VERIFYING',
            'PAUSE_REQUESTED','PAUSED','CANCEL_REQUESTED','SUCCEEDED','FAILED','CANCELLED',
            'UNKNOWN','NEEDS_RECONCILIATION')),
        state_version BIGINT NOT NULL DEFAULT 0 CHECK (state_version >= 0),
        dispatch_blocked BOOLEAN NOT NULL DEFAULT TRUE,
        binding_hash TEXT NOT NULL CHECK (binding_hash ~ '^[a-f0-9]{64}$'),
        task_identities JSONB NOT NULL,
        created_by TEXT NOT NULL REFERENCES principals,
        UNIQUE (experiment_id,id),
        FOREIGN KEY (experiment_id,plan_revision_id,plan_hash)
            REFERENCES plan_revisions(experiment_id,id,plan_hash),
        FOREIGN KEY (experiment_id,approval_id,plan_revision_id,plan_hash)
            REFERENCES approvals(experiment_id,id,plan_revision_id,plan_hash)
    );
    CREATE TABLE idempotency_records (
        actor_id TEXT NOT NULL REFERENCES principals, operation TEXT NOT NULL,
        scope_id TEXT NOT NULL, key TEXT NOT NULL CHECK (length(key) > 0),
        request_hash TEXT NOT NULL CHECK (request_hash ~ '^[a-f0-9]{64}$'),
        response_json JSONB, status TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETE')),
        expires_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (actor_id,operation,scope_id,key),
        CHECK ((status = 'COMPLETE') = (response_json IS NOT NULL))
    );
    CREATE FUNCTION reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'immutable record: %', TG_TABLE_NAME USING ERRCODE='23514'; END $$;
    CREATE TRIGGER immutable_plan BEFORE UPDATE OR DELETE ON plan_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    CREATE FUNCTION protect_approval() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'immutable approval' USING ERRCODE='23514';
        END IF;
        IF (to_jsonb(NEW) - ARRAY['state','state_version','decided_by']) IS DISTINCT FROM
           (to_jsonb(OLD) - ARRAY['state','state_version','decided_by']) THEN
            RAISE EXCEPTION 'immutable approval envelope' USING ERRCODE='23514';
        END IF;
        IF NEW.state_version <> OLD.state_version + 1 THEN
            RAISE EXCEPTION 'approval version must advance once' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_approval BEFORE UPDATE OR DELETE ON approvals
        FOR EACH ROW EXECUTE FUNCTION protect_approval();
    CREATE FUNCTION protect_run() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'immutable run' USING ERRCODE='23514';
        END IF;
        IF (to_jsonb(NEW) - ARRAY['state','state_version','dispatch_blocked']) IS DISTINCT FROM
           (to_jsonb(OLD) - ARRAY['state','state_version','dispatch_blocked']) THEN
            RAISE EXCEPTION 'immutable run definition' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_run BEFORE UPDATE OR DELETE ON runs
        FOR EACH ROW EXECUTE FUNCTION protect_run();
    """)


def downgrade():
    require_test_database()
    op.execute("""
    DROP TABLE idempotency_records;
    DROP TABLE runs;
    DROP TABLE approvals;
    DROP TABLE plan_revisions;
    DROP FUNCTION protect_run();
    DROP FUNCTION protect_approval();
    DROP FUNCTION reject_mutation();
    """)
