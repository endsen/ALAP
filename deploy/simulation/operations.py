"""Encrypted cold snapshots and isolated simulation restore drills. No production restore."""

import argparse
import io
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml
from manage import DEPLOY, ROOT, environment

from alap.adapters.ops.archive import (
    PAYLOADS,
    decrypt_verified,
    encrypt_stream,
    extract_tar,
    private_write,
    read_key,
    verify_bundle,
    write_manifest,
    write_tar,
)
from alap.adapters.ops.locking import maintenance_lock

SERVICES = ("web", "api", "agent", "engine", "outbox", "gateway", "nats", "postgres")
VOLUMES = {
    "postgres": ("postgres", "/var/lib/postgresql"),
    "nats": ("nats", "/data"),
    "gateway": ("gateway", "/data"),
    "artifacts": ("engine", "/artifacts"),
}
DOCKER = str(ROOT / ".local-deploy/bin/docker")
COMPOSE = str(ROOT / ".local-deploy/bin/docker-compose")


class Runtime:
    def __init__(self, directory, project="alap-simulation", override=None):
        if not re.fullmatch(r"alap-(?:simulation|restore-[a-z0-9]{8,24})", project):
            raise ValueError("Invalid isolated project name")
        self.directory, self.project = directory, project
        self.env = environment(directory) | {"COMPOSE_PROJECT_NAME": project}
        self.compose = [COMPOSE, "-p", project, "-f", str(DEPLOY / "compose.yaml")]
        if override:
            self.compose += ["-f", str(override)]
        options = json.loads(self.output([DOCKER, "info", "--format", "{{json .SecurityOptions}}"]))
        if "name=rootless" not in options:
            raise ValueError("Rootless Docker required")

    def run(self, command, **kwargs):
        return subprocess.run(command, env=self.env, cwd=ROOT, check=True, **kwargs)

    def output(self, command):
        return subprocess.check_output(command, env=self.env, cwd=ROOT, text=True)

    def containers(self):
        ids = self.output(
            [DOCKER, "ps", "-aq", "--filter", f"label=com.docker.compose.project={self.project}"]
        ).split()
        if not ids:
            return {}
        result = {}
        for item in json.loads(self.output([DOCKER, "inspect", *ids])):
            labels = item["Config"]["Labels"]
            if labels.get("com.docker.compose.oneoff", "False").lower() == "true":
                if item["State"]["Running"]:
                    raise ValueError("Active maintenance container")
                continue
            service = labels["com.docker.compose.service"]
            if service in result:
                raise ValueError("Multiple instances of a stateful deployment service")
            result[service] = item
        return result

    def helper(self, image, volume, readonly=True, user="0:0"):
        return [
            DOCKER,
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--user",
            user,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "-v",
            volume + ":/volume" + (":ro" if readonly else ""),
            image,
            "python",
            "-c",
        ]


def assert_stopped(runtime, volumes):
    for item in runtime.containers().values():
        if item["State"]["Running"] or item["State"]["ExitCode"] == 137:
            raise ValueError("Cleanly stopped services required; inspect forced shutdown")
    for volume in volumes.values():
        if runtime.output([DOCKER, "ps", "-q", "--filter", "volume=" + volume]).strip():
            raise ValueError("A live container is using a snapshot volume")


