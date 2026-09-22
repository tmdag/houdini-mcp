"""Tests for viewport handlers."""
import sys
import os
import types

import pytest

if "hou" not in sys.modules:
    pytest.skip("hou mock not loaded", allow_module_level=True)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from houdinimcp.handlers import viewport as viewport_mod
from houdinimcp.handlers.viewport import (
    list_panes, set_current_network, _resolve_hydra_name,
    _restore_renderer_paused, set_hydra_renderer, capture_screenshot,
    FLIPBOOK_FRAME_TIME_LIMIT,
)


class TestViewportHandlers:
    def setup_method(self):
        self._orig_ui = sys.modules["hou"].ui
        self._orig_node = sys.modules["hou"].node

    def teardown_method(self):
        sys.modules["hou"].ui = self._orig_ui
        sys.modules["hou"].node = self._orig_node

    def test_list_panes(self):
        tab1 = types.SimpleNamespace(
            name=lambda: "viewer1",
            type=lambda: "SceneViewer",
            isCurrentTab=lambda: True,
        )
        sys.modules["hou"].ui = types.SimpleNamespace(
            paneTabs=lambda: [tab1],
            paneTabOfType=lambda t: None,
        )
        result = list_panes()
        assert result["count"] == 1
        assert result["panes"][0]["name"] == "viewer1"

    def test_list_panes_empty(self):
        sys.modules["hou"].ui = types.SimpleNamespace(
            paneTabs=lambda: [],
            paneTabOfType=lambda t: None,
        )
        result = list_panes()
        assert result["count"] == 0

    def test_set_current_network(self):
        node = types.SimpleNamespace(path=lambda: "/obj/geo1")
        editor = types.SimpleNamespace(setCurrentNode=lambda n: None)
        sys.modules["hou"].ui = types.SimpleNamespace(
            paneTabOfType=lambda t: editor,
            paneTabs=lambda: [],
        )
        sys.modules["hou"].paneTabType = types.SimpleNamespace(
            NetworkEditor=1, SceneViewer=0,
        )
        sys.modules["hou"].node = lambda p: node if p == "/obj/geo1" else None
        result = set_current_network("/obj/geo1")
        assert result["path"] == "/obj/geo1"

    def test_set_current_network_not_found(self):
        editor = types.SimpleNamespace(setCurrentNode=lambda n: None)
        sys.modules["hou"].ui = types.SimpleNamespace(
            paneTabOfType=lambda t: editor,
            paneTabs=lambda: [],
        )
        sys.modules["hou"].paneTabType = types.SimpleNamespace(
            NetworkEditor=1, SceneViewer=0,
        )
        sys.modules["hou"].node = lambda p: None
        with pytest.raises(ValueError, match="Node not found"):
            set_current_network("/obj/missing")

    def test_resolve_hydra_aliases(self):
        viewer = types.SimpleNamespace(
            hydraRenderers=lambda: ("Houdini VK", "Karma CPU", "Karma XPU", "Storm"),
        )
        assert _resolve_hydra_name(viewer, "xpu") == "Karma XPU"
        assert _resolve_hydra_name(viewer, "karma") == "Karma XPU"
        assert _resolve_hydra_name(viewer, "Karma XPU") == "Karma XPU"
        assert _resolve_hydra_name(viewer, "cpu") == "Karma CPU"
        assert _resolve_hydra_name(viewer, "vk") == "Houdini VK"
        assert _resolve_hydra_name(viewer, "storm") == "Storm"

    def test_resolve_hydra_unknown(self):
        viewer = types.SimpleNamespace(
            hydraRenderers=lambda: ("Houdini VK", "Karma XPU"),
        )
        with pytest.raises(ValueError, match="Unknown Hydra renderer"):
            _resolve_hydra_name(viewer, "arnold")

    def test_resolve_hydra_empty(self):
        viewer = types.SimpleNamespace(hydraRenderers=lambda: ())
        with pytest.raises(RuntimeError, match="No Hydra renderers"):
            _resolve_hydra_name(viewer, "xpu")

    def test_restore_renderer_paused_retries(self):
        states = [True, True, False]

        class Viewer:
            def __init__(self):
                self.writes = []

            def setRendererPaused(self, v):
                self.writes.append(bool(v))

            def isRendererPaused(self):
                return states[min(len(self.writes) - 1, len(states) - 1)]

        v = Viewer()
        assert _restore_renderer_paused(v, False, defer=False) is False
        assert v.writes == [False, False, False]

    def test_restore_unknown_unpauses(self):
        v = types.SimpleNamespace(
            setRendererPaused=lambda paused: None,
            isRendererPaused=lambda: False,
        )
        assert _restore_renderer_paused(v, None, defer=False) is False

    def test_set_hydra_renderer_does_not_restart(self, monkeypatch):
        calls = []

        class Viewer:
            def name(self):
                return "pane1"

            def pwd(self):
                return types.SimpleNamespace(path=lambda: "/stage")

            def hydraRenderers(self):
                return ("Houdini VK", "Karma XPU")

            def currentHydraRenderer(self):
                return "Karma XPU"

            def isRendererPaused(self):
                return False

            def setHydraRenderer(self, name):
                calls.append(("set", name))

            def restartRenderer(self):
                calls.append("restart")

        monkeypatch.setattr(viewport_mod, "_scene_viewer", lambda viewer=None: Viewer())
        result = set_hydra_renderer("xpu", wait=True)
        assert result["resolved"] == "Karma XPU"
        assert result["wait_ignored"] is True
        assert calls == [("set", "Karma XPU")]

    def test_capture_snapshot_limit_and_restore_pause(self, monkeypatch, tmp_path):
        paused = {"value": False}
        settings_state = {}
        out = str(tmp_path / "mcp_xpu.png")

        class Settings:
            def stash(self):
                return self

            def frameRange(self, *a):
                pass

            def output(self, *a):
                pass

            def outputToMPlay(self, *a):
                pass

            def leaveFrameAtEnd(self, *a):
                pass

            def initializeSimulations(self, *a):
                pass

            def useMotionBlur(self, *a):
                pass

            def renderAllViewports(self, *a):
                pass

            def appendFramesToCurrent(self, *a):
                pass

            def useResolution(self, *a):
                pass

            def resolution(self, *a):
                pass

            def setUseFrameTimeLimit(self, v):
                settings_state["time_on"] = v

            def setFrameTimeLimit(self, t):
                settings_state["time"] = t

            def setUseFrameProgressLimit(self, v):
                settings_state["progress_on"] = v

        class Viewport:
            def name(self):
                return "persp1"

            def cameraPath(self):
                return "/world/cam"

            def settings(self):
                return types.SimpleNamespace(
                    visibleObjects=lambda: "*",
                    displayOrthoGrid=lambda: False,
                    guideEnabled=lambda g: False,
                )

        class Viewer:
            def name(self):
                return "pane1"

            def pwd(self):
                return types.SimpleNamespace(path=lambda: "/stage")

            def curViewport(self):
                return Viewport()

            def flipbookSettings(self):
                return Settings()

            def isRendererPaused(self):
                return paused["value"]

            def setRendererPaused(self, v):
                paused["value"] = bool(v)

            def hydraRenderers(self):
                return ("Karma XPU",)

            def currentHydraRenderer(self):
                return "Karma XPU"

            def flipbook(self, viewport=None, settings=None, open_dialog=False):
                paused["value"] = True
                with open(out, "wb") as f:
                    f.write(b"\x89PNG\r\n")

        monkeypatch.setattr(viewport_mod, "_scene_viewer", lambda viewer=None: Viewer())
        monkeypatch.setattr(viewport_mod, "_hscript_viewport_path",
                            lambda sv, vp: "Solaris.pane1.solaris.persp1")
        monkeypatch.setattr(viewport_mod.hou, "frame", lambda: 1001, raising=False)

        result = capture_screenshot(output_path=out, source="viewport")
        assert settings_state["time_on"] is True
        assert settings_state["time"] == FLIPBOOK_FRAME_TIME_LIMIT
        assert settings_state["progress_on"] is False
        assert result["snapshot"] is True
        assert result["paused_before"] is False
        assert result["paused"] is False
        assert result["paused_restored_to"] is False
        assert paused["value"] is False
        assert result["exists"] is True
        assert result["hydra_renderer"] == "Karma XPU"

    def test_capture_restores_pause_on_flipbook_error(self, monkeypatch, tmp_path):
        paused = {"value": False}

        class Settings:
            def stash(self):
                return self

            def frameRange(self, *a):
                pass

            def output(self, *a):
                pass

            def outputToMPlay(self, *a):
                pass

            def leaveFrameAtEnd(self, *a):
                pass

            def initializeSimulations(self, *a):
                pass

            def useMotionBlur(self, *a):
                pass

            def renderAllViewports(self, *a):
                pass

            def appendFramesToCurrent(self, *a):
                pass

            def useResolution(self, *a):
                pass

            def resolution(self, *a):
                pass

            def setUseFrameTimeLimit(self, *a):
                pass

            def setFrameTimeLimit(self, *a):
                pass

            def setUseFrameProgressLimit(self, *a):
                pass

        class Viewer:
            def name(self):
                return "pane1"

            def pwd(self):
                return types.SimpleNamespace(path=lambda: "/stage")

            def curViewport(self):
                return types.SimpleNamespace(name=lambda: "persp1", cameraPath=lambda: None)

            def flipbookSettings(self):
                return Settings()

            def isRendererPaused(self):
                return paused["value"]

            def setRendererPaused(self, v):
                paused["value"] = bool(v)

            def hydraRenderers(self):
                return ("Karma XPU",)

            def currentHydraRenderer(self):
                return "Karma XPU"

            def flipbook(self, **kw):
                paused["value"] = True
                raise RuntimeError("flipbook died")

        monkeypatch.setattr(viewport_mod, "_scene_viewer", lambda viewer=None: Viewer())
        monkeypatch.setattr(viewport_mod.hou, "frame", lambda: 1, raising=False)
        with pytest.raises(RuntimeError, match="flipbook died"):
            capture_screenshot(output_path=str(tmp_path / "x.png"))
        assert paused["value"] is False
