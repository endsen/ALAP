"""D12d.3 committed Agent tool boundary deployment recovery."""

from check_agent import main
from manage import ROOT

from alap.adapters.ops.locking import maintenance_lock

if __name__ == "__main__":
    with maintenance_lock(ROOT / ".local-deploy/operations.lock"):
        raise SystemExit(main(tool_recovery=True))
