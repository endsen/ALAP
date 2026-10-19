"""D05a: immutable acquisition identity, formal datasets and acquisition provenance."""

from alembic import op

from migrations.safety import require_test_database

revision = "d05_001"
down_revision = "d04_001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE command_ledger ADD CONSTRAINT command_dataset_source
      UNIQUE(experiment_id,run_id,task_id,id);
    CREATE TABLE device_snapshots (
      id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments,
      version BIGINT NOT NULL CHECK(version>0),
      command_id TEXT NOT NULL UNIQUE REFERENCES command_ledger,
      source JSONB NOT NULL, UNIQUE(experiment_id,version,command_id)
    );
    CREATE TRIGGER immutable_device_snapshot BEFORE UPDATE OR DELETE ON device_snapshots
      FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    CREATE TABLE datasets (
      id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, run_id TEXT NOT NULL,
      task_id TEXT NOT NULL, command_id TEXT NOT NULL UNIQUE,
      receipt_id TEXT NOT NULL REFERENCES gateway_receipts,
      state TEXT NOT NULL CHECK(state IN ('STAGING','VALIDATING','COMMITTED','CORRUPT')),
      state_version BIGINT NOT NULL DEFAULT 0 CHECK(state_version>=0),
      binding_hash TEXT NOT NULL CHECK(binding_hash ~ '^[a-f0-9]{64}$'),
      storage_key TEXT NOT NULL UNIQUE, manifest_json JSONB, checksum TEXT,
      device_snapshot_version BIGINT NOT NULL,
      FOREIGN KEY(experiment_id,device_snapshot_version,command_id)
        REFERENCES device_snapshots(experiment_id,version,command_id),
      acquired_from TIMESTAMPTZ NOT NULL, acquired_to TIMESTAMPTZ NOT NULL,
      UNIQUE(experiment_id,id), CHECK(acquired_from<=acquired_to),
      UNIQUE(experiment_id,run_id,task_id,command_id,receipt_id,id),
      FOREIGN KEY(experiment_id,run_id,task_id,command_id)
        REFERENCES command_ledger(experiment_id,run_id,task_id,id),
      CHECK(state<>'COMMITTED' OR (manifest_json IS NOT NULL AND checksum IS NOT NULL)),
      CHECK(checksum IS NULL OR checksum ~ '^[a-f0-9]{64}$')
    );
    CREATE TABLE provenance_edges (
      dataset_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
      run_id TEXT NOT NULL, task_id TEXT NOT NULL, command_id TEXT NOT NULL,
      receipt_id TEXT NOT NULL REFERENCES gateway_receipts,
      plan_revision_id TEXT NOT NULL REFERENCES plan_revisions,
      algorithm_version TEXT NOT NULL, parameters_hash TEXT NOT NULL,
      FOREIGN KEY(experiment_id,run_id,task_id,command_id,receipt_id,dataset_id)
        REFERENCES datasets(experiment_id,run_id,task_id,command_id,receipt_id,id),
      FOREIGN KEY(experiment_id,run_id,task_id,command_id)
        REFERENCES command_ledger(experiment_id,run_id,task_id,id)
    );
    CREATE TRIGGER immutable_provenance BEFORE UPDATE OR DELETE ON provenance_edges
      FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    CREATE FUNCTION protect_dataset() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'immutable acquisition' USING ERRCODE='23514';
      END IF;
      IF (to_jsonb(NEW)-ARRAY['state','state_version','manifest_json','checksum']) IS DISTINCT FROM
         (to_jsonb(OLD)-ARRAY['state','state_version','manifest_json','checksum'])
         OR NEW.state_version<>OLD.state_version+1
         OR NOT ((OLD.state='STAGING' AND NEW.state IN ('VALIDATING','CORRUPT'))
           OR (OLD.state='VALIDATING' AND NEW.state IN ('COMMITTED','CORRUPT'))
           OR (OLD.state='COMMITTED' AND NEW.state='CORRUPT'))
         OR (OLD.manifest_json IS NOT NULL AND NEW.manifest_json IS DISTINCT FROM OLD.manifest_json)
         OR (OLD.checksum IS NOT NULL AND NEW.checksum IS DISTINCT FROM OLD.checksum) THEN
        RAISE EXCEPTION 'immutable dataset or invalid transition' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_dataset BEFORE UPDATE OR DELETE ON datasets
      FOR EACH ROW EXECUTE FUNCTION protect_dataset();
    """)


def downgrade():
    require_test_database()
    op.execute("""
      DROP TABLE provenance_edges,datasets,device_snapshots;
      DROP FUNCTION protect_dataset();
      ALTER TABLE command_ledger DROP CONSTRAINT command_dataset_source;
    """)
