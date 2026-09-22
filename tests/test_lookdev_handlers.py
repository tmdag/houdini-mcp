"""#9–#11 lookdev helpers: dome, preview surface, camera, karma samples, USD frame."""
import math
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import tests.test_server_commands  # noqa: F401  hou mock

from houdinimcp.handlers.lop import (
    _require_mcp_lop, usd_prim_bbox, lookdev_dome, lookdev_preview_surface,
    lookdev_display_color, lookdev_camera, set_karma_samples, _lookat_angles,
)
from houdinimcp.handlers.viewport import set_karma_quality, set_renderer_paused


class _Parm:
    def __init__(self, value=None):
        self.value = value

    def set(self, val):
        self.value = val

    def eval(self):
        return self.value


class _Attr:
    def __init__(self, value=None):
        self._value = value

    def Get(self):
        return self._value

    def Set(self, value):
        self._value = value


class _Prim:
    def __init__(self, path, type_name="Mesh", extent=None):
        self._path = path
        self._type = type_name
        self._extent = extent or [[-1, 0, -1], [1, 2, 1]]
        self._attrs = {"extent": _Attr(self._extent)}

    def GetPath(self):
        return self._path

    def GetTypeName(self):
        return self._type

    def GetAttribute(self, name):
        return self._attrs.get(name)

    def CreateAttribute(self, name, type_name=None):
        attr = _Attr(None)
        self._attrs[name] = attr
        return attr

    def GetChildren(self):
        return []

    def GetAttributes(self):
        return list(self._attrs.values())

    def IsActive(self):
        return True

    def HasPayload(self):
        return False


class _Stage:
    def __init__(self, prims):
        self._prims = prims

    def GetPrimAtPath(self, path):
        return self._prims.get(path)

    def Traverse(self):
        return self._prims.values()

    def GetPseudoRoot(self):
        return types.SimpleNamespace(GetChildren=lambda: list(self._prims.values()))

    def HasDefaultPrim(self):
        return False

    def GetLayerStack(self):
        return []

    def GetStartTimeCode(self):
        return 1

    def GetEndTimeCode(self):
        return 1


class _Node:
    def __init__(self, name, path, node_type, graph):
        self._name = name
        self._path = path
        self._type = node_type
        self._graph = graph
        self._parms = {}
        self.inputs = {}
        self._stage = None
        self._parent = None

    def name(self):
        return self._name

    def path(self):
        return self._path

    def type(self):
        return types.SimpleNamespace(name=lambda: self._type)

    def parent(self):
        return self._parent

    def node(self, name):
        return self._graph.get(self._path + "/" + name)

    def createNode(self, node_type, node_name=None):
        n = node_name or node_type.replace(":", "_").replace(".", "_")
        child = _Node(n, self._path + "/" + n, node_type, self._graph)
        child._parent = self
        child._stage = self._stage
        self._graph[child.path()] = child
        return child

    def parm(self, name):
        if name not in self._parms:
            self._parms[name] = _Parm()
        return self._parms[name]

    def setInput(self, idx, node, output_idx=0):
        self.inputs[idx] = node.path() if node else None

    def stage(self):
        return self._stage


class _FakeViewer:
    def __init__(self):
        self._paused = False
        self._name = "solaris"

    def name(self):
        return self._name

    def hydraRenderers(self):
        return ("Houdini GL", "Karma CPU", "Karma XPU")

    def currentHydraRenderer(self):
        return "Karma XPU"

    def isRendererPaused(self):
        return self._paused

    def setRendererPaused(self, paused):
        self._paused = bool(paused)


class TestMcpIsolation:
    def test_stage_plus_mcp_name_ok(self):
        _require_mcp_lop("/stage", "mcp_dome")

    def test_rejects_show_name(self):
        with pytest.raises(ValueError, match="mcp_"):
            _require_mcp_lop("/stage", "dome")


class TestUsdBBox:
    def setup_method(self):
        self._orig = sys.modules["hou"].node
        prim = _Prim("/world/hero")
        stage = _Stage({"/world/hero": prim})
        node = _Node("mcp_hero", "/stage/mcp_hero", "sopcreate", {})
        node._stage = stage
        sys.modules["hou"].node = lambda p, n=node: n if p == "/stage/mcp_hero" else None

    def teardown_method(self):
        sys.modules["hou"].node = self._orig

    def test_extent_bbox(self):
        box = usd_prim_bbox("/stage/mcp_hero", "/world/hero")
        assert box["min"] == [-1.0, 0.0, -1.0]
        assert box["center"][1] == 1.0


