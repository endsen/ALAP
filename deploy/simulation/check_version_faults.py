"""D12d.3 deployed immutable model/Skill bindings and unavailable capabilities."""

from check_agent import main
from manage import ROOT

from alap.adapters.ops.locking import maintenance_lock

if __name__ == "__main__":
    with maintenance_lock(ROOT / ".local-deploy/operations.lock"):
        raise SystemExit(main(versions=True))
