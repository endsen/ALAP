"""D04 exercises real PostgreSQL and separate persistent simulator/journal files."""

import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Barrier

import psycopg
import pytest

from alap.adapters.gateway.auth import Authenticator
from alap.adapters.gateway.journal import Gateway
from alap.adapters.gateway.simulator import Simulator, WallClock
from alap.application.execution import ExecutionService
from alap.domain.rules import DomainError

from .conftest import rows
from .test_persistence import EXP, approved, start

pytestmark = pytest.mark.postgres


@pytest.fixture
def execution(scenario, tmp_path, request):
    base, _, revision, dsn = scenario
    for task in revision["proposal"]["tasks"]:
        for condition in task["preconditions"] + [task["success_condition"]]:
            if condition["kind"] == "stable_window":
                condition["min_duration_s"] = 0.01
    if getattr(request, "param", None) == "parallel":
        revision["proposal"]["tasks"][1]["depends_on"] = []
        revision["proposal"]["tasks"][1]["preconditions"] = []
    if getattr(request, "param", None) == "single":
        revision["proposal"]["tasks"] = revision["proposal"]["tasks"][:1]
        revision["proposal"]["requested_resources"] = ["sim-temp"]
        revision["policy_versions"] = {"sim-temp": base.policy_versions["sim-temp"]}
        revision["capability_versions"] = {"sim-temp": base.capability_versions["sim-temp"]}
    auth = Authenticator(secrets.token_bytes(32))
    simulator = Simulator(tmp_path / "physical.sqlite", WallClock())
    gateway = Gateway(
        "gw",
        tmp_path / "journal.sqlite",
        authenticator=auth,
        catalog=base.catalog,
        simulator=simulator,
        skills=base.skills,
        policy_versions=base.policy_versions,
        capability_versions=base.capability_versions,
    )
    service = ExecutionService(base, authenticator=auth, gateways={"gw": gateway})
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO principals VALUES ('engine','alap-engine','engine','service',NULL)"
        )
        connection.execute(
            "INSERT INTO principals VALUES ('gateway','test','gateway','service',NULL)"
        )
        connection.execute("INSERT INTO gateways(id,principal_id) VALUES ('gw','gateway')")
        for resource in revision["proposal"]["requested_resources"]:
            connection.execute(
                """INSERT INTO instruments VALUES (%s,'gw',%s,%s,%s,'{}')""",
                (
                    resource,
                    resource,
                    base.policy_versions[resource],
                    base.capability_versions[resource],
                ),
            )
            connection.execute(
                """INSERT INTO resource_controls(id,epoch,last_fencing_token,reason)
                                  SELECT %s,epoch,0,'initial' FROM control_generation""",
                (resource,),
            )
    service.bind_gateway("engine", "gw")
    service.finish_recovery("engine")
    approval = approved(scenario)
    run = start(base, approval)
    service.materialize("engine", run["id"])
    yield service, gateway, simulator, run, scenario
    for current in service.gateways.values():
        current.close()
    gateway.close()


def prepare(execution, task="temperature"):
    service, _, _, run, _ = execution
    assert service.acquire("engine", run["id"])
    return service.prepare("engine", run["id"], task)


def test_dag_three_simulators_leave_iv_uncommitted(execution):
    service, _, simulator, run, scenario = execution
    dsn = scenario[3]
    command = prepare(execution)
    with pytest.raises(DomainError, match="DEPENDENCIES_PENDING"):
        service.prepare("engine", run["id"], "field")
    service.dispatch("engine", command)
    field = service.prepare("engine", run["id"], "field")
    service.dispatch("engine", field)
    iv = service.prepare("engine", run["id"], "iv")
    service.dispatch("engine", iv)
    assert (
        simulator.action_count(command)
        == simulator.action_count(field)
        == simulator.action_count(iv)
        == 1
    )
    assert (
        rows(dsn, "SELECT state FROM command_ledger WHERE id=%s", (iv,))[0]["state"] == "VERIFYING"
    )
    assert rows(dsn, "SELECT state FROM runs")[0]["state"] == "RUNNING"
    assert rows(dsn, "SELECT count(*) AS n FROM tasks")[0]["n"] == 3