def snapshot(runtime, destination, key_file):
    if (runtime.directory / "restored.json").exists():
        raise ValueError("Do not snapshot a drill as if it were the source deployment")
    for name in ("engine", "gateway", "agent"):
        if json.loads((runtime.directory / (name + ".json")).read_text())["mode"] != "simulation":
            raise ValueError("Simulation deployment required")
    if key_file.is_relative_to(destination) or key_file.is_relative_to(runtime.directory):
        raise ValueError("Backup key must be separate from the bundle and source credentials")
    if destination.exists() or key_file.exists():
        raise ValueError("New backup directory and key path required")
    containers = runtime.containers()
    if set(containers) != set(SERVICES):
        raise ValueError("Expected all eight source service containers")
    volumes = {}
    for name, (service, target) in VOLUMES.items():
        mount = next(m for m in containers[service]["Mounts"] if m["Destination"] == target)
        if mount["Type"] != "volume":
            raise ValueError("Expected dedicated named volumes")
        volumes[name] = mount["Name"]
    if len(set(volumes.values())) != 4:
        raise ValueError("Snapshot volumes must be distinct")
    destination.mkdir(mode=0o700)
    key = os.urandom(32)
    private_write(key_file, key)
    # Stop admission first, then execution at its normal signal boundary, then stores.
    for group in (
        ("web", "api", "agent"),
        ("engine", "outbox"),
        ("gateway", "nats"),
        ("postgres",),
    ):
        runtime.run(runtime.compose + ["stop", *group])
    assert_stopped(runtime, volumes)
    image = containers["engine"]["Image"]
    pg_image = containers["postgres"]["Image"]
    pgdata = next(
        v.split("=", 1)[1]
        for v in containers["postgres"]["Config"]["Env"]
        if v.startswith("PGDATA=")
    )
    if not pgdata.startswith("/var/lib/postgresql/"):
        raise ValueError("Unsupported PostgreSQL data layout")
    relative = pgdata.removeprefix("/var/lib/postgresql/")
    control = runtime.output(
        [
            DOCKER,
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "-v",
            volumes["postgres"] + ":/volume:ro",
            pg_image,
            "pg_controldata",
            "/volume/" + relative,
        ]
    )
    if not re.search(r"Database cluster state:\s+shut down\s*$", control, re.MULTILINE):
        raise ValueError("PostgreSQL did not shut down cleanly")
    entries = {}
    pg_uid = runtime.output(
        [DOCKER, "run", "--rm", "--network", "none", pg_image, "id", "-u", "postgres"]
    ).strip()
    if not pg_uid.isdecimal():
        raise ValueError("PostgreSQL volume owner unavailable")
    for name, volume in volumes.items():
        command = runtime.helper(image, volume, user=pg_uid if name == "postgres" else "0:0") + [
            "import sys; from alap.adapters.ops.archive import write_tar; "
            "write_tar('/volume',sys.stdout.buffer)"
        ]
        with subprocess.Popen(command, env=runtime.env, stdout=subprocess.PIPE) as process:
            try:
                entries[name] = encrypt_stream(process.stdout, destination / (name + ".aes"), key)
            except BaseException:
                process.kill()
                process.stdout.close()
                process.wait()
                raise
            if process.wait() != 0:
                raise ValueError("Volume export failed")
        print(json.dumps({"event": "snapshot_payload_exported", "payload": name}), flush=True)
    # Private configuration is small; credentials never go into Docker command arguments.
    buffer = io.BytesIO()
    write_tar(runtime.directory, buffer)
    buffer.seek(0)
    entries["secrets"] = encrypt_stream(buffer, destination / "secrets.aes", key)
    assert_stopped(runtime, volumes)
    manifest = {
        "format": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "source_project": runtime.project,
        "images": {name: value["Image"] for name, value in containers.items()},
        "entries": entries,
    }
    write_manifest(destination, manifest, key)
    print(json.dumps({"event": "cold_snapshot_completed", "source_services": "stopped"}))


def restore(bundle, key_file, destination, project):
    key = read_key(key_file)
    manifest = verify_bundle(bundle, key)
    if (
        not re.fullmatch(r"alap-restore-[a-z0-9]{8,24}", project)
        or project == manifest["source_project"]
    ):
        raise ValueError("An independent restore project is required")
    if destination.exists():
        raise ValueError("Restore directory must not exist")
    probe = Runtime(destination, project)
    if (
        probe.containers()
        or probe.output(
            [
                DOCKER,
                "volume",
                "ls",
                "-q",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ]
        ).strip()
    ):
        raise ValueError("Restore project already has resources")
    if set(manifest["images"]) != set(SERVICES):
        raise ValueError("Incomplete image identity set")
    for image in manifest["images"].values():
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise ValueError("Invalid image identity")
        probe.run([DOCKER, "image", "inspect", image], stdout=subprocess.DEVNULL)
    # Decrypt/authenticate every payload before creating any restore resources.
    with tempfile.TemporaryDirectory(prefix="alap-restore-") as temporary:
        temporary = Path(temporary)
        for name in PAYLOADS:
            decrypt_verified(
                bundle / (name + ".aes"),
                temporary / (name + ".tar"),
                manifest["entries"][name],
                key,
            )
        destination.mkdir(mode=0o700)
        with (temporary / "secrets.tar").open("rb") as stream:
            extract_tar(stream, destination)
        settings = json.loads((destination / "engine.json").read_text())
        if settings["mode"] != "simulation" or any(
            e["url"] != "https://gateway:8091"
            for e in settings["gateway_transport"]["endpoints"].values()
        ):
            raise ValueError("Restored configuration must target only the isolated simulator")
        override = destination / "restore.compose.yaml"
        services = {
            s: {"image": manifest["images"][s], "profiles": ["restore-manual"]}
            for s in SERVICES
            if s not in {"postgres", "nats", "gateway"}
        }
        for s in ("postgres", "nats", "gateway"):
            services[s] = {"image": manifest["images"][s]}
        for name, (service, target) in VOLUMES.items():
            services[service]["volumes"] = [
                {
                    "type": "volume",
                    "source": name if name == "artifacts" else name + "-data",
                    "target": target,
                    "volume": {"nocopy": True},
                }
            ]
        services["engine"]["volumes"].append("gateway-data:/gateway-audit:ro")
        config = {
            "services": services,
            "networks": {"web": {"internal": True}, "egress": {"internal": True}},
        }
        # Compose's reset tag removes inherited publish rules rather than merging lists.
        config["services"]["web"]["ports"] = "RESET_PORTS"
        text = yaml.safe_dump(config, sort_keys=False).replace(
            "ports: RESET_PORTS", "ports: !reset []"
        )
        override.write_text(text)
        private_write(
            destination / "restored.json",
            json.dumps({"project": project, "state": "importing"}).encode(),
        )
        runtime = Runtime(destination, project, override)
        # Create containers/volumes but do not start a database with an open execution gate.
        runtime.run(
            runtime.compose
            + ["--profile", "restore-manual", "create", "--no-build", "--pull", "never"]
        )
        containers = runtime.containers()
        for name, (service, target) in VOLUMES.items():
            volume = next(
                m["Name"] for m in containers[service]["Mounts"] if m["Destination"] == target
            )
            command = runtime.helper(manifest["images"]["engine"], volume, readonly=False) + [
                "import sys; from alap.adapters.ops.archive import extract_tar; "
                "extract_tar(sys.stdin.buffer,'/volume')"
            ]
            with (temporary / (name + ".tar")).open("rb") as stream:
                runtime.run(command, stdin=stream)
        runtime.run(
            runtime.compose
            + [
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "60",
                "postgres",
            ]
        )
        # Revoke copied browser sessions, retaining the original source database untouched.
        runtime.run(
            runtime.compose
            + [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "postgres",
                "-d",
                "alap_simulation",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "UPDATE alap.api_tokens SET revoked=TRUE",
            ]
        )
        runtime.run(
            runtime.compose
            + [
                "run",
                "--rm",
                "--no-deps",
                "engine",
                "python",
                "deploy/simulation/recovery.py",
                "fence",
            ]
        )
        (destination / "restored.json").write_text(
            json.dumps({"project": project, "state": "fenced"})
        )
    print(json.dumps({"event": "isolated_restore_fenced", "project": project}))


