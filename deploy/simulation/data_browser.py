"""Private file barrier coordinates real browser recovery with artifact restoration."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from manage import ROOT

from alap.adapters.ops.archive import private_write


def check_browser(seed, dataset, mode, checksum, restore):
    with tempfile.TemporaryDirectory(prefix="data-browser-", dir=ROOT / ".local-deploy") as temp:
        directory = Path(temp)
        state = {
            "owner": seed["owner"],
            "dataset": dataset,
            "mode": mode,
            "checksum": checksum,
            "directory": temp,
        }
        private_write(directory / "state.json", json.dumps(state).encode())
        with (directory / "output.log").open("w+") as output:
            child = subprocess.Popen(
                [
                    "npm",
                    "exec",
                    "--",
                    "playwright",
                    "test",
                    "--config",
                    "playwright.deployment.config.ts",
                    "data-fault.spec.ts",
                    "--output",
                    str(directory / "results"),
                ],
                cwd=ROOT / "apps/web",
                env=os.environ
                | {
                    "ALAP_COMPOSE_BROWSER_STATE": str(directory / "state.json"),
                    "PLAYWRIGHT_BROWSERS_PATH": str(ROOT / ".local-deploy/browsers"),
                },
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            restored = False
            deadline = time.monotonic() + 130
            try:
                while child.poll() is None and time.monotonic() < deadline:
                    if not restored and (directory / "ready").exists():
                        restore()
                        restored = True
                        (directory / "restored").touch()
                    time.sleep(0.1)
                assert child.poll() == 0, "Browser data fault check failed"
                assert restored
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                output.seek(0)
                (ROOT / f"reports/d12d3-data-browser-{mode}.txt").write_text(
                    output.read().replace(seed["owner"], "[REDACTED]")
                )
