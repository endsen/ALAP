"""Run the foundation quality gate, identically on developer machines and CI."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    commands = [
        ["-m", "ruff", "check", "."],
        ["-m", "ruff", "format", "--check", "."],
        ["scripts/build_lifecycle_reference.py", "--check"],
        ["scripts/build_design.py", "--check"],
        ["scripts/build_openapi.py", "--check"],
        ["contracts/validate_contracts.py"],
        ["-m", "pytest", "-q"],
        ["-m", "pip", "check"],
    ]
    for command in commands:
        print(f"\n> python {' '.join(command)}", flush=True)
        subprocess.run([sys.executable, *command], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
