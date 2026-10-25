"""D12d.3 real HTTPS bounded retries and no replay after partial output."""

from check_agent import main
from manage import ROOT

from alap.adapters.ops.locking import maintenance_lock

if __name__ == "__main__":
    with maintenance_lock(ROOT / ".local-deploy/operations.lock"):
        raise SystemExit(main(retries=True))