def test_duplicate_delivery_never_performs_second_action(execution):
    service, gateway, simulator, _, scenario = execution
    command = prepare(execution)
    receipt = service.dispatch("engine", command)
    service.ingest("engine", command, receipt)
    with pytest.raises(DomainError, match="ALREADY_DISPATCHED"):
        service.dispatch("engine", command)
    row = rows(scenario[3], "SELECT * FROM command_ledger WHERE id=%s", (command,))[0]
    task = rows(scenario[3], "SELECT definition FROM tasks WHERE id=%s", (row["task_id"],))[0][
        "definition"
    ]
    duplicate = gateway.accept(
        service.auth.seal({"command": json.loads(bytes(row["payload_bytes"])), "task": task})
    )
    assert duplicate["payload"]["state"] == "SUCCEEDED"
    assert simulator.action_count(command) == 1


def test_lost_ack_reconciles_without_reexecution(execution, monkeypatch):
    service, gateway, simulator, run, scenario = execution
    command = prepare(execution)
    original = gateway.accept
    monkeypatch.setattr(gateway, "accept", lambda signed: original(signed, crash_at="after_result"))
    with pytest.raises(ConnectionError):
        service.dispatch("engine", command)
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "UNKNOWN"
    assert all(r["quarantined"] for r in rows(scenario[3], "SELECT * FROM resource_controls"))
    service.reconcile("engine", command)
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "PAUSED"
    assert simulator.action_count(command) == 1
    with pytest.raises(DomainError, match="LEASE_INVALID|DISPATCH_BLOCKED"):
        service.prepare("engine", run["id"], "field")
    service.release("engine", run["id"])
    assert rows(scenario[3], "SELECT * FROM resource_claims") == []


def test_central_crash_before_send_does_not_redispatch(execution):
    service, _, simulator, _, scenario = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        service.dispatch("engine", command, crash_after_commit=True)
    service.mark_unknown("engine", command)
    with pytest.raises(DomainError, match="LEASE_INVALID|ALREADY_DISPATCHED"):
        service.dispatch("engine", command)
    with pytest.raises(DomainError, match="JOURNAL_MISSING"):
        service.reconcile("engine", command)
    assert simulator.action_count(command) == 0
    assert rows(scenario[3], "SELECT status FROM command_deliveries")[0]["status"] == "ATTEMPTED"


@pytest.mark.parametrize("point", ["after_accept", "before_execute", "after_execute"])
def test_gateway_restart_keeps_nonterminal_journal_without_replay(execution, monkeypatch, point):
    service, gateway, simulator, _, scenario = execution
    command = prepare(execution)
    original = gateway.accept
    monkeypatch.setattr(gateway, "accept", lambda signed: original(signed, crash_at=point))
    with pytest.raises(ConnectionError):
        service.dispatch("engine", command)
    count = simulator.action_count(command)
    gateway.close()
    restarted = Gateway(
        "gw",
        gateway.path,
        authenticator=gateway.auth,
        catalog=gateway.catalog,
        simulator=simulator,
        skills=gateway.skills,
        policy_versions=gateway.policies,
        capability_versions=gateway.capabilities,
    )
    service.gateways["gw"] = restarted
    with pytest.raises(DomainError, match="RECONCILIATION_PENDING"):
        service.reconcile("engine", command)
    assert simulator.action_count(command) == count == (1 if point == "after_execute" else 0)
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "UNKNOWN"


def test_revocation_after_prepare_blocks_send(execution):
    service, _, simulator, run, scenario = execution
    command = prepare(execution)
    base = scenario[0]
    current = rows(scenario[3], "SELECT * FROM experiments")[0]
    approval = rows(scenario[3], "SELECT * FROM approvals")[0]
    base.decide_approval(
        "approver",
        experiment_id=EXP,
        approval_id=approval["id"],
        event="revoke",
        expected_revision=current["revision"],
        expected_version=approval["state_version"],
        key="revoke-live",
    )
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "PAUSE_REQUESTED"
    with pytest.raises(DomainError, match="APPROVAL_INVALID"):
        service.dispatch("engine", command)
    assert simulator.action_count(command) == 0


