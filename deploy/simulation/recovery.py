"""One-shot restore fencing/checking; deliberately never runs the scheduling worker."""

import argparse
import json
from pathlib import Path

from alap.adapters.engine.server import build_worker
from alap.adapters.ops.inspection import audit
from alap.adapters.postgres.engine_owner import PostgresEngineOwner
from alap.adapters.postgres.settings import database_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["fence", "audit", "check"])
    args = parser.parse_args()
    settings = json.loads(Path("/config/engine.json").read_text())
    if settings["mode"] != "simulation":
        raise ValueError("Restore drills are simulation only")
    with PostgresEngineOwner(database_url()) as owner:
        worker = build_worker(owner, settings, lambda: True)
        if args.action == "fence":
            epoch = worker.recovery.begin(force_new_epoch=True)
            print(json.dumps({"event": "restore_fenced", "epoch": epoch}))
            return
        with owner.transaction() as repo:
            if repo.generation()["mode"] != "RECOVERING":
                raise ValueError("Restore must be fenced before checking")
        if args.action == "audit":
            # The host orchestrator stops the Gateway before this command.
            result = audit(database_url(), "/artifacts", "/gateway-audit")
            print(json.dumps({"event": "restore_audited", "audit": result}))
            return
        worker.recovery.started = True
        report = worker.recovery.advance()
        print(json.dumps({"event": "restore_checked", "recovery": report}))
        if report["mode"] != "ACTIVE":
            raise SystemExit(2)
        # No worker.tick, no dispatch, no automatic resume or model call.


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            json.dumps(
                {"event": "restore_check_failed", "code": getattr(exc, "code", type(exc).__name__)}
            )
        )
        raise SystemExit(1) from None
