"""D09: local bearer identities, management state, encrypted credentials and API ledger."""

from alembic import op

from migrations.safety import require_test_database

revision = "d09_001"
down_revision = "d08_001"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE experiments ADD COLUMN title TEXT NOT NULL DEFAULT '',
      ADD COLUMN objective TEXT NOT NULL DEFAULT '',
      ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp();
    CREATE TABLE platform_roles (
      actor_id TEXT PRIMARY KEY REFERENCES principals,
      role TEXT NOT NULL CHECK(role IN ('admin','researcher','observer'))
    );
    CREATE TABLE api_tokens (
      token_hash TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES principals,
      expires_at TIMESTAMPTZ NOT NULL, revoked BOOLEAN NOT NULL DEFAULT FALSE
    );
    CREATE TABLE api_credentials (
      ref TEXT PRIMARY KEY, ciphertext BYTEA NOT NULL,
      revision BIGINT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE
    );
    CREATE TABLE platform_configs (
      kind TEXT NOT NULL CHECK(kind IN ('connection','model')),
      ref TEXT NOT NULL, document JSONB NOT NULL, content_hash TEXT NOT NULL,
      enabled BOOLEAN NOT NULL DEFAULT TRUE, revision BIGINT NOT NULL DEFAULT 0,
      PRIMARY KEY(kind,ref)
    );
    CREATE TABLE api_requests (
      actor_id TEXT NOT NULL REFERENCES principals, operation TEXT NOT NULL,
      key TEXT NOT NULL, request_hash TEXT NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('INFLIGHT','DONE','FAILED')),
      response JSONB, error_code TEXT,
      PRIMARY KEY(actor_id,operation,key)
    );
    CREATE TABLE api_audit (
      id BIGSERIAL PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES principals,
      operation TEXT NOT NULL, target TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
    );
    CREATE TRIGGER immutable_api_audit BEFORE UPDATE OR DELETE ON api_audit
      FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    """)


def downgrade():
    require_test_database()
    op.execute("""DROP TABLE api_audit,api_requests,platform_configs,api_credentials,
      api_tokens,platform_roles;
      ALTER TABLE experiments DROP COLUMN title, DROP COLUMN objective, DROP COLUMN created_at;""")
