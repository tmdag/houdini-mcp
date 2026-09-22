"""The advertised tool surface must match what the instructions promise.

The 2026-09 audit found HOUDINIMCP_PROFILE=stage deleting 9 of the tools
this server's own instructions tell the model to call, plus a name in
_SOP_EXTRA that was never a tool at all. Neither showed up as an error --
the model simply could not see them.
"""
import importlib.util
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Backticked words in the instructions that are deliberately not tools:
# a binary, a Houdini node type, and a response field.
_NOT_TOOLS = {"husk", "karmarendersettings", "pause_honored"}


def _load_bridge():
    """Import houdini_mcp_server.py under a private name, tools untouched."""
    spec = importlib.util.spec_from_file_location(
        "_bridge_surface", os.path.join(_ROOT, "houdini_mcp_server.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_bridge_surface"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bridge():
    os.environ.setdefault("HOUDINIMCP_NO_HEADLESS", "1")
    return _load_bridge()


@pytest.fixture
def registry(bridge):
    """Snapshot and restore the tool registry around profile mutations."""
    tools = bridge.mcp._tool_manager._tools
    saved = dict(tools)
    lowlevel = bridge._lowlevel_server()
    saved_instructions = lowlevel.instructions
    yield tools
    tools.clear()
    tools.update(saved)
    lowlevel.instructions = saved_instructions


def _instructions(bridge):
    return bridge._lowlevel_server().instructions or ""


def _tools_named_in_instructions(bridge):
    ticked = set(re.findall(r"`([a-z_][a-z_0-9]*)`", _instructions(bridge)))
    return ticked - _NOT_TOOLS


class TestInstructionsMatchTools:
    def test_every_tool_named_in_instructions_exists(self, bridge):
        missing = sorted(
            name for name in _tools_named_in_instructions(bridge)
            if name not in bridge.mcp._tool_manager._tools
        )
        assert not missing, (
            "instructions name tools that do not exist: %s" % missing
        )

    def test_every_tool_named_in_instructions_survives_the_default_profile(
        self, bridge, registry
    ):
        os.environ.pop("HOUDINIMCP_PROFILE", None)
        named = _tools_named_in_instructions(bridge)
        bridge._apply_profile()
        pruned = sorted(n for n in named if n not in registry)
        assert not pruned, (
            "the default profile hides tools the instructions tell the model "
            "to call: %s" % pruned
        )


class TestProfileSets:
    def test_stage_tools_are_all_real(self, bridge):
        bogus = sorted(
            n for n in bridge._STAGE_TOOLS
            if n not in bridge.mcp._tool_manager._tools
        )
        assert not bogus, "_STAGE_TOOLS names non-existent tools: %s" % bogus

    def test_sop_extra_tools_are_all_real(self, bridge):
        bogus = sorted(
            n for n in bridge._SOP_EXTRA
            if n not in bridge.mcp._tool_manager._tools
        )
        assert not bogus, "_SOP_EXTRA names non-existent tools: %s" % bogus

    def test_no_duplicate_tool_names(self, bridge):
        source = open(os.path.join(_ROOT, "houdini_mcp_server.py")).read()
        decorated = re.findall(r"@mcp\.tool\(\)\s*\ndef\s+([a-z_0-9]+)", source)
        assert len(decorated) == len(set(decorated))
        assert len(decorated) == len(bridge.mcp._tool_manager._tools)


class TestApplyProfile:
    def test_stage_keeps_exactly_the_stage_set(self, bridge, registry):
        os.environ["HOUDINIMCP_PROFILE"] = "stage"
        try:
            bridge._apply_profile()
            assert set(registry) == set(bridge._STAGE_TOOLS)
        finally:
            os.environ.pop("HOUDINIMCP_PROFILE", None)

    def test_sop_adds_the_sop_extras(self, bridge, registry):
        os.environ["HOUDINIMCP_PROFILE"] = "sop"
        try:
            bridge._apply_profile()
            assert set(registry) == bridge._STAGE_TOOLS | bridge._SOP_EXTRA
        finally:
            os.environ.pop("HOUDINIMCP_PROFILE", None)

    def test_all_keeps_everything_and_stays_quiet(self, bridge, registry):
        os.environ["HOUDINIMCP_PROFILE"] = "all"
        before = set(registry)
        before_instructions = _instructions(bridge)
        try:
            bridge._apply_profile()
            assert set(registry) == before
            assert _instructions(bridge) == before_instructions
        finally:
            os.environ.pop("HOUDINIMCP_PROFILE", None)

    def test_pruning_tells_the_model_what_it_cannot_see(self, bridge, registry):
        os.environ["HOUDINIMCP_PROFILE"] = "stage"
        try:
            total = len(registry)
            bridge._apply_profile()
            note = _instructions(bridge)
            assert "HOUDINIMCP_PROFILE=all" in note
            assert "%d of %d tools advertised" % (len(registry), total) in note
        finally:
            os.environ.pop("HOUDINIMCP_PROFILE", None)

    def test_missing_registry_exposes_everything_rather_than_crashing(
        self, bridge, monkeypatch
    ):
        """The tool registry is private API; a rename must not 500."""
        monkeypatch.setattr(bridge.mcp, "_tool_manager", object())
        monkeypatch.setattr(bridge.mcp, "remove_tool", None, raising=False)
        bridge._apply_profile()  # must not raise


class TestStageProfileBudget:
    def test_stage_profile_is_meaningfully_smaller(self, bridge):
        total = len(bridge.mcp._tool_manager._tools)
        assert len(bridge._STAGE_TOOLS) < total
        assert len(bridge._STAGE_TOOLS) >= 60, "stage must stay usable"