def test_multi_resource_contention_is_all_or_nothing(execution):
    service, _, _, run, scenario = execution
    base, _, _, dsn = scenario
    approval = rows(dsn, "SELECT * FROM approvals")[0]
    revision = rows(dsn, "SELECT revision FROM experiments")[0]["revision"]
    other = base.start_run(
        "owner",
        experiment_id=EXP,
        approval_id=approval["id"],
        expected_revision=revision,
        key="run-two",
    )
    barrier = Barrier(2)

    def worker(identity):
        barrier.wait(timeout=5)
        return service.acquire("engine", identity)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(worker, [run["id"], other["id"]]))
    assert sorted(map(len, outcomes)) == [0, 3]
    claims = rows(dsn, "SELECT * FROM resource_claims")
    assert len({r["holder_run_id"] for r in claims}) == 1 and len(claims) == 3


def test_expired_lease_keeps_claim_and_quarantine(execution):
    service, _, _, run, scenario = execution
    service.acquire("engine", run["id"], duration_s=0.01)
    with psycopg.connect(scenario[3]) as connection:
        connection.execute("SELECT pg_sleep(0.02)")
    assert service.expire_leases("engine", run["id"]) == 3
    assert len(rows(scenario[3], "SELECT * FROM resource_claims")) == 3
    assert all(r["quarantined"] for r in rows(scenario[3], "SELECT * FROM resource_controls"))
    with pytest.raises(DomainError, match="LEASE_INVALID"):
        service.prepare("engine", run["id"], "temperature")


def test_epoch_recovery_rejects_old_signed_command(execution):
    service, gateway, _, _, scenario = execution
    command = prepare(execution)
    service.dispatch("engine", command)
    row = rows(scenario[3], "SELECT * FROM command_ledger")[0]
    task = rows(scenario[3], "SELECT definition FROM tasks WHERE id=%s", (row["task_id"],))[0][
        "definition"
    ]
    old = service.auth.seal({"command": json.loads(bytes(row["payload_bytes"])), "task": task})
    epoch = service.begin_recovery("engine")
    with pytest.raises(DomainError, match="GATEWAY_OFFLINE"):
        service.finish_recovery("engine")
    service.bind_gateway("engine", "gw")
    service.finish_recovery("engine")
    assert str(rows(scenario[3], "SELECT epoch FROM control_generation")[0]["epoch"]) == epoch
    with pytest.raises(DomainError, match="OLD_EPOCH"):
        gateway.accept(old)
    assert rows(scenario[3], "SELECT * FROM resource_claims") == []


def test_forged_or_mismatched_receipt_cannot_advance_state(execution):
    service, _, _, _, scenario = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        service.dispatch("engine", command, crash_after_commit=True)
    payload = {
        "gateway_id": "other",
        "epoch": str(rows(scenario[3], "SELECT epoch FROM control_generation")[0]["epoch"]),
        "command_id": command,
        "payload_hash": "0" * 64,
        "receipt_seq": 1,
        "state": "SUCCEEDED",
    }
    with pytest.raises(DomainError, match="RECEIPT_MISMATCH"):
        service.ingest("engine", command, service.auth.seal(payload))
    signed = service.auth.seal(payload)
    signed["signature"] = "0" * 64
    with pytest.raises(DomainError, match="UNAUTHENTICATED"):
        service.ingest("engine", command, signed)
    assert rows(scenario[3], "SELECT state FROM command_ledger")[0]["state"] == "DISPATCHED"


