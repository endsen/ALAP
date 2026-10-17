"""D03-001: identity, samples and experiment serialization roots."""

from alembic import op

from migrations.safety import require_test_database

revision = "d03_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE principals (
        id TEXT PRIMARY KEY, issuer TEXT NOT NULL, external_subject TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('user','service')), disabled_at TIMESTAMPTZ,
        UNIQUE (issuer, external_subject)
    );
    CREATE TABLE samples (
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES principals,
        metadata JSONB NOT NULL, version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0)
    );
    CREATE TABLE experiments (
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES principals,
        sample_id TEXT NOT NULL REFERENCES samples,
        revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
        event_cursor BIGINT NOT NULL DEFAULT 0 CHECK (event_cursor >= 0),
        state TEXT NOT NULL DEFAULT 'DRAFT' CHECK (state IN ('DRAFT','PLANNED'))
    );
    CREATE TABLE experiment_memberships (
        experiment_id TEXT NOT NULL REFERENCES experiments,
        actor_id TEXT NOT NULL REFERENCES principals,
        role TEXT NOT NULL CHECK (role IN ('observer','operator','approver','owner')),
        scope JSONB NOT NULL, version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
        revoked_at TIMESTAMPTZ,
        PRIMARY KEY (experiment_id, actor_id)
    );
    """)


def downgrade():
    require_test_database()
    op.execute("""
    DROP TABLE experiment_memberships;
    DROP TABLE experiments;
    DROP TABLE samples;
    DROP TABLE principals;
    """)
