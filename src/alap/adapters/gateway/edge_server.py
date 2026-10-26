"""Run the standalone local simulation monitor foundation (no devices or RPC)."""

import argparse
import json
import signal
from pathlib import Path
from threading import Event

from alap.adapters.gateway.edge import SimulationEdgeMonitor
from alap.domain.edge_policy import SimulationLossPolicy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config["mode"] != "simulation":
        parser.error("Only simulation mode allowed")
    policy = SimulationLossPolicy(**config["loss_policy"])
    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)
    }
    monitor = SimulationEdgeMonitor(config["state_path"], policy)
    try:
        print(json.dumps({"event": "edge_monitor_ready"}), flush=True)
        while not stop.wait(min(0.05, policy.timeout_s / 4)):
            monitor.scan()
    finally:
        monitor.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
