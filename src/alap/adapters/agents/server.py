"""Advance existing Agent runs; starting this process enables configured model API usage."""

import argparse
import json
import math
import os
import signal
import sys
import time
from pathlib import Path
from threading import Event

from alap.adapters.agents.bootstrap import build_agent
from alap.adapters.postgres.repository import PostgresUnitOfWork
from alap.adapters.postgres.settings import database_url
from alap.adapters.storage.hdf5 import Hdf5Store
from alap.application.agent_worker import AgentWorker
from alap.application.datasets import DatasetService
from alap.application.execution import ExecutionService
from alap.application.experiments import ExperimentService
from alap.contracts import ContractCatalog


def build_worker(dsn, key, settings, stop):
    if settings["mode"] != "simulation":
        raise ValueError("Only simulation deployment is supported")
    catalog = ContractCatalog(Path(__file__).resolve().parents[4] / "contracts")
    base = ExperimentService(
        PostgresUnitOfWork(dsn),
        catalog,
        skills=settings["execution_skills"],
        policy_versions=settings["policy_versions"],
        capability_versions=settings["capability_versions"],
    )
    # Dataset reads share the API artifact root. No Gateway ports are available to this process.
    data = DatasetService(
        ExecutionService(base, authenticator=None, gateways={}),
        Hdf5Store(settings["artifact_root"]),
    )
    _, _, _, manager, _, runtime = build_agent(dsn, key, catalog, base.skills, data)
    return AgentWorker(
        runtime,
        settings["agent_actor"],
        settings["experiment_ids"],
        limit=settings.get("batch_size", 20),
        refresh=manager,
        cancel=stop,
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
        if not math.isfinite(poll_s) or not 0.05 <= poll_s <= 60:
            raise ValueError("Polling interval must be 0.05..60 seconds")
        worker = build_worker(
            database_url(),
            Path(os.environ["ALAP_MASTER_KEY_FILE"]).read_bytes().strip(),
            settings,
            stop,
        )
        last, heartbeat = None, 0
        while not stop.is_set():
            report = json.dumps(worker.tick(), sort_keys=True)
            if report != last or time.monotonic() - heartbeat >= 30:
                print(report, flush=True)
                last, heartbeat = report, time.monotonic()
            stop.wait(poll_s)
        print(json.dumps({"event": "agent_stopped"}), flush=True)
        return 0
    except Exception as exc:
        print(
            json.dumps({"event": "agent_failed", "code": getattr(exc, "code", "AGENT_ERROR")}),
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
