"""Restore fencing and real committed dataset audit; uses the normal execution adapters."""

import pytest

from alap.adapters.ops.inspection import audit, metrics
from alap.application.engine_recovery import EngineRecovery
from alap.domain.rules import DomainError

from .conftest import rows
from .test_datasets import acquisition, stage  # noqa: F401
from .test_execution import execution  # noqa: F401

pytestmark = pytest.mark.postgres


def test_restored_recovering_database_gets_new_epoch_and_no_dispatch(execution):  # noqa: F811
    engine, _, simulator, run, scenario = execution
    recovery = EngineRecovery(engine, "engine")
    previous = recovery.begin()
    restored = recovery.begin(force_new_epoch=True)
    assert previous != restored
    assert rows(scenario[3], "SELECT dispatch_blocked FROM runs WHERE id=%s", (run["id"],))[0][
        "dispatch_blocked"
    ]
    assert rows(scenario[3], "SELECT mode FROM control_generation")[0]["mode"] == "RECOVERING"
    assert rows(scenario[3], "SELECT count(*) AS n FROM command_ledger")[0]["n"] == 0
    with simulator.connect() as db:
        assert db.execute("SELECT count(*) FROM actions").fetchone()[0] == 0
    # Default repeated startup still reuses the same in-progress generation.
    assert recovery.begin() == restored


def test_audit_real_committed_data_and_corruption(acquisition):  # noqa: F811
    service, _, _, (_, gateway, _, _, scenario) = acquisition
    identity = stage(acquisition)
    service.commit("engine", identity)
    report = audit(scenario[3], service.store.root, gateway.path.parent)
    assert report["committed_datasets_verified"] == 1
    path = service.store.root / service.store.key(identity)
    path.write_bytes(b"corrupted backup content")
    with pytest.raises(DomainError, match="ARTIFACT_INVALID"):
        audit(scenario[3], service.store.root, gateway.path.parent)


def test_metrics_report_authoritative_recovery_state(execution):  # noqa: F811
    engine, _, _, _, scenario = execution
    report = metrics(scenario[3])
    assert report["database_reachable"]
    assert report["control"]["mode"] == "ACTIVE"
    assert report["outbox"]["pending"] > 0
    assert report["outbox"]["oldest_age_s"] >= 0
    EngineRecovery(engine, "engine").begin(force_new_epoch=True)
    after = metrics(scenario[3])
    assert after["control"]["mode"] == "RECOVERING"
    assert "RECOVERY_GATE_CLOSED" in after["alerts"]
