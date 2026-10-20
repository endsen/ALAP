"""Explicit rootless simulation deployment commands; never implicitly migrate on startup."""

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy/simulation"


def environment(directory):
    env = dict(os.environ)
    env.setdefault("DOCKER_HOST", f"unix://{ROOT}/.local-deploy/run/docker.sock")
    env["SIM_ROOT"] = str(directory)
    for line in (DEPLOY / "images.env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key] = value
    return env


def run(command, env):
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["prepare", "build", "initialize", "up", "status", "token", "stop"]
    )
    parser.add_argument("--directory", type=Path, default=ROOT / ".local-deploy/simulation")
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.action == "prepare":
        from prepare import prepare

        prepare(directory)
        return
    env = environment(directory)
    docker = str(ROOT / ".local-deploy/bin/docker")
    compose = [str(ROOT / ".local-deploy/bin/docker-compose"), "-f", str(DEPLOY / "compose.yaml")]
    options = json.loads(
        subprocess.check_output(
            [docker, "info", "--format", "{{json .SecurityOptions}}"],
            env=env,
            text=True,
        )
    )
    if "name=rootless" not in options:
        raise ValueError("This simulation profile requires rootless Docker")
    if args.action == "build":
        # The bundled static Docker distribution has no buildx plugin. Explicit
        # legacy builds work locally; Compose uses the resulting local images.
        for component, base in (("backend", "PYTHON"), ("web", "NODE")):
            command = [
                docker,
                "build",
                "-f",
                str(DEPLOY / f"{component}.Dockerfile"),
                "--build-arg",
                f"{base}_IMAGE={env[base + '_IMAGE']}",
                "-t",
                f"alap-{component}:simulation",
            ]
            proxy = env.get("BUILD_HTTP_PROXY")
            if proxy:
                command += [
                    "--build-arg",
                    "HTTP_PROXY=" + proxy,
                    "--build-arg",
                    "HTTPS_PROXY=" + proxy,
                ]
            run(command + ["."], env | {"DOCKER_BUILDKIT": "0"})
    elif args.action == "initialize":
        if not (directory / "prepared").is_file() or (directory / "deployment").exists():
            raise ValueError("Fresh prepared directory required; inspect partial initialization")
        run(compose + ["run", "--rm", "initialize"], env)
    elif args.action == "up":
        if not (directory / "ready").is_file():
            raise ValueError("Explicit initialization must complete first")
        run(compose + ["up", "-d", "--no-build", "--pull", "never"], env)
    elif args.action == "status":
        run(compose + ["ps", "--all"], env)
    elif args.action == "token":
        if not (directory / "ready").is_file():
            raise ValueError("An initialized simulation is required")
        # Capture through the trusted local container boundary, never the console.
        token = subprocess.check_output(
            compose
            + [
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "from alap.adapters.postgres.api import PostgresAPIStore; "
                "from alap.adapters.postgres.settings import database_url; "
                "print(PostgresAPIStore(database_url()).issue_token('admin'))",
            ],
            env=env,
        )
        pending = directory / "admin.token.new"
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(token)
        pending.replace(directory / "admin.token")
        print("New one-hour token saved to the private admin.token file")
    else:
        run(compose + ["stop"], env)  # Preserve volumes and credentials.


if __name__ == "__main__":
    main()
