"""Tests for the MCP bridge's HoudiniConnection class.

We extract HoudiniConnection via AST to avoid triggering the full
houdini_mcp_server.py initialization (FastMCP, env vars, etc.).
"""
import ast
import json
import os
import socket
import sys
import threading
import time
import types

import pytest


def _load_houdini_connection_class(export_ns=None):
    """Extract the HoudiniConnection dataclass from houdini_mcp_server.py
    without executing the full module.
    """
    bridge_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "houdini_mcp_server.py",
    )

    with open(bridge_path) as f:
        source = f.read()

    tree = ast.parse(source)

    # Collect the imports and class def we need
    nodes_to_compile = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Include standard library imports
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in (
                    "json", "socket", "logging", "asyncio", "dataclasses"
                ):
                    nodes_to_compile.append(node)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in (
                        "json", "socket", "logging", "asyncio"
                    ):
                        nodes_to_compile.append(node)
                        break
        elif isinstance(node, ast.ClassDef) and node.name == "HoudiniConnection":
            nodes_to_compile.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in (
            "_timeout_for", "_env_number", "_format_error",
        ):
            nodes_to_compile.append(node)
        elif isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") in (
                "DEFAULT_COMMAND_TIMEOUT", "LONG_COMMAND_TIMEOUT", "_LONG_COMMANDS",
            )
            for t in node.targets
        ):
            nodes_to_compile.append(node)

    import logging
    import time as _time
    from typing import Dict, Any, List
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from houdinimcp.framing import MAGIC, pack_message, feed_messages
    ns = {
        "__builtins__": __builtins__,
        "Dict": Dict,
        "Any": Any,
        "List": List,
        "logger": logging.getLogger("test_bridge"),
        "MAGIC": MAGIC,
        "pack_message": pack_message,
        "feed_messages": feed_messages,
        "json": json,
        "os": os,
        "_time": _time,
    }
    module = ast.Module(body=nodes_to_compile, type_ignores=[])
    code = compile(module, bridge_path, "exec")
    exec(code, ns)

    if export_ns is not None:
        export_ns.update(ns)
    return ns["HoudiniConnection"]


_NS = {}
HoudiniConnection = _load_houdini_connection_class(_NS)


def _make_connection(port):
    return HoudiniConnection(host="localhost", port=port)


class TestHoudiniConnection:
    def test_ping(self, mock_houdini_server):
        mock_houdini_server.set_response("ping", {
            "status": "success",
            "result": {"alive": True},
        })
        conn = _make_connection(mock_houdini_server.port)
        result = conn.send_command("ping")
        assert result["status"] == "success"
        assert result["result"]["alive"] is True
        conn.disconnect()

    def test_unknown_command(self, mock_houdini_server):
        """Mock server returns a generic success for unknown commands."""
        conn = _make_connection(mock_houdini_server.port)
        result = conn.send_command("nonexistent_command")
        assert result["status"] == "success"
        assert result["result"]["echo"] == "nonexistent_command"
        conn.disconnect()

    def test_connection_error_returns_error_dict(self):
        """Connecting to a port with nothing listening returns an error dict."""
        conn = _make_connection(19999)
        result = conn.send_command("ping")
        assert result["status"] == "error"
        assert "origin" in result
        conn.disconnect()

    def test_disconnect_resets_socket(self, mock_houdini_server):
        conn = _make_connection(mock_houdini_server.port)
        conn.connect()
        assert conn.sock is not None
        conn.disconnect()
        assert conn.sock is None

    def test_get_status_disconnected(self):
        conn = _make_connection(19999)
        status = conn.get_status()
        assert status["connected"] is False
        assert status["port"] == 19999

    def test_reuses_socket_across_commands(self, mock_houdini_server):
        mock_houdini_server.set_response("ping", {
            "status": "success",
            "result": {"alive": True},
        })
        conn = _make_connection(mock_houdini_server.port)
        first = conn.send_command("ping")
        fd = conn.sock.fileno()
        second = conn.send_command("ping")
        assert first["status"] == "success"
        assert second["status"] == "success"
        assert conn.sock.fileno() == fd
        conn.disconnect()


@pytest.fixture
def silent_server():
    """A listener that accepts a connection and then says nothing, ever."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("localhost", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    accepted = []

    def _accept():
        try:
            client, _ = sock.accept()
            accepted.append(client)
        except OSError:
            pass

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    yield port
    sock.close()
    for client in accepted:
        try:
            client.close()
        except OSError:
            pass


class TestCommandTimeouts:
    """A flat 30s deadline reported every render/cook as a Houdini timeout."""

    def test_long_commands_get_a_long_budget(self):
        timeout_for = _NS["_timeout_for"]
        long_budget = _NS["LONG_COMMAND_TIMEOUT"]
        for cmd in ("render_flipbook", "start_render", "pdg_cook", "batch",
                    "execute_code", "geo_export", "setup_pyro_sim",
                    "capture_screenshot", "load_scene"):
            assert timeout_for(cmd) == long_budget, cmd

    def test_cheap_commands_keep_the_default(self):
        timeout_for = _NS["_timeout_for"]
        default = _NS["DEFAULT_COMMAND_TIMEOUT"]
        for cmd in ("ping", "get_node_info", "list_children", "get_parameter"):
            assert timeout_for(cmd) == default, cmd

    def test_long_budget_exceeds_the_default(self):
        assert _NS["LONG_COMMAND_TIMEOUT"] > _NS["DEFAULT_COMMAND_TIMEOUT"]
        assert _NS["DEFAULT_COMMAND_TIMEOUT"] >= 30

    def test_every_long_command_is_a_real_command(self):
        """Guard against typos rotting the timeout table."""
        bridge = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "houdini_mcp_server.py",
        )
        source = open(bridge).read()
        for cmd in _NS["_LONG_COMMANDS"]:
            assert '"%s"' % cmd in source, "%s is in _LONG_COMMANDS but never sent" % cmd

    def test_explicit_timeout_overrides_the_table(self, silent_server):
        """A 0.2s budget must fire instead of waiting out the 900s table value."""
        conn = _make_connection(silent_server)
        started = time.monotonic()
        result = conn.send_command("pdg_cook", timeout=0.2)
        elapsed = time.monotonic() - started
        assert result["status"] == "error"
        assert "Timeout" in result["message"]
        assert elapsed < 10, "explicit timeout was ignored (%.1fs)" % elapsed
        conn.disconnect()

    def test_timeout_message_names_the_command_and_the_escape_hatch(self, silent_server):
        conn = _make_connection(silent_server)
        result = conn.send_command("render_flipbook", timeout=0.2)
        assert "render_flipbook" in result["message"]
        assert "HOUDINIMCP_LONG_TIMEOUT" in result["message"]
        conn.disconnect()
