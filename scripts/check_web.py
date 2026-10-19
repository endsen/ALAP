"""D10 Web gate. Requires Node 24, npm ci, Chromium and isolated PostgreSQL."""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps/web"


def main():
    env = os.environ | {"NEXT_TELEMETRY_DISABLED": "1", "ALAP_API_ORIGIN": "http://127.0.0.1:58000"}
    if not env.get("ALAP_TEST_DATABASE_URL"):
        sys.exit("ALAP_TEST_DATABASE_URL is required; browser integration must not be skipped")

    def run(command):
        print("> " + " ".join(command), flush=True)
        subprocess.run(command, cwd=WEB, env=env, check=True)

    with TemporaryDirectory(prefix="alap-web-contract-") as temp:
        output = str(Path(temp) / "api.d.ts")
        run(
            [
                "npm",
                "exec",
                "--",
                "openapi-typescript",
                "../../contracts/openapi.yaml",
                "-o",
                output,
            ]
        )
        if Path(output).read_bytes() != (WEB / "src/generated/api.d.ts").read_bytes():
            sys.exit("Generated API types drifted; run npm run contracts")
    run(["npm", "run", "format:check"])
    run(["npm", "run", "typecheck"])
    run(["npm", "test"])
    run(["npm", "run", "build"])
    run(["npm", "run", "test:e2e"])


if __name__ == "__main__":
    main()
