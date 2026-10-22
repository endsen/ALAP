"""Real Chromium data fault/recovery acceptance against Compose services."""

from check_data_fault import main
from manage import ROOT

from alap.adapters.ops.locking import maintenance_lock

if __name__ == "__main__":
    with maintenance_lock(ROOT / ".local-deploy/operations.lock"):
        main(browser=True)
