"""SIGKILL at persisted MCP success while the Agent checkpoint commit is row-lock blocked."""

import json
import subprocess

from check_agent import execute
from model_faults import wait
from operations import DOCKER, Runtime


def cached_state(runtime, identity):
    return json.loads(
        execute(
            runtime,
            """import json,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute('SET TRANSACTION READ ONLY')
 cp,revision=db.execute('SELECT checkpoint,revision FROM agent_runs WHERE id=%s',
                       (RUN,)).fetchone()
 calls=db.execute('SELECT call_id,tool_id,input_hash,state,result FROM mcp_calls '
                  'WHERE run_id=%s ORDER BY call_id',(RUN,)).fetchall()
 inv=db.execute('SELECT count(*) FROM agent_tool_invocations WHERE run_id=%s',(RUN,)).fetchone()[0]
 print(json.dumps({'checkpoint':cp,'revision':revision,'calls':calls,'invocations':inv}))
""".replace("RUN", repr(identity)),
        )
    )


def interrupt_success(runtime, directory, deployed, identity, exp, revoke):
    worker = deployed["agent-drill"]["Id"]
    control = directory / "control"
    wait(lambda: (control / (exp + ".mcp-started")).exists(), bool)
    before = cached_state(runtime, identity)
    assert before["checkpoint"]["stage"] == "tools"
    assert before["checkpoint"]["status"] == "RUNNING"
    assert before["checkpoint"]["history"] == [] and before["invocations"] == 0
    assert len(before["calls"]) == 1 and before["calls"][0][3:] == ["INFLIGHT", None]
    code = """import json,sys,select,psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 db.execute("SET LOCAL lock_timeout='5s'")
 db.execute("SET LOCAL idle_in_transaction_session_timeout='60s'")
 db.execute('SELECT id FROM agent_runs WHERE id=%s FOR UPDATE',(RUN,)).fetchone()
 print(json.dumps({'pid':db.info.backend_pid}),flush=True)
 if not select.select([sys.stdin],[],[],55)[0]: raise TimeoutError('Row lock release deadline')
 assert sys.stdin.read(1)=='r'
""".replace("RUN", repr(identity))
    locker = subprocess.Popen(
        runtime.compose + ["exec", "-T", "api", "python", "-c", code],
        env=runtime.env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # Bounded readiness; never leave a row lock held after test failure.
        import select

        assert select.select([locker.stdout], [], [], 10)[0], "Row lock did not become ready"
        ready = json.loads(locker.stdout.readline())
        (control / (exp + ".mcp-release")).touch()
        boundary = wait(
            lambda: cached_state(runtime, identity),
            lambda r: r["calls"][0][3:] == ["SUCCEEDED", {"value": 3}],
        )
        assert boundary["checkpoint"] == before["checkpoint"]
        assert boundary["revision"] == before["revision"] and boundary["invocations"] == 0
        blocked = wait(
            lambda: int(
                execute(
                    runtime,
                    """import psycopg
from alap.adapters.postgres.settings import database_url
with psycopg.connect(database_url()) as db:
 print(db.execute('SELECT count(*) FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid))',
                  (PID,)).fetchone()[0])
""".replace("PID", str(ready["pid"])),
                )
            ),
            lambda n: n > 0,
        )
        (control / "agent-start").unlink()
        runtime.output([DOCKER, "kill", "--signal", "KILL", worker])
        stopped = json.loads(runtime.output([DOCKER, "inspect", worker]))[0]["State"]
        assert not stopped["Running"] and stopped["ExitCode"] == 137 and not stopped["OOMKilled"]
        assert cached_state(runtime, identity) == boundary
    finally:
        if locker.poll() is None:
            try:
                locker.stdin.write("r")
                locker.stdin.flush()
            except BrokenPipeError:
                pass
        locker.communicate(timeout=10)
        assert locker.returncode == 0, "Row-lock fixture failed"
    assert cached_state(runtime, identity) == boundary
    if revoke is not None:
        revoke()
    drill = Runtime(runtime.directory, override=directory / "compose.yaml")
    # Restart the loopback service in the new worker network namespace before Agent execution.
    drill.run(drill.compose + ["rm", "-f", "-s", "offline-mcp"])
    runtime.output([DOCKER, "start", worker])
    drill.run(
        drill.compose
        + [
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "--no-build",
            "--pull",
            "never",
            "offline-mcp",
        ]
    )
    wait(
        lambda: drill.output(drill.compose + ["logs", "offline-mcp"]),
        lambda logs: "offline-mcp-ready" in logs,
    )
    (control / "agent-start").touch()
    return {
        "boundary": boundary,
        "blocked_sessions": blocked,
        "killed_exit_code": 137,
        "checkpoint_unchanged_after_kill": True,
        "grant_revoked_before_restart": revoke is not None,
    }
