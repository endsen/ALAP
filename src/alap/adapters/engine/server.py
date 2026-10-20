"""Run the simulation engine with existing database identities and approved Runs."""

import argparse
import json
import math
import signal
import sys
import time
from pathlib import Path
from threading import Event

from alap.adapters.gateway.config import build_gateway_ports
from alap.adapters.postgres.engine_owner import OwnedGateway, PostgresEngineOwner
from alap.adapters.postgres.settings import database_url
from alap.adapters.storage.hdf5 import Hdf5Store
from alap.application.datasets import DatasetService
from alap.application.engine_worker import EngineWorker
from alap.application.execution import ExecutionService
from alap.application.experiments import ExperimentService
from alap.contracts import ContractCatalog


def build_worker(owner, settings, stopping):
    if settings["mode"] != "simulation":
        raise ValueError("Only explicitly configured simulation deployment is supported")
    auth, ports = build_gateway_ports(settings["gateway_transport"])
    base = ExperimentService(
        owner.transaction,
        ContractCatalog(Path(__file__).resolve().parents[4] / "contracts"),
        skills=settings["execution_skills"],
        policy_versions=settings["policy_versions"],
        capability_versions=settings["capability_versions"],
    )
    engine = ExecutionService(
        base,
        authenticator=auth,
        gateways={identity: OwnedGateway(owner, port) for identity, port in ports.items()},
    )
    datasets = DatasetService(engine, Hdf5Store(settings["artifact_root"]))
    return EngineWorker(
        engine,
        datasets,
        settings["engine_actor"],
        lease_s=settings.get("lease_s", 300),
        stopping=stopping,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        settings = json.loads(args.config.read_text())
        poll_s = settings.get("poll_s", 0.5)
        if not math.isfinite(poll_s) or not 0.05 <= poll_s <= settings.get("lease_s", 300) / 4:
            raise ValueError("Polling interval must be finite, >=0.05s and <= one quarter lease")
        with PostgresEngineOwner(database_url()) as owner:
            worker = build_worker(owner, settings, stop.is_set)
            previous_report, heartbeat = None, 0
            while not stop.is_set():
                report = worker.tick()
                encoded = json.dumps(report, sort_keys=True)
                if encoded != previous_report or time.monotonic() - heartbeat >= 30:
                    print(encoded, flush=True)
                    previous_report, heartbeat = encoded, time.monotonic()
                stop.wait(poll_s)
        print(json.dumps({"event": "engine_stopped"}), flush=True)
        return 0
    except Exception as exc:
        # Configuration, DSN, credentials and device payloads never enter default logs.
        print(
            json.dumps({"event": "engine_failed", "code": getattr(exc, "code", "ENGINE_ERROR")}),
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
