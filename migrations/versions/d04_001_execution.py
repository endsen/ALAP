"""D04-001: durable execution identities, ownership, leases and command delivery."""

from alembic import op

from migrations.safety import require_test_database

revision = "d04_001"
down_revision = "d03_003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE gateways (
        id TEXT PRIMARY KEY, principal_id TEXT NOT NULL UNIQUE REFERENCES principals,
        epoch UUID, reconciliation_ref TEXT
    );
    CREATE TABLE instruments (
        id TEXT PRIMARY KEY, gateway_id TEXT NOT NULL REFERENCES gateways,
        physical_resource_key TEXT NOT NULL UNIQUE,
        policy_version TEXT NOT NULL, capability_version TEXT NOT NULL,
        metadata JSONB NOT NULL
    );
    CREATE TABLE control_generation (
        id TEXT PRIMARY KEY CHECK (id='current'), epoch UUID NOT NULL,
        mode TEXT NOT NULL CHECK (mode IN ('ACTIVE','RECOVERING')),
        version BIGINT NOT NULL CHECK (version>=0)
    );
    INSERT INTO control_generation VALUES ('current',gen_random_uuid(),'RECOVERING',0);
    CREATE TABLE resource_controls (
        id TEXT PRIMARY KEY REFERENCES instruments,
        epoch UUID NOT NULL, last_fencing_token BIGINT NOT NULL CHECK (last_fencing_token>=0),
        quarantined BOOLEAN NOT NULL DEFAULT TRUE, reason TEXT NOT NULL,
        reconciliation_ref TEXT
    );
    CREATE TABLE leases (
        id TEXT PRIMARY KEY, resource_id TEXT NOT NULL REFERENCES instruments,
        holder_run_id TEXT NOT NULL REFERENCES runs,
        epoch UUID NOT NULL, token BIGINT NOT NULL CHECK (token>0),
        expires_at TIMESTAMPTZ NOT NULL, scope_hash TEXT NOT NULL,
        binding_hash TEXT NOT NULL CHECK (binding_hash ~ '^[a-f0-9]{64}$'),
        state TEXT NOT NULL CHECK (state IN
          ('ACTIVE','RELEASE_PENDING','RELEASED','EXPIRED','REVOKED')),
        state_version BIGINT NOT NULL DEFAULT 0 CHECK (state_version>=0),
        UNIQUE(resource_id,epoch,token), UNIQUE(id,resource_id,holder_run_id,epoch,token)
    );
    CREATE TABLE resource_claims (
        resource_id TEXT PRIMARY KEY REFERENCES instruments,
        lease_id TEXT NOT NULL UNIQUE, holder_run_id TEXT NOT NULL, epoch UUID NOT NULL,
        token BIGINT NOT NULL,
        FOREIGN KEY(lease_id,resource_id,holder_run_id,epoch,token)
          REFERENCES leases(id,resource_id,holder_run_id,epoch,token)
    );
    CREATE TABLE tasks (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, run_id TEXT NOT NULL,
        plan_task_id TEXT NOT NULL, attempt_no INT NOT NULL CHECK(attempt_no>0),
        state TEXT NOT NULL CHECK(state IN ('PENDING','READY','WAITING_RESOURCE','DISPATCHED',
          'RUNNING','VERIFYING','CANCEL_REQUESTED','SUCCEEDED','FAILED','CANCELLED','SKIPPED',
          'UNKNOWN','NEEDS_RECONCILIATION')),
        state_version BIGINT NOT NULL DEFAULT 0 CHECK(state_version>=0),
        binding_hash TEXT NOT NULL CHECK(binding_hash ~ '^[a-f0-9]{64}$'),
        definition JSONB NOT NULL,
        UNIQUE(run_id,plan_task_id,attempt_no), UNIQUE(run_id,id),
        UNIQUE(experiment_id,run_id,id),
        FOREIGN KEY(experiment_id,run_id) REFERENCES runs(experiment_id,id)
    );
    CREATE TABLE task_dependencies (
        run_id TEXT NOT NULL, task_id TEXT NOT NULL, depends_on_id TEXT NOT NULL,
        PRIMARY KEY(run_id,task_id,depends_on_id), CHECK(task_id<>depends_on_id),
        FOREIGN KEY(run_id,task_id) REFERENCES tasks(run_id,id),
        FOREIGN KEY(run_id,depends_on_id) REFERENCES tasks(run_id,id)
    );
    CREATE TABLE command_ledger (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
        run_id TEXT NOT NULL, task_id TEXT NOT NULL,
        attempt_no INT NOT NULL CHECK(attempt_no>0),
        payload_bytes BYTEA NOT NULL, payload_hash TEXT NOT NULL,
        binding_hash TEXT NOT NULL CHECK(binding_hash=payload_hash),
        instrument_id TEXT NOT NULL REFERENCES instruments,
        lease_id TEXT NOT NULL, epoch UUID NOT NULL, token BIGINT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('NOT_DISPATCHED','DISPATCHED','ACCEPTED','RUNNING',
          'VERIFYING','CANCEL_REQUESTED','SUCCEEDED','FAILED_CONFIRMED','REJECTED_BEFORE_EXECUTE',
          'CANCELLED','UNKNOWN','NEEDS_RECONCILIATION')),
        state_version BIGINT NOT NULL DEFAULT 0 CHECK(state_version>=0),
        UNIQUE(task_id), UNIQUE(experiment_id,id),
        FOREIGN KEY(experiment_id,run_id,task_id) REFERENCES tasks(experiment_id,run_id,id),
        FOREIGN KEY(lease_id,instrument_id,run_id,epoch,token)
          REFERENCES leases(id,resource_id,holder_run_id,epoch,token),
        CHECK(encode(sha256(payload_bytes),'hex')=payload_hash)
    );
    CREATE TABLE command_deliveries (
        id TEXT PRIMARY KEY REFERENCES command_ledger,
        status TEXT NOT NULL CHECK(status IN ('PENDING','ATTEMPTED')),
        claimed_by TEXT REFERENCES principals, claimed_until TIMESTAMPTZ,
        delivery_attempt_id TEXT UNIQUE
    );
    CREATE TABLE stop_requests (
        id TEXT PRIMARY KEY, command_id TEXT NOT NULL REFERENCES command_ledger,
        actor_id TEXT NOT NULL REFERENCES principals, reason TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('PENDING','REQUESTED','CONFIRMED','UNKNOWN')),
        dedup_key TEXT NOT NULL UNIQUE
    );
    CREATE TABLE gateway_receipts (
        id TEXT PRIMARY KEY, gateway_id TEXT NOT NULL REFERENCES gateways,
        epoch UUID NOT NULL, receipt_seq BIGINT NOT NULL CHECK(receipt_seq>0),
        command_id TEXT NOT NULL REFERENCES command_ledger,
        payload_hash TEXT NOT NULL, raw_receipt JSONB NOT NULL, received_at TIMESTAMPTZ NOT NULL,
        UNIQUE(gateway_id,epoch,receipt_seq)
    );
    CREATE FUNCTION protect_execution_record() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE mutable_fields TEXT[];
    BEGIN
        IF TG_OP='DELETE' THEN
          RAISE EXCEPTION 'immutable execution record' USING ERRCODE='23514';
        END IF;
        mutable_fields := CASE WHEN TG_TABLE_NAME='leases'
          THEN ARRAY['state','state_version','expires_at'] ELSE ARRAY['state','state_version'] END;
        IF (to_jsonb(NEW)-mutable_fields) IS DISTINCT FROM (to_jsonb(OLD)-mutable_fields)
          OR NEW.state_version<>OLD.state_version+1 THEN
          RAISE EXCEPTION 'immutable definition or invalid version' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_task BEFORE UPDATE OR DELETE ON tasks
      FOR EACH ROW EXECUTE FUNCTION protect_execution_record();
    CREATE TRIGGER immutable_command BEFORE UPDATE OR DELETE ON command_ledger
      FOR EACH ROW EXECUTE FUNCTION protect_execution_record();
    CREATE TRIGGER immutable_lease BEFORE UPDATE OR DELETE ON leases
      FOR EACH ROW EXECUTE FUNCTION protect_execution_record();
    CREATE TRIGGER immutable_receipt BEFORE UPDATE OR DELETE ON gateway_receipts
      FOR EACH ROW EXECUTE FUNCTION reject_mutation();
    CREATE FUNCTION protect_delivery() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.status='ATTEMPTED' OR NEW.status<>'ATTEMPTED' THEN
        RAISE EXCEPTION 'delivery may be attempted only once' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER delivery_once BEFORE UPDATE ON command_deliveries
      FOR EACH ROW EXECUTE FUNCTION protect_delivery();
    """)


def downgrade():
    require_test_database()
    op.execute("""
    DROP TABLE gateway_receipts,stop_requests,command_deliveries,command_ledger;
    DROP TABLE task_dependencies,tasks,resource_claims,leases,resource_controls;
    DROP TABLE control_generation,instruments,gateways;
    DROP FUNCTION protect_execution_record();
    DROP FUNCTION protect_delivery();
    """)
