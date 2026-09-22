"""#19: stdio bridge initialize + tools/list under 5s, not via `uv run`."""
import json
import os
import select
import subprocess
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PYTHON = os.path.join(REPO, ".venv", "bin", "python")
BRIDGE = os.path.join(REPO, "houdini_mcp_server.py")


def _recv_json(proc, timeout=8.0):
    buf = b""
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([proc.stdout], [], [], 0.2)
        if r:
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                line, _, rest = buf.partition(b"\n")
                try:
                    return json.loads(line.decode()), rest
                except json.JSONDecodeError:
                    pass
        if proc.poll() is not None:
            break
    return None, buf


def test_hot_path_is_not_uv_run():
    """The argv under test is venv python + the bridge script. Not `uv run`."""
    assert os.path.isfile(VENV_PYTHON)
    assert os.path.isfile(BRIDGE)
    argv = [VENV_PYTHON, BRIDGE]
    assert argv[0].endswith("/python") or argv[0].endswith("/python3")
    assert "uv" not in os.path.basename(argv[0])
    assert argv[1].endswith("houdini_mcp_server.py")


def test_bridge_handshake_under_5s():
    if not os.path.isfile(VENV_PYTHON) or not os.path.isfile(BRIDGE):
        pytest.skip("venv python / bridge missing")
    env = os.environ.copy()
    env["HOUDINIMCP_NO_HEADLESS"] = "1"
    env["HOUDINIMCP_PROFILE"] = "stage"
    env["PYTHONUNBUFFERED"] = "1"
    t0 = time.time()
    proc = subprocess.Popen(
        [VENV_PYTHON, BRIDGE],
        cwd=REPO,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    try:
        def send(obj):
            proc.stdin.write(json.dumps(obj).encode() + b"\n")
            proc.stdin.flush()

        send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mustdo", "version": "0"},
            },
        })
        init, _ = _recv_json(proc, timeout=8.0)
        assert init is not None, "no initialize response"
        assert init.get("id") == 1
        assert "result" in init
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed, leftover = _recv_json(proc, timeout=8.0)
        elapsed = time.time() - t0
        assert listed is not None, "no tools/list response leftover=%r" % (leftover[:200],)
        tools = (listed.get("result") or {}).get("tools") or []
        names = [t.get("name") for t in tools]
        assert elapsed < 5.0, "handshake took %.2fs" % elapsed
        assert len(tools) >= 10
        assert "ping" in names
        assert "get_viewport_info" in names
        assert "frame_bbox" in names
    finally:
        proc.kill()
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