class TestLookdevBuild:
    def setup_method(self):
        hou = sys.modules["hou"]
        self._orig = hou.node
        self.graph = {}
        stage_node = _Node("stage", "/stage", "manager", self.graph)
        self.graph["/stage"] = stage_node
        prim = _Prim("/world/hero")
        self.stage = _Stage({"/world/hero": prim, "/world/dome": _Prim("/world/dome", "DomeLight")})
        sop = stage_node.createNode("sopcreate", "mcp_hero")
        sop._stage = self.stage
        hou.node = lambda p, g=self.graph: g.get(p)

    def teardown_method(self):
        sys.modules["hou"].node = self._orig

    def test_dome(self):
        out = lookdev_dome("/stage", name="mcp_dome", input_path="/stage/mcp_hero",
                           exposure=1.5, color=[1, 0.9, 0.8])
        assert out["path"] == "/stage/mcp_dome"
        assert "/stage/mcp_dome" in self.graph
        assert self.graph["/stage/mcp_dome"].inputs[0] == "/stage/mcp_hero"

    def test_preview_surface(self):
        out = lookdev_preview_surface(
            "/stage", name="mcp_preview", input_path="/stage/mcp_hero",
            prim_pattern="/world/hero", color=[0.2, 0.4, 0.8],
        )
        assert out["library"] == "/stage/mcp_preview_lib"
        assert out["assign"] == "/stage/mcp_preview_assign"
        assert self.graph[out["assign"]].inputs[0] == out["library"]
        assert out["material"].startswith("/materials/")
        assert out["material"] != "/preview"

    def test_pause_noop_setter_is_not_honored(self):
        import houdinimcp.handlers.viewport as vp
        class _Noop:
            def name(self):
                return "solaris"
            def hydraRenderers(self):
                return ("Karma XPU",)
            def currentHydraRenderer(self):
                return "Karma XPU"
            def isRendererPaused(self):
                return False
            def setRendererPaused(self, paused):
                pass
        orig = vp._scene_viewer
        vp._scene_viewer = lambda viewer=None: _Noop()
        try:
            out = set_renderer_paused(True)
            assert out["pause_honored"] is False
            assert out["paused"] is False
        finally:
            vp._scene_viewer = orig

    def test_display_color(self):
        out = lookdev_display_color("/stage/mcp_hero", "/world/hero", [1, 0, 0])
        assert out["color"] == [1.0, 0.0, 0.0]
        assert out["method"]

    def test_camera_lookat(self):
        out = lookdev_camera(
            "/stage", name="mcp_cam", look_at="/world/hero",
            input_path="/stage/mcp_hero",
        )
        assert out["usd_prim"].startswith("/")
        assert out["eye"][1] > out["bbox"]["center"][1]
        rx, ry, rz = _lookat_angles(out["eye"], out["bbox"]["center"])
        assert math.isfinite(rx) and math.isfinite(ry)

    def test_karma_samples_creates_lop(self):
        out = set_karma_samples(
            "/stage/mcp_hero", samples=16, preview=True, parent_path="/stage",
        )
        assert out["created"] is True
        assert out["viewport_samples"] == "unavailable"
        assert "samplesperpixel" in out["parms"]
        assert out["parms"]["preview"] is True


class TestKarmaQualityViewport:
    def setup_method(self, monkeypatch=None):
        import houdinimcp.handlers.viewport as vp
        self._orig = vp._scene_viewer
        self.viewer = _FakeViewer()
        vp._scene_viewer = lambda viewer=None, v=self.viewer: v

    def teardown_method(self):
        import houdinimcp.handlers.viewport as vp
        vp._scene_viewer = self._orig

    def test_pause_honored(self):
        out = set_renderer_paused(True)
        assert out["paused"] is True
        assert out["pause_honored"] is True
        out = set_renderer_paused(False)
        assert out["paused"] is False
        assert out["pause_honored"] is True

    def test_viewport_samples_unavailable(self):
        out = set_karma_quality(samples=64, preview=True)
        assert out["viewport_quality"]["samples"] == "unavailable"
        assert out["viewport_quality"]["preview"] == "unavailable"
        assert out["lop"] is None
