"""Live smoke against a running houdini-bin (issue #5).

Opt-in: HOUDINIMCP_LIVE=1. Does not launch Houdini. CI stays skipped.

Fails if hydra commands 404 or current != requested after set_hydra_renderer.
Talks TCP :9876 (HOUDINIMCP_PORT). Viewport only — no scene save, no mcp_* nodes.
"""
import json
import os
import socket
import time

import pytest

LIVE = os.environ.get("HOUDINIMCP_LIVE", "").strip().lower() in ("1", "true", "yes")
HOST = os.environ.get("HOUDINIMCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("HOUDINIMCP_PORT", "9876"))
CAM = os.environ.get("HOUDINIMCP_LIVE_CAM", "/world/cam")
OUT = os.environ.get("HOUDINIMCP_LIVE_PNG", "/tmp/mcp_live_smoke.png")

pytestmark = pytest.mark.live

if not LIVE:
    pytest.skip("HOUDINIMCP_LIVE=1 required (no houdini-bin in CI)", allow_module_level=True)


def _send(cmd_type, params=None, timeout=15.0):
    payload = json.dumps({"type": cmd_type, "params": params or {}}).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    t0 = time.time()
    try:
        sock.connect((HOST, PORT))
        sock.sendall(payload)
        buf = b""
        while True:
            if time.time() - t0 > timeout:
                raise TimeoutError("%s timed out after %.1fs" % (cmd_type, timeout))
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                return json.loads(buf.decode("utf-8"))
            except json.JSONDecodeError:
                continue
        raise ConnectionError("%s: connection closed, got %r" % (cmd_type, buf[:200]))
    finally:
        sock.close()


def cmd(cmd_type, params=None, timeout=15.0):
    response = _send(cmd_type, params, timeout=timeout)
    status = response.get("status")
    message = response.get("message") or ""
    if status == "error" and "Unknown command type" in message:
        pytest.fail("hydra command 404: %s — %s" % (cmd_type, message))
    if status != "success":
        pytest.fail("%s failed: %s" % (cmd_type, message or response))
    return response.get("result") or {}


def _poll_current(expected, attempts=8, delay=0.15):
    last = None
    for _ in range(attempts):
        snap = cmd("list_hydra_renderers")
        last = snap.get("current")
        if last == expected:
            return snap
        time.sleep(delay)
    pytest.fail(
        "current %r != requested %r after set_hydra_renderer (list_hydra_renderers)"
        % (last, expected)
    )


@pytest.fixture(scope="module")
def origin():
    ping = cmd("ping")
    assert ping.get("alive") is True
    before = cmd("list_hydra_renderers")
    yield before
    try:
        current = before.get("current")
        if current:
            cmd("set_hydra_renderer", {"renderer": current})
        if before.get("paused") is not None:
            cmd("set_renderer_paused", {"paused": bool(before.get("paused"))})
    except Exception:
        pass


class TestLiveHydraSmoke:
    def test_list_hydra_renderers_not_404(self, origin):
        available = origin.get("available") or []
        assert "Houdini VK" in available, available
        assert "Karma XPU" in available, available
        assert origin.get("pwd", "").startswith("/stage"), origin

    def test_viewport_is_solaris_not_world(self):
        info = cmd("get_viewport_info")
        hscript = info.get("hscript_path") or ""
        assert ".solaris." in hscript, hscript
        assert ".world." not in hscript, hscript
        assert (info.get("pwd") or "").startswith("/stage"), info

    def test_usd_look_through(self):
        result = cmd("set_viewport_camera", {"camera_path": CAM})
        look = result.get("look_through") or result.get("camera_path")
        assert look == CAM, result
        info = cmd("get_viewport_info")
        assert info.get("camera_path") == CAM, info

    def test_switch_vk_then_xpu(self, origin):
        vk = cmd("set_hydra_renderer", {"renderer": "vk"})
        assert vk.get("resolved") == "Houdini VK", vk
        assert vk.get("current") == "Houdini VK", vk
        _poll_current("Houdini VK")

        xpu = cmd("set_hydra_renderer", {"renderer": "xpu"})
        assert xpu.get("resolved") == "Karma XPU", xpu
        assert xpu.get("current") == "Karma XPU", xpu
        _poll_current("Karma XPU")

    def test_flipbook_is_xpu(self):
        cmd("set_hydra_renderer", {"renderer": "xpu"})
        _poll_current("Karma XPU")
        if os.path.isfile(OUT):
            os.remove(OUT)
        cap = cmd(
            "capture_screenshot",
            {"output_path": OUT, "source": "viewport"},
            timeout=20.0,
        )
        assert cap.get("hydra_renderer") == "Karma XPU", cap
        assert cap.get("exists") is True, cap
        assert int(cap.get("bytes") or 0) > 1000, cap
        assert os.path.isfile(OUT) and os.path.getsize(OUT) > 1000
        hscript = cap.get("hscript_path") or ""
        assert ".solaris." in hscript, cap
        # Flipbook re-pauses; QTimer 0/250ms restores. Poll, don't sleep in Houdini.
        last = None
        for _ in range(8):
            last = cmd("list_hydra_renderers")
            if last.get("paused") is False:
                break
            time.sleep(0.15)
        else:
            pytest.fail("capture left XPU paused: %s" % last)
