"""The bridge must import and run on mcp 1.x and 2.x.

mcp 2.0 renamed FastMCP to MCPServer and moved the module, so
`from mcp.server.fastmcp import FastMCP` raises ModuleNotFoundError. The
dependency range allows both, which means an unguarded import made a fresh
clone resolve to 2.x and fail before the first tool call.

Differences this shim covers:
    class            FastMCP              -> MCPServer
    module           mcp.server.fastmcp   -> mcp.server.mcpserver
    lowlevel attr    _mcp_server          -> _lowlevel_server
    tool removal     _tool_manager._tools -> remove_tool() (public)
    ImageContent     .mimeType            -> .mime_type
"""
import importlib.util
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def bridge():
    os.environ.setdefault("HOUDINIMCP_NO_HEADLESS", "1")
    spec = importlib.util.spec_from_file_location(
        "_bridge_compat", os.path.join(_ROOT, "houdini_mcp_server.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_bridge_compat"] = module
    spec.loader.exec_module(module)
    return module


class TestImportShim:
    def test_reports_the_major_version_it_bound_to(self, bridge):
        import importlib.metadata as metadata
        installed = int(metadata.version("mcp").split(".")[0])
        assert bridge.MCP_MAJOR == installed

    def test_server_class_matches_the_installed_major(self, bridge):
        name = bridge.MCPServerClass.__name__
        assert name == ("MCPServer" if bridge.MCP_MAJOR >= 2 else "FastMCP")

    def test_context_and_image_are_bound(self, bridge):
        assert bridge.Context is not None
        assert bridge.Image is not None

    def test_source_never_imports_fastmcp_unguarded(self):
        """A bare `from mcp.server.fastmcp import ...` breaks on 2.x."""
        source = open(os.path.join(_ROOT, "houdini_mcp_server.py")).read()
        for number, line in enumerate(source.splitlines(), 1):
            if "mcp.server.fastmcp" in line and not line.startswith("    "):
                pytest.fail(
                    "line %d imports mcp.server.fastmcp outside a try/except: %s"
                    % (number, line.strip())
                )

    def test_dependency_range_has_no_upper_bound(self):
        pyproject = open(os.path.join(_ROOT, "pyproject.toml")).read()
        pin = re.search(r'"mcp\[cli\]([^"]*)"', pyproject)
        assert pin, "mcp dependency missing from pyproject.toml"
        assert "<2" not in pin.group(1), (
            "the shim supports 2.x; drop the upper bound or drop the shim"
        )


class TestVersionNeutralAccessors:
    def test_lowlevel_server_is_reachable(self, bridge):
        server = bridge._lowlevel_server()
        assert server is not None
        assert isinstance(server.instructions, str)

    def test_tool_names_returns_the_registry(self, bridge):
        names = bridge._tool_names()
        assert isinstance(names, list)
        assert "ping" in names

    def test_tool_names_is_none_when_the_registry_moves(self, bridge, monkeypatch):
        monkeypatch.setattr(bridge.mcp, "_tool_manager", object())
        assert bridge._tool_names() is None

    def test_remove_tool_actually_removes(self, bridge):
        names = bridge._tool_names()
        victim = "get_connection_status"
        assert victim in names
        saved = dict(bridge.mcp._tool_manager._tools)
        try:
            assert bridge._remove_tool(victim) is True
            assert victim not in bridge._tool_names()
        finally:
            bridge.mcp._tool_manager._tools.clear()
            bridge.mcp._tool_manager._tools.update(saved)
        assert victim in bridge._tool_names()

    def test_remove_tool_reports_failure_when_nothing_works(self, bridge, monkeypatch):
        monkeypatch.setattr(bridge.mcp, "_tool_manager", object())
        monkeypatch.setattr(bridge.mcp, "remove_tool", None, raising=False)
        assert bridge._remove_tool("ping") is False


class TestVenvFallback:
    def test_repo_venv_is_a_fallback_not_an_override(self):
        """Prepending .venv unconditionally ignored the launching environment."""
        source = open(os.path.join(_ROOT, "houdini_mcp_server.py")).read()
        head = source[:source.index("HOUDINI_PORT")]
        assert "except ImportError:" in head
        insert = head.index("sys.path.insert(0, venv_site_packages)")
        probe = head.index("import mcp as _mcp_probe")
        assert probe < insert, "the import probe must gate the sys.path insert"