def restored_runtime(directory):
    record = json.loads((directory / "restored.json").read_text())
    if record["state"] != "fenced":
        raise ValueError("Incomplete restore requires inspection")
    return Runtime(directory, record["project"], directory / "restore.compose.yaml")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--directory", type=Path, default=ROOT / ".local-deploy/simulation")
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument("--key-file", type=Path, required=True)
    restore_cmd = sub.add_parser("restore")
    restore_cmd.add_argument("--bundle", type=Path, required=True)
    restore_cmd.add_argument("--key-file", type=Path, required=True)
    restore_cmd.add_argument("--directory", type=Path, required=True)
    restore_cmd.add_argument("--project", required=True)
    for action in ("recover", "stop-restore", "status"):
        item = sub.add_parser(action)
        item.add_argument("--directory", type=Path, default=ROOT / ".local-deploy/simulation")
    args = parser.parse_args()
    with maintenance_lock(ROOT / ".local-deploy/operations.lock"):
        directory = args.directory.resolve()
        if args.action == "backup":
            snapshot(Runtime(directory), args.output.resolve(), args.key_file.resolve())
        elif args.action == "restore":
            restore(args.bundle.resolve(), args.key_file.resolve(), directory, args.project)
        elif args.action == "recover":
            runtime = restored_runtime(directory)
            runtime.run(runtime.compose + ["stop", "gateway"])
            if runtime.containers()["gateway"]["State"]["ExitCode"] == 137:
                raise ValueError("Gateway must stop cleanly before auditing")
            runtime.run(
                runtime.compose
                + [
                    "run",
                    "--rm",
                    "--no-deps",
                    "engine",
                    "python",
                    "deploy/simulation/recovery.py",
                    "audit",
                ]
            )
            runtime.run(
                runtime.compose + ["up", "-d", "--no-build", "--pull", "never", "gateway", "nats"]
            )
            runtime.run(
                runtime.compose
                + [
                    "run",
                    "--rm",
                    "--no-deps",
                    "engine",
                    "python",
                    "deploy/simulation/recovery.py",
                    "check",
                ]
            )
        elif args.action == "stop-restore":
            runtime = restored_runtime(directory)
            runtime.run(runtime.compose + ["stop"])
        else:
            runtime = (
                restored_runtime(directory)
                if (directory / "restored.json").exists()
                else Runtime(directory)
            )
            states = {
                name: {
                    "running": c["State"]["Running"],
                    "exit_code": c["State"]["ExitCode"],
                    "health": c["State"].get("Health", {}).get("Status"),
                }
                for name, c in runtime.containers().items()
            }
            result = {
                "services": states,
                "database": None,
                "observed_at": datetime.now(UTC).isoformat(),
            }
            if states.get("postgres", {}).get("running"):
                code = (
                    "import json; from alap.adapters.ops.inspection import metrics; "
                    "from alap.adapters.postgres.settings import database_url; "
                    "print(json.dumps(metrics(database_url())))"
                )
                command = (
                    ["exec", "-T", "api"]
                    if states.get("api", {}).get("running")
                    else ["run", "--rm", "--no-deps", "-T", "api"]
                )
                try:
                    result["database"] = json.loads(
                        runtime.output(runtime.compose + command + ["python", "-c", code])
                    )
                except subprocess.CalledProcessError:
                    result["database"] = {"database_reachable": False}
            print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"event": "maintenance_failed", "code": type(exc).__name__}))
        raise SystemExit(1) from None
