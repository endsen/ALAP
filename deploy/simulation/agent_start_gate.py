"""Test-only startup barrier before exec of the unchanged Agent server."""

import os
import sys
import time
from pathlib import Path

if __name__ == "__main__":
    deadline = time.monotonic() + 90
    while not Path("/control/agent-start").exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("Agent fixture startup gate")
        time.sleep(0.05)
    os.execv(sys.executable, [sys.executable, "-m", "alap.adapters.agents.server", *sys.argv[1:]])