@pytest.mark.parametrize(
    "point,expected",
    [
        ("after_accept", "REJECTED_BEFORE_EXECUTE"),
        ("before_execute", "REJECTED_BEFORE_EXECUTE"),
        ("after_execute", "SUCCEEDED"),
    ],
)
def test_explicit_restarted_simulator_reconciliation(execution, monkeypatch, point, expected):
    service, gateway, simulator, _, scenario = execution
    command = prepare(execution)
    original = gateway.accept
    monkeypatch.setattr(gateway, "accept", lambda signed: original(signed, crash_at=point))
    with pytest.raises(ConnectionError):
        service.dispatch("engine", command)
    gateway.close()
    restarted = Gateway(
        "gw",
        gateway.path,
        authenticator=gateway.auth,
        catalog=gateway.catalog,
        simulator=simulator,
        skills=gateway.skills,
        policy_versions=gateway.policies,
        capability_versions=gateway.capabilities,
    )
    service.gateways["gw"] = restarted
    service.reconcile("engine", command, recover_gateway=True)
    assert rows(scenario[3], "SELECT state FROM command_ledger")[0]["state"] == expected
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "PAUSED"
    assert simulator.action_count(command) == (1 if point == "after_execute" else 0)


def signed_command(execution):
    service, _, _, _, scenario = execution
    command = prepare(execution)
    row = rows(scenario[3], "SELECT * FROM command_ledger WHERE id=%s", (command,))[0]
    task = rows(scenario[3], "SELECT definition FROM tasks WHERE id=%s", (row["task_id"],))[0][
        "definition"
    ]
    return {"command": json.loads(bytes(row["payload_bytes"])), "task": task}


def test_gateway_rejects_old_token_and_conflicting_lease(execution):
    service, gateway, simulator, _, _ = execution
    package = signed_command(execution)
    package["command"]["fencing_token"] = 10
    gateway.accept(service.auth.seal(package))
    old = deepcopy(package)
    old["command"]["command_id"] = "old-token"
    old["command"]["fencing_token"] = 9
    with pytest.raises(DomainError, match="STALE_FENCE"):
        gateway.accept(service.auth.seal(old))
    old["command"]["fencing_token"] = 10
    old["command"]["lease_id"] = "different-owner"
    with pytest.raises(DomainError, match="STALE_FENCE"):
        gateway.accept(service.auth.seal(old))
    assert simulator.action_count("old-token") == 0


def test_gateway_duplicate_id_must_match_bytes(execution):
    service, gateway, simulator, _, _ = execution
    package = signed_command(execution)
    gateway.accept(service.auth.seal(package))
    changed = deepcopy(package)
    changed["command"]["parameters"]["target_kelvin"] = 296
    changed["task"]["parameters"]["target_kelvin"] = 296
    with pytest.raises(DomainError, match="COMMAND_CONFLICT"):
        gateway.accept(service.auth.seal(changed))
    assert simulator.action_count(package["command"]["command_id"]) == 1


@pytest.mark.parametrize(
    "change,error",
    [
        ("expired", "DEADLINE_EXPIRED"),
        ("policy", "POLICY_MISMATCH"),
        ("signature", "UNAUTHENTICATED"),
    ],
)
def test_gateway_authorization_gates(execution, change, error):
    service, gateway, simulator, _, _ = execution
    package = signed_command(execution)
    if change == "expired":
        package["command"]["issued_at"] = "2020-01-01T00:00:00+00:00"
        package["command"]["deadline_at"] = "2020-01-01T00:00:01+00:00"
    elif change == "policy":
        package["command"]["policy_version"] = "unapproved"
    signed = service.auth.seal(package)
    if change == "signature":
        signed["signature"] = "0" * 64
    with pytest.raises(DomainError, match=error):
        gateway.accept(signed)
    assert simulator.action_count(package["command"]["command_id"]) == 0


def test_gateway_has_one_process_owner(execution):
    _, gateway, simulator, _, _ = execution
    with pytest.raises(DomainError, match="GATEWAY_ALREADY_RUNNING"):
        Gateway(
            "gw",
            gateway.path,
            authenticator=gateway.auth,
            catalog=gateway.catalog,
            simulator=simulator,
            skills=gateway.skills,
            policy_versions=gateway.policies,
            capability_versions=gateway.capabilities,
        )


