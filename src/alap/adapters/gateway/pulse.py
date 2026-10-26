"""Engine-only heartbeat during one command call; never replay physical dispatch."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, Thread

from alap.domain.rules import DomainError


@contextmanager
def command_heartbeat(port, command, check):
    stop = Event()

    def loop():
        sequence = 0
        while not stop.is_set():
            try:
                check(command)
                status = port._call(
                    "edge_status",
                    {"command_id": command["command_id"]},
                    authenticator=port.supervision_auth,
                    path="/supervision",
                    timeout=1,
                )
                if status["mode"] == "TRIPPED":
                    return
                now = datetime.now(UTC)
                port._call(
                    "edge_heartbeat",
                    {
                        "command_id": command["command_id"],
                        "epoch": command["control_epoch"],
                        "generation": status["generation"],
                        "sequence": sequence,
                        "issued_at": now.isoformat(),
                        "expires_at": (now + timedelta(seconds=1)).isoformat(),
                    },
                    authenticator=port.supervision_auth,
                    path="/supervision",
                    timeout=1,
                )
                sequence += 1
            except DomainError as exc:
                if exc.code != "EDGE_COMMAND_PENDING":
                    return
            except ConnectionError:
                # Losing an acknowledgement must not reuse a sequence number.
                sequence += 1
            except Exception:
                return  # Ownership/authorization check failures stop supervision.
            stop.wait(0.1)

    worker = Thread(target=loop, name="alap-command-heartbeat", daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=3)
