"""D07: immutable registry, logical agent checkpoints, trace and proposal ledger."""

from alembic import op

from migrations.safety import require_test_database

revision = "d07_001"
down_revision = "d05_003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE agent_registry (
      kind TEXT NOT NULL CHECK (kind IN ('skill','agent')), ref TEXT NOT NULL,
      document JSONB NOT NULL, content_hash TEXT NOT NULL,
      canonical_bytes BYTEA NOT NULL, state TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK (state IN ('DRAFT','PUBLISHED','DISABLED')),
      publisher TEXT, validated_at TIMESTAMPTZ,
      published_bundle JSONB, published_hash TEXT,
      PRIMARY KEY(kind,ref),
      CHECK (encode(sha256(canonical_bytes),'hex')=content_hash),
      CHECK (convert_from(canonical_bytes,'UTF8')::jsonb=document)
    );
    CREATE FUNCTION protect_agent_registry() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' OR
        (to_jsonb(NEW)-ARRAY['state','publisher','validated_at',
          'published_bundle','published_hash']) IS DISTINCT FROM
        (to_jsonb(OLD)-ARRAY['state','publisher','validated_at',
          'published_bundle','published_hash']) THEN
        RAISE EXCEPTION 'immutable registry version' USING ERRCODE='23514';
      END IF;
      IF OLD.state<>'DRAFT' AND
        (to_jsonb(NEW)-'state') IS DISTINCT FROM (to_jsonb(OLD)-'state') THEN
        RAISE EXCEPTION 'immutable published binding' USING ERRCODE='23514';
      END IF;
      IF OLD.state='DISABLED' AND NEW.state<>'DISABLED' THEN
        RAISE EXCEPTION 'disabled versions cannot be reenabled' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_agent_registry BEFORE UPDATE OR DELETE ON agent_registry
      FOR EACH ROW EXECUTE FUNCTION protect_agent_registry();
    CREATE TABLE agent_runs (
      id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES principals,
      experiment_id TEXT NOT NULL REFERENCES experiments,
      definition_ref TEXT NOT NULL, bundle JSONB NOT NULL,
      bundle_hash TEXT NOT NULL, checkpoint JSONB NOT NULL,
      revision BIGINT NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      deadline_at TIMESTAMPTZ NOT NULL
    );
    CREATE FUNCTION protect_agent_run() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' OR
        (to_jsonb(NEW)-ARRAY['checkpoint','revision']) IS DISTINCT FROM
        (to_jsonb(OLD)-ARRAY['checkpoint','revision']) OR NEW.revision<>OLD.revision+1 THEN
        RAISE EXCEPTION 'immutable agent binding or invalid revision' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_agent_binding BEFORE UPDATE OR DELETE ON agent_runs
      FOR EACH ROW EXECUTE FUNCTION protect_agent_run();
    CREATE TABLE agent_trace (
      run_id TEXT NOT NULL REFERENCES agent_runs, seq BIGINT NOT NULL,
      event JSONB NOT NULL, occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(run_id,seq)
    );
    CREATE TABLE agent_proposals (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs,
      call_id TEXT NOT NULL, proposal JSONB NOT NULL, content_hash TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'PROPOSED' CHECK (state='PROPOSED'),
      UNIQUE(run_id,call_id)
    );
    CREATE TABLE agent_tool_invocations (
      run_id TEXT NOT NULL REFERENCES agent_runs, call_id TEXT NOT NULL,
      tool_ref TEXT NOT NULL, input_hash TEXT NOT NULL, result JSONB NOT NULL,
      outcome TEXT NOT NULL CHECK (outcome IN ('SUCCEEDED','BLOCKED')),
      PRIMARY KEY(run_id,call_id)
    );
    CREATE TRIGGER immutable_agent_trace BEFORE UPDATE OR DELETE ON agent_trace
      FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    CREATE TRIGGER immutable_agent_proposal BEFORE UPDATE OR DELETE ON agent_proposals
      FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    CREATE TRIGGER immutable_agent_invocation BEFORE UPDATE OR DELETE ON agent_tool_invocations
      FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    """)


def downgrade():
    require_test_database()
    op.execute("""DROP TABLE agent_tool_invocations, agent_proposals, agent_trace, agent_runs,
      agent_registry; DROP FUNCTION protect_agent_run(); DROP FUNCTION protect_agent_registry();""")
