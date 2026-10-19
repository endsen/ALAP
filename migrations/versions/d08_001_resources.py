"""D08: reviewed MCP discovery, scoped sources, analyses and deduplicated collaboration."""

from alembic import op

from migrations.safety import require_test_database

revision = "d08_001"
down_revision = "d07_001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE knowledge_versions (
      id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments,
      source_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
      kind TEXT NOT NULL CHECK(kind IN ('document','memory')),
      owner_id TEXT NOT NULL REFERENCES principals, agent_ref TEXT,
      resources JSONB NOT NULL, content TEXT NOT NULL CHECK(length(content)<=100000),
      source_uri TEXT NOT NULL, content_hash TEXT NOT NULL,
      enabled BOOLEAN NOT NULL DEFAULT TRUE,
      UNIQUE(experiment_id,source_id,version)
    );
    CREATE TABLE knowledge_grants (
      source_version_id TEXT NOT NULL REFERENCES knowledge_versions,
      actor_id TEXT NOT NULL REFERENCES principals, revoked BOOLEAN NOT NULL DEFAULT FALSE,
      PRIMARY KEY(source_version_id,actor_id)
    );
    CREATE TABLE mcp_connections (
      ref TEXT PRIMARY KEY, config JSONB NOT NULL, config_hash TEXT NOT NULL,
      enabled BOOLEAN NOT NULL DEFAULT TRUE
    );
    CREATE TABLE mcp_tools (
      id TEXT PRIMARY KEY, connection_ref TEXT NOT NULL REFERENCES mcp_connections,
      name TEXT NOT NULL, spec JSONB NOT NULL, spec_hash TEXT NOT NULL,
      current BOOLEAN NOT NULL DEFAULT TRUE, UNIQUE(connection_ref,name,spec_hash)
    );
    CREATE TABLE mcp_grants (
      tool_id TEXT NOT NULL REFERENCES mcp_tools, actor_id TEXT NOT NULL REFERENCES principals,
      experiment_id TEXT NOT NULL REFERENCES experiments, resources JSONB NOT NULL,
      reviewer TEXT NOT NULL, revoked BOOLEAN NOT NULL DEFAULT FALSE,
      PRIMARY KEY(tool_id,actor_id,experiment_id)
    );
    CREATE TABLE mcp_calls (
      run_id TEXT NOT NULL REFERENCES agent_runs, call_id TEXT NOT NULL,
      tool_id TEXT NOT NULL REFERENCES mcp_tools,
      input_hash TEXT NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('INFLIGHT','SUCCEEDED','UNKNOWN')),
      result JSONB, PRIMARY KEY(run_id,call_id)
    );
    CREATE TABLE dataset_analyses (
      id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments,
      dataset_id TEXT NOT NULL REFERENCES datasets, checksum TEXT NOT NULL,
      algorithm TEXT NOT NULL, result JSONB NOT NULL,
      UNIQUE(dataset_id,checksum,algorithm)
    );
    CREATE TABLE collaboration_claims (
      experiment_id TEXT NOT NULL REFERENCES experiments,
      actor_id TEXT NOT NULL REFERENCES principals,
      definition_ref TEXT NOT NULL, evidence_hash TEXT NOT NULL, run_id TEXT REFERENCES agent_runs,
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(experiment_id,actor_id,definition_ref,evidence_hash)
    );
    CREATE TABLE proposal_business_keys (
      experiment_id TEXT NOT NULL REFERENCES experiments, fingerprint TEXT NOT NULL,
      proposal_id TEXT NOT NULL REFERENCES agent_proposals,
      PRIMARY KEY(experiment_id,fingerprint)
    );
    INSERT INTO proposal_business_keys
      SELECT DISTINCT ON (proposal->>'experiment_id',
        encode(sha256(convert_to((proposal-ARRAY['proposal_id','source_agent_run_id','reason'])::text,
          'UTF8')),'hex')) proposal->>'experiment_id',
        encode(sha256(convert_to((proposal-ARRAY['proposal_id','source_agent_run_id','reason'])::text,
          'UTF8')),'hex'),id FROM agent_proposals ORDER BY 1,2,id;
    CREATE TRIGGER immutable_proposal_business_key BEFORE UPDATE OR DELETE ON proposal_business_keys
      FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    CREATE FUNCTION protect_d08_record() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE fields TEXT[];
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable D08 record' USING ERRCODE='23514'; END IF;
      fields := CASE TG_TABLE_NAME WHEN 'knowledge_versions' THEN ARRAY['enabled']
        WHEN 'mcp_connections' THEN ARRAY['enabled'] WHEN 'mcp_tools' THEN ARRAY['current']
        WHEN 'mcp_calls' THEN ARRAY['state','result'] ELSE ARRAY['run_id'] END;
      IF (to_jsonb(NEW)-fields) IS DISTINCT FROM (to_jsonb(OLD)-fields) THEN
        RAISE EXCEPTION 'immutable D08 identity' USING ERRCODE='23514';
      END IF;
      IF TG_TABLE_NAME='mcp_calls' THEN
       IF OLD.state<>'INFLIGHT' THEN
        RAISE EXCEPTION 'immutable terminal MCP call' USING ERRCODE='23514';
       END IF;
      END IF;
      IF TG_TABLE_NAME='collaboration_claims' THEN
       IF OLD.run_id IS NOT NULL THEN
        RAISE EXCEPTION 'immutable collaboration binding' USING ERRCODE='23514';
       END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER protect_knowledge BEFORE UPDATE OR DELETE ON knowledge_versions
      FOR EACH ROW EXECUTE FUNCTION protect_d08_record();
    CREATE TRIGGER protect_mcp_connection BEFORE UPDATE OR DELETE ON mcp_connections
      FOR EACH ROW EXECUTE FUNCTION protect_d08_record();
    CREATE TRIGGER protect_mcp_tool BEFORE UPDATE OR DELETE ON mcp_tools
      FOR EACH ROW EXECUTE FUNCTION protect_d08_record();
    CREATE TRIGGER protect_mcp_call BEFORE UPDATE OR DELETE ON mcp_calls
      FOR EACH ROW EXECUTE FUNCTION protect_d08_record();
    CREATE TRIGGER protect_collaboration BEFORE UPDATE OR DELETE ON collaboration_claims
      FOR EACH ROW EXECUTE FUNCTION protect_d08_record();
    CREATE TRIGGER immutable_analysis BEFORE UPDATE OR DELETE ON dataset_analyses
      FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    """)


def downgrade():
    require_test_database()
    op.execute("""DROP TABLE proposal_business_keys,collaboration_claims,dataset_analyses,
      mcp_calls,mcp_grants,mcp_tools,
      mcp_connections,knowledge_grants,knowledge_versions; DROP FUNCTION protect_d08_record();""")
