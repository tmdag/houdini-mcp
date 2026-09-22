"""Per-command connect/disconnect must not spam the Houdini console."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import tests.test_server_commands  # noqa: F401  — installs hou mock

from houdinimcp.handlers.plugin import (
    hush_server_prints,
    is_session_noise,
    log_level,
    set_log_level,
    dispatch_command,
    is_quiet_command_error,
    _patch_instance,
)


class TestSessionNoise:
    def test_connect_disconnect_is_noise(self):
        assert is_session_noise("Connected to client: ('127.0.0.1', 36696)")
        assert is_session_noise("Client disconnected")
        assert is_session_noise("Executing handler for execute_code")
        assert is_session_noise("Handler execution complete for capture_screenshot")
        assert is_session_noise(
            "Houdini MCP: additional client ('127.0.0.1', 9) (1 already connected; "
            "not stealing the first session)"
        )

    def test_start_and_errors_are_not_noise(self):
        assert not is_session_noise("HoudiniMCP server started on localhost:9876")
        assert not is_session_noise("Error executing command: boom")
        assert not is_session_noise("Failed to start server: Address already in use")


class TestLogLevel:
    def test_default_quiet(self, monkeypatch):
        monkeypatch.delenv("HOUDINIMCP_LOG", raising=False)
        import hou
        hou.session.houdinimcp_log = None
        assert log_level() == "quiet"

    def test_set_log_level_roundtrip(self):
        assert set_log_level("verbose")["log"] == "verbose"
        assert log_level() == "verbose"
        assert set_log_level("quiet")["log"] == "quiet"
        assert log_level() == "quiet"

    def test_aliases(self):
        assert set_log_level("debug")["log"] == "verbose"
        assert set_log_level("off")["log"] == "quiet"

    def test_bad_level_raises(self):
        with pytest.raises(ValueError):
            set_log_level("loud")


class TestHushAndExecute:
    def test_execute_command_quiet_by_default(self, capsys):
        from tests.test_server_commands import TestCommandDispatcher
        helper = TestCommandDispatcher()
        helper.setup_method()
        set_log_level("quiet")
        hush_server_prints()
        helper.server.execute_command({"type": "ping"})
        out, err = capsys.readouterr()
        combined = out + err
        assert "Executing handler" not in combined
        assert "Handler execution complete" not in combined
        assert "Connected to client" not in combined

    def test_verbose_prints_handler(self, capsys):
        from tests.test_server_commands import TestCommandDispatcher
        helper = TestCommandDispatcher()
        helper.setup_method()
        try:
            set_log_level("verbose")
            helper.server.execute_command({"type": "ping"})
            out, err = capsys.readouterr()
            combined = out + err
            assert "Executing handler for ping" in combined
        finally:
            set_log_level("quiet")


class TestQuietCaptureRefused:
    def test_is_quiet(self):
        assert is_quiet_command_error(RuntimeError("capture refused: grid_only"))
        assert not is_quiet_command_error(RuntimeError("isolate matches no node"))

    def test_dispatch_capture_refused_no_traceback(self, capsys):
        class _Inst:
            MUTATING_COMMANDS = set()

            def _ensure_reload_hook(self):
                pass

            def _execute_command_internal(self, command):
                raise RuntimeError("capture refused: empty_isolate")

        out = dispatch_command(_Inst(), {"type": "capture_screenshot"})
        printed = capsys.readouterr()
        combined = printed.out + printed.err
        assert out["status"] == "error"
        assert out["message"] == "capture refused: empty_isolate"
        assert out["traceback"] == ""
        assert "Traceback" not in combined
        assert "Error executing command" not in combined

    def test_dispatch_other_errors_still_print(self, capsys):
        class _Inst:
            MUTATING_COMMANDS = set()

            def _ensure_reload_hook(self):
                pass

            def _execute_command_internal(self, command):
                raise RuntimeError("boom")

        out = dispatch_command(_Inst(), {"type": "ping"})
        printed = capsys.readouterr()
        combined = printed.out + printed.err
        assert out["status"] == "error"
        assert out["traceback"]
        assert "Error executing command: boom" in combined

    def test_patch_instance_rebinds_execute_command(self):
        class _Noisy:
            MUTATING_COMMANDS = set()

            def _ensure_reload_hook(self):
                pass

            def _execute_command_internal(self, command):
                raise RuntimeError("capture refused: grid_only")

            def execute_command(self, command):
                raise RuntimeError("old noisy path")

        inst = _Noisy()
        _patch_instance(inst)
        out = inst.execute_command({"type": "capture_screenshot"})
        assert out["status"] == "error"
        assert out["message"].startswith("capture refused")
        assert out["traceback"] == ""