def test_lease_renewal_preserves_binding_and_token(execution):
    service, _, _, run, scenario = execution
    service.acquire("engine", run["id"], duration_s=10)
    before = rows(scenario[3], "SELECT * FROM leases ORDER BY id")
    service.renew("engine", run["id"], duration_s=20)
    after = rows(scenario[3], "SELECT * FROM leases ORDER BY id")
    for old, new in zip(before, after, strict=True):
        assert new["token"] == old["token"] and new["binding_hash"] == old["binding_hash"]
        assert (
            new["state_version"] == old["state_version"] + 1
            and new["expires_at"] > old["expires_at"]
        )
    with pytest.raises(DomainError, match="INVALID_RENEWAL"):
        service.renew("engine", run["id"], duration_s=1)


def test_unknown_effects_rollback_with_outbox_failure(execution, monkeypatch):
    from alap.adapters.postgres.repository import PostgresRepository

    service, _, _, _, scenario = execution
    command = prepare(execution)
    with pytest.raises(ConnectionError):
        service.dispatch("engine", command, crash_after_commit=True)
    original = PostgresRepository.insert

    def fail(self, table, values):
        if table == "outbox_events":
            raise RuntimeError("injected")
        return original(self, table, values)

    with monkeypatch.context() as patch:
        patch.setattr(PostgresRepository, "insert", fail)
        with pytest.raises(RuntimeError):
            service.mark_unknown("engine", command)
    assert rows(scenario[3], "SELECT state FROM command_ledger")[0]["state"] == "DISPATCHED"
    assert not any(r["quarantined"] for r in rows(scenario[3], "SELECT * FROM resource_controls"))
    service.mark_unknown("engine", command)
    assert all(r["quarantined"] for r in rows(scenario[3], "SELECT * FROM resource_controls"))


def test_cross_experiment_resource_race(execution):
    from psycopg.types.json import Jsonb

    service, _, _, run, scenario = execution
    base, _, revision, dsn = scenario
    base.create_experiment("owner", experiment_id="exp-two", sample_id="sample", key="create-two")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE experiment_memberships SET scope=%s WHERE experiment_id='exp-two'",
            (
                Jsonb(
                    {
                        "resources": revision["proposal"]["requested_resources"],
                        "risk_levels": ["operator_review"],
                    }
                ),
            ),
        )
    second = deepcopy(revision)
    second["plan_revision_id"] = "plan-two"
    second["proposal"]["experiment_id"] = "exp-two"
    saved = base.save_plan(
        "owner", experiment_id="exp-two", revision=second, expected_revision=1, key="save-two"
    )
    request = base.request_approval(
        "owner",
        experiment_id="exp-two",
        plan_id=saved["id"],
        plan_hash=saved["plan_hash"],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        expected_revision=2,
        key="request-two",
    )
    base.decide_approval(
        "owner",
        experiment_id="exp-two",
        approval_id=request["id"],
        event="approve",
        expected_revision=3,
        expected_version=0,
        key="approve-two",
    )
    other = base.start_run(
        "owner",
        experiment_id="exp-two",
        approval_id=request["id"],
        expected_revision=4,
        key="run-two",
    )
    barrier = Barrier(2)

    def acquire(identity):
        barrier.wait(5)
        return service.acquire("engine", identity)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(acquire, [run["id"], other["id"]]))
    assert sorted(map(len, results)) == [0, 3]
    assert len({c["holder_run_id"] for c in rows(dsn, "SELECT * FROM resource_claims")}) == 1


@pytest.mark.parametrize("execution", ["parallel"], indirect=True)
def test_parallel_unknown_commands_can_reconcile_one_at_a_time(execution):
    service, gateway, _, run, scenario = execution
    first = prepare(execution)
    second = service.prepare("engine", run["id"], "field")
    for command_id in (first, second):
        with pytest.raises(ConnectionError):
            service.dispatch("engine", command_id, crash_after_commit=True)
        row = rows(scenario[3], "SELECT * FROM command_ledger WHERE id=%s", (command_id,))[0]
        task = rows(scenario[3], "SELECT definition FROM tasks WHERE id=%s", (row["task_id"],))[0][
            "definition"
        ]
        gateway.accept(
            service.auth.seal({"command": json.loads(bytes(row["payload_bytes"])), "task": task})
        )
    assert len(service.recover_inflight("engine")) == 2
    service.reconcile("engine", first)
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "NEEDS_RECONCILIATION"
    service.reconcile("engine", second)
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "PAUSED"


