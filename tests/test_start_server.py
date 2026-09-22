"""start_server() must not lie about :9876 (issue #6).

Never binds the live H22 port. Uses an ephemeral holder on 127.0.0.1.
"""
import errno
import os
import socket
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

if "hou" not in sys.modules:
    # Full hou mock lives in test_server_commands; reuse it so we don't
    # install a half-mock that breaks the dispatcher tests.
    import tests.test_server_commands  # noqa: F401

if "PySide6" not in sys.modules and "PySide2" not in sys.modules:
    for name in ("PySide2", "PySide2.QtCore", "PySide2.QtWidgets", "PySide2.QtGui"):
        sys.modules.setdefault(name, types.ModuleType(name))

    class _MockQTimer:
        def __init__(self):
            self._callback = None

        @property
        def timeout(self):
            return types.SimpleNamespace(connect=lambda cb: setattr(self, "_callback", cb))

        def start(self, ms):
            pass

        def stop(self):
            pass

    sys.modules["PySide2.QtCore"].QTimer = _MockQTimer

if "numpy" not in sys.modules:
    _np = types.ModuleType("numpy")
    _np.array = lambda *a, **kw: a[0] if a else []
    _np.isinf = lambda x: types.SimpleNamespace(any=lambda: False)
    sys.modules["numpy"] = _np

from houdinimcp import start_server, stop_server
from houdinimcp.server import (
    HoudiniMCPServer, port_is_taken, report_bind_failure, server_is_listening,
)


def _hold_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


def _messages():
    ui = sys.modules["hou"].ui
    return list(getattr(ui, "_messages", []))


@pytest.fixture(autouse=True)
def _isolate_session():
    hou = sys.modules["hou"]
    prev = getattr(hou.session, "houdinimcp_server", None)
    hou.session.houdinimcp_server = None
    if not hasattr(hou, "isUIAvailable"):
        hou.isUIAvailable = lambda: True
    if not hasattr(hou, "severityType"):
        hou.severityType = types.SimpleNamespace(Error="Error", Fatal="Fatal")
    messages = []

    def displayMessage(text, **kwargs):
        messages.append({"text": text, "kwargs": kwargs})
        return 0

    ui = getattr(hou, "ui", None)
    if ui is None:
        hou.ui = types.SimpleNamespace(displayMessage=displayMessage, _messages=messages)
    else:
        hou.ui.displayMessage = displayMessage
        hou.ui._messages = messages
    if not hasattr(hou, "NotAvailable"):
        hou.NotAvailable = type("NotAvailable", (Exception,), {})
    yield
    server = getattr(hou.session, "houdinimcp_server", None)
    if server is not None:
        try:
            server.stop()
        except Exception:
            pass
    hou.session.houdinimcp_server = prev


class TestPortProbe:
    def test_port_is_taken_true(self):
        holder, port = _hold_port()
        try:
            assert port_is_taken("127.0.0.1", port) is True
            assert port_is_taken("localhost", port) is True
        finally:
            holder.close()

    def test_port_is_taken_false(self):
        holder, port = _hold_port()
        holder.close()
        assert port_is_taken("127.0.0.1", port) is False

    def test_listening_false_on_closed_socket(self):
        server = HoudiniMCPServer(host="127.0.0.1", port=0)
        server.running = True
        dead = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dead.close()
        server.socket = dead
        assert server_is_listening(server) is False


class TestStartServer:
    def test_healthy_instance_is_already_running(self):
        holder, port = _hold_port()
        holder.close()
        server = start_server(host="127.0.0.1", port=port)
        assert server is not None
        assert server_is_listening(server)
        again = start_server(host="127.0.0.1", port=port)
        assert again is server
        stop_server()

    def test_dead_instance_is_torn_down_and_rebound(self):
        holder, port = _hold_port()
        holder.close()
        dead = HoudiniMCPServer(host="127.0.0.1", port=port)
        dead.running = True
        z = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        z.close()
        dead.socket = z
        sys.modules["hou"].session.houdinimcp_server = dead
        server = start_server(host="127.0.0.1", port=port)
        assert server is not None
        assert server is not dead
        assert server_is_listening(server)
        stop_server()

    def test_eaddrinuse_is_ui_error_not_already_running(self):
        holder, port = _hold_port()
        try:
            server = start_server(host="127.0.0.1", port=port)
            assert server is None
            assert sys.modules["hou"].session.houdinimcp_server is None
            bind_err = getattr(sys.modules["hou"].session, "houdinimcp_bind_error", "")
            msgs = _messages()
            text = (msgs[0]["text"] if msgs else bind_err) or ""
            assert str(port) in text, text
            assert "already in use" in text.lower(), text
            if msgs:
                sev = msgs[0]["kwargs"].get("severity")
                assert sev != getattr(sys.modules["hou"].severityType, "Fatal", "Fatal")
        finally:
            holder.close()

    def test_start_returns_false_when_port_held(self):
        holder, port = _hold_port()
        try:
            server = HoudiniMCPServer(host="127.0.0.1", port=port)
            assert server.start() is False
            assert server.running is False
            assert not server_is_listening(server)
        finally:
            holder.close()

    def test_report_bind_failure_never_fatal(self):
        report_bind_failure("127.0.0.1", 12345, OSError(errno.EADDRINUSE, "Address already in use"))
        bind_err = getattr(sys.modules["hou"].session, "houdinimcp_bind_error", "")
        assert "already in use" in bind_err.lower()
        msgs = _messages()
        if msgs:
            assert msgs[-1]["kwargs"].get("severity") != "Fatal"