@pytest.mark.parametrize("execution", ["single"], indirect=True)
def test_complete_run_and_release_allows_next_holder(execution):
    service, _, _, run, scenario = execution
    command = prepare(execution)
    service.dispatch("engine", command)
    assert rows(scenario[3], "SELECT state FROM runs")[0]["state"] == "SUCCEEDED"
    service.release("engine", run["id"])
    assert rows(scenario[3], "SELECT * FROM resource_claims") == []
    approval = rows(scenario[3], "SELECT * FROM approvals")[0]
    revision = rows(scenario[3], "SELECT revision FROM experiments")[0]["revision"]
    new = scenario[0].start_run(
        "owner",
        experiment_id=EXP,
        approval_id=approval["id"],
        expected_revision=revision,
        key="next",
    )
    service.acquire("engine", new["id"])
    assert rows(scenario[3], "SELECT token FROM resource_claims")[0]["token"] == 2


def test_late_acceptance_cannot_regress_success_and_conflict_is_audited(execution):
    service, _, _, _, scenario = execution
    command = prepare(execution)
    original = service.dispatch("engine", command)["payload"]
    late = {**original, "state": "ACCEPTED", "receipt_seq": original["receipt_seq"] + 100}
    service.ingest("engine", command, service.auth.seal(late))
    assert rows(scenario[3], "SELECT state FROM command_ledger")[0]["state"] == "SUCCEEDED"
    conflict = {
        **original,
        "state": "FAILED_CONFIRMED",
        "receipt_seq": original["receipt_seq"] + 101,
    }
    service.ingest("engine", command, service.auth.seal(conflict))
    assert rows(scenario[3], "SELECT state FROM command_ledger")[0]["state"] == "SUCCEEDED"
    assert rows(scenario[3], "SELECT * FROM transition_audit WHERE kind='incident'")
    assert all(c["quarantined"] for c in rows(scenario[3], "SELECT * FROM resource_controls"))


def test_actual_process_exit_after_simulated_action(execution):
    import subprocess
    import sys
    from pathlib import Path

    service, gateway, simulator, _, scenario = execution
    package = signed_command(execution)
    command = package["command"]["command_id"]
    with pytest.raises(ConnectionError):
        service.dispatch("engine", command, crash_after_commit=True)
    config = {
        "journal": str(gateway.path),
        "physical": str(simulator.path),
        "key": gateway.auth._key.hex(),
        "skills": gateway.skills,
        "policies": gateway.policies,
        "capabilities": gateway.capabilities,
        "package": package,
        "contracts": str(Path(__file__).resolve().parents[2] / "contracts"),
    }
    gateway.close()
    child = r"""
import json,os,sys
from pathlib import Path
from alap.adapters.gateway.auth import Authenticator
from alap.adapters.gateway.journal import Gateway
from alap.adapters.gateway.simulator import Simulator,WallClock
from alap.contracts import ContractCatalog
c=json.load(sys.stdin)
a=Authenticator(bytes.fromhex(c['key']))
s=Simulator(c['physical'],WallClock())
g=Gateway('gw',c['journal'],authenticator=a,catalog=ContractCatalog(Path(c['contracts'])),
          simulator=s,skills=c['skills'],policy_versions=c['policies'],capability_versions=c['capabilities'])
original=s.execute
def crash(command,task):
    original(command,task)
    os._exit(42)
s.execute=crash
g.accept(a.seal(c['package']))
"""
    result = subprocess.run(
        [sys.executable, "-c", child],
        input=json.dumps(config),
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 42, result.stderr
    restarted = Gateway(
        "gw",
        gateway.path,
        authenticator=gateway.auth,
        catalog=gateway.catalog,
        simulator=simulator,
        skills=gateway.skills,
        policy_versions=gateway.policies,
        capability_versions=gateway.capabilities,
    )
    service.gateways["gw"] = restarted
    service.recover_inflight("engine")
    service.reconcile("engine", command, recover_gateway=True)
    assert simulator.action_count(command) == 1
    assert rows(scenario[3], "SELECT state FROM command_ledger")[0]["state"] == "SUCCEEDED"
