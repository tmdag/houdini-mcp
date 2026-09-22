"""#20: isolate SOP rewrite, grid/info fields, frame_bbox, capture-guard."""
import os
import struct
import sys
import types
import zlib

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import tests.test_server_commands  # noqa: F401  hou mock

from houdinimcp.handlers.viewport import (
    resolve_isolate_path,
    count_visible_objects,
    evaluate_capture_guard,
    png_looks_grid_only,
    frame_all,
    get_viewport_info,
    set_viewport_display,
    capture_screenshot,
)
from houdinimcp.handlers import viewport as viewport_mod


class _FakeType:
    def __init__(self, category):
        self._category = category

    def category(self):
        return types.SimpleNamespace(name=lambda: self._category)


class _FakeNode:
    def __init__(self, path, category, parent=None):
        self._path = path
        self._category = category
        self._parent = parent

    def path(self):
        return self._path

    def type(self):
        return _FakeType(self._category)

    def parent(self):
        return self._parent


def _lookup_capy(path):
    obj = _FakeNode("/obj/mcp_capy", "Object", _FakeNode("/obj", "Manager"))
    sop = _FakeNode("/obj/mcp_capy/mcp_deform", "Sop", obj)
    table = {
        "/obj/mcp_capy": obj,
        "/obj/mcp_capy/mcp_deform": sop,
    }
    return table.get(path)


class TestResolveIsolate:
    def test_obj_path_unchanged(self):
        out = resolve_isolate_path("/obj/mcp_capy", lookup=_lookup_capy)
        assert out["applied"] == "/obj/mcp_capy"
        assert out["rewritten"] is False

    def test_sop_path_rewritten_to_obj(self):
        out = resolve_isolate_path("/obj/mcp_capy/mcp_deform", lookup=_lookup_capy)
        assert out["applied"] == "/obj/mcp_capy"
        assert out["rewritten"] is True
        assert out["requested"] == "/obj/mcp_capy/mcp_deform"

    def test_missing_exact_path_raises(self):
        with pytest.raises(ValueError, match="OBJ-level"):
            resolve_isolate_path("/obj/geo/sop", lookup=_lookup_capy)

    def test_star_passthrough(self):
        out = resolve_isolate_path("*")
        assert out["applied"] == "*"
        assert out["rewritten"] is False

    def test_glob_passthrough(self):
        out = resolve_isolate_path("/obj/mcp_*")
        assert out["applied"] == "/obj/mcp_*"
        assert out["rewritten"] is False


class TestCountVisible:
    def test_star_is_all(self):
        assert count_visible_objects("*", children=[]) == -1

    def test_exact_miss(self):
        kids = [_FakeNode("/obj/other", "Object")]
        assert count_visible_objects("/obj/mcp_capy", children=kids) == 0

    def test_exact_hit(self):
        kids = [_FakeNode("/obj/mcp_capy", "Object")]
        assert count_visible_objects("/obj/mcp_capy", children=kids) == 1


class TestCaptureGuard:
    def test_empty_isolate_is_reason(self):
        reasons = evaluate_capture_guard(
            "/obj/mcp_capy/mcp_deform", 0, True, 500000, grid_on=True
        )
        assert "empty_isolate" in reasons
        assert "grid_only" in reasons

    def test_ok_when_objects_match(self):
        reasons = evaluate_capture_guard("*", -1, True, 500000, grid_on=False)
        assert reasons == []

    def test_missing_file(self):
        reasons = evaluate_capture_guard("*", -1, False, 0)
        assert "missing_file" in reasons

    def test_looks_grid_only_flag(self):
        reasons = evaluate_capture_guard(
            "/obj/mcp_capy", 1, True, 100, grid_on=True, looks_grid_only=True)
        assert "grid_only" in reasons

    def test_high_contrast_not_grid_only_when_hom_grid_off(self):
        reasons = evaluate_capture_guard(
            "*", -1, True, 100, grid_on=False, looks_grid_only=True)
        assert "grid_only" not in reasons
        assert reasons == []

    def test_default_scene_with_grid_is_not_refused(self):
        reasons = evaluate_capture_guard(
            "*", -1, True, 100, grid_on=True, looks_grid_only=True)
        assert "grid_only" not in reasons
        assert reasons == []


def _write_rgb_png(path, pixels, w, h):
    def chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b""
    for y in range(h):
        raw += b"\x00"
        for x in range(w):
            r, g, b = pixels[y * w + x]
            raw += bytes((r, g, b))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    blob = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(blob)


class TestPngGrid:
    def test_bw_grid_detected(self, tmp_path):
        pixels = []
        for y in range(16):
            for x in range(16):
                pixels.append((0, 0, 0) if (x + y) % 2 == 0 else (255, 255, 255))
        p = str(tmp_path / "grid.png")
        _write_rgb_png(p, pixels, 16, 16)
        assert png_looks_grid_only(p) is True

    def test_gray_clay_not_grid(self, tmp_path):
        pixels = [(140, 140, 140)] * (16 * 16)
        p = str(tmp_path / "clay.png")
        _write_rgb_png(p, pixels, 16, 16)
        assert png_looks_grid_only(p) is False


class TestApplyGridReferencePlane:
    def test_grid_false_calls_reference_plane(self, monkeypatch):
        """Flipbook grid is SceneViewer.referencePlane(), not construction/XZ/-g."""
        calls = []

        class RefPlane:
            def __init__(self):
                self._on = True

            def isVisible(self):
                return self._on

            def setIsVisible(self, on):
                calls.append(("referencePlane", bool(on)))
                self._on = bool(on)

        class CPlane:
            def setIsVisible(self, on):
                calls.append(("constructionPlane", bool(on)))

            def isVisible(self):
                return False

        plane = RefPlane()
        hscript = []
        settings = types.SimpleNamespace(
            visibleObjects=lambda: "*",
            enableGuide=lambda g, on: None,
            setDisplayOrthoGrid=lambda on: None,
            displayOrthoGrid=lambda: False,
            guideEnabled=lambda g: False,
            displaySet=lambda t: types.SimpleNamespace(
                setShadedMode=lambda *a: None,
                useLighting=lambda *a: None,
                useGhostedLook=lambda *a: None,
            ),
        )
        viewport = types.SimpleNamespace(
            name=lambda: "persp1",
            settings=lambda: settings,
        )
        viewer = types.SimpleNamespace(
            name=lambda: "pane1",
            pwd=lambda: types.SimpleNamespace(path=lambda: "/obj"),
            curViewport=lambda: viewport,
            referencePlane=lambda: plane,
            constructionPlane=lambda: CPlane(),
        )
        monkeypatch.setattr(viewport_mod, "_scene_viewer", lambda viewer=None: viewer)
        monkeypatch.setattr(
            viewport_mod, "_hscript_viewport_path",
            lambda sv, vp: "Build.pane1.world.persp1",
        )
        monkeypatch.setattr(
            viewport_mod.hou, "hscript",
            lambda cmd: (hscript.append(cmd), ("", ""))[1],
            raising=False,
        )
        result = set_viewport_display(grid=False, viewer=viewer)
        assert ("referencePlane", False) in calls
        assert plane.isVisible() is False
        assert result["grid"]["on"] is False
        assert result["grid"]["reference_plane"] is False
        joined = " ".join(hscript)
        assert "-x" in joined and "off" in joined
        assert not any(c.startswith("viewdisplay -g ") or "viewdisplay -g " in c for c in hscript)

    def test_info_grid_on_follows_reference_plane(self, monkeypatch):
        plane = types.SimpleNamespace(isVisible=lambda: True)
        settings = types.SimpleNamespace(
            visibleObjects=lambda: "*",
            displayOrthoGrid=lambda: False,
            guideEnabled=lambda g: False,
            displaySet=lambda t: types.SimpleNamespace(shadedMode=lambda: "Smooth"),
        )
        viewport = types.SimpleNamespace(
            name=lambda: "persp1",
            settings=lambda: settings,
            camera=lambda: None,
            cameraPath=lambda: None,
            type=lambda: "Perspective",
        )
        pane = types.SimpleNamespace(
            desktop=lambda: types.SimpleNamespace(name=lambda: "Build"),
        )
        viewer = types.SimpleNamespace(
            name=lambda: "pane1",
            pwd=lambda: types.SimpleNamespace(path=lambda: "/obj"),
            curViewport=lambda: viewport,
            pane=lambda: pane,
            hydraRenderers=lambda: (),
            currentHydraRenderer=lambda: None,
            isRendererPaused=lambda: None,
            referencePlane=lambda: plane,
        )
        monkeypatch.setattr(viewport_mod, "_scene_viewer", lambda viewer=None: viewer)
        monkeypatch.setattr(
            viewport_mod, "_hscript_viewport_path",
            lambda sv, vp: "Build.pane1.world.persp1",
        )
        info = get_viewport_info(viewer=viewer)
        assert info["grid"]["reference_plane"] is True
        assert info["grid_on"] is True


class TestSetViewportDisplayIsolate:
    def test_sop_isolate_rewritten_not_applied_verbatim(self, monkeypatch):
        applied = {}

        class Settings:
            def __init__(self):
                self._vis = "*"

            def setVisibleObjects(self, v):
                applied["v"] = v
                self._vis = v

            def visibleObjects(self):
                return self._vis

            def enableGuide(self, g, on):
                pass

            def displaySet(self, t):
                return types.SimpleNamespace(
                    setShadedMode=lambda *a: None,
                    useLighting=lambda *a: None,
                    useGhostedLook=lambda *a: None,
                )

            def displayOrthoGrid(self):
                return False

            def guideEnabled(self, g):
                return False

            def setDisplayOrthoGrid(self, on):
                pass

        settings = Settings()
        viewport = types.SimpleNamespace(
            name=lambda: "persp1",
            settings=lambda: settings,
        )
        viewer = types.SimpleNamespace(
            name=lambda: "pane1",
            pwd=lambda: types.SimpleNamespace(path=lambda: "/obj"),
            curViewport=lambda: viewport,
        )
        monkeypatch.setattr(viewport_mod, "_scene_viewer", lambda viewer=None: viewer)
        monkeypatch.setattr(viewport_mod, "_hscript_viewport_path", lambda sv, vp: "Build.pane1.world.persp1")
        monkeypatch.setattr(viewport_mod.hou, "node", _lookup_capy, raising=False)
        monkeypatch.setattr(viewport_mod, "resolve_isolate_path",
                            lambda iso, lookup=None: resolve_isolate_path(iso, lookup=_lookup_capy))

        result = set_viewport_display(isolate="/obj/mcp_capy/mcp_deform", viewer=viewer)
        assert applied["v"] == "/obj/mcp_capy"
        assert applied["v"] != "/obj/mcp_capy/mcp_deform"
        assert result["isolate"]["rewritten"] is True
        assert result["visibleObjects"] == "/obj/mcp_capy"


class TestFrameAllRefuse:
    def test_empty_isolate_refused(self, monkeypatch):
        settings = types.SimpleNamespace(
            visibleObjects=lambda: "/obj/nobody",
        )
        viewport = types.SimpleNamespace(
            name=lambda: "persp1",
            settings=lambda: settings,
            frameAll=lambda: (_ for _ in ()).throw(AssertionError("must not frame_all")),
        )
        viewer = types.SimpleNamespace(
            name=lambda: "pane1",
            curViewport=lambda: viewport,
        )
        monkeypatch.setattr(viewport_mod, "_scene_viewer", lambda viewer=None: viewer)
        monkeypatch.setattr(viewport_mod, "count_visible_objects", lambda p, children=None: 0)
        with pytest.raises(ValueError, match="frame_all refused"):
            frame_all(viewer=viewer)


class TestGetViewportInfoFields:
    def test_info_includes_visible_and_grid(self, monkeypatch):
        settings = types.SimpleNamespace(
            visibleObjects=lambda: "/obj/mcp_capy",
            displayOrthoGrid=lambda: False,
            guideEnabled=lambda g: False,
            displaySet=lambda t: types.SimpleNamespace(shadedMode=lambda: "Smooth"),
        )
        viewport = types.SimpleNamespace(
            name=lambda: "persp1",
            settings=lambda: settings,
            camera=lambda: None,
            cameraPath=lambda: None,
            type=lambda: "Perspective",
        )
        pane = types.SimpleNamespace(desktop=lambda: types.SimpleNamespace(name=lambda: "Solaris"))
        viewer = types.SimpleNamespace(
            name=lambda: "pane1",
            pwd=lambda: types.SimpleNamespace(path=lambda: "/obj"),
            curViewport=lambda: viewport,
            pane=lambda: pane,
            hydraRenderers=lambda: (),
            currentHydraRenderer=lambda: None,
            isRendererPaused=lambda: None,
        )
        monkeypatch.setattr(viewport_mod, "_scene_viewer", lambda viewer=None: viewer)
        monkeypatch.setattr(viewport_mod, "_hscript_viewport_path", lambda sv, vp: "Solaris.pane1.world.persp1")
        info = get_viewport_info(viewer=viewer)
        assert "visibleObjects" in info
        assert info["visibleObjects"] == "/obj/mcp_capy"
        assert "grid" in info
        assert "on" in info["grid"]
        assert info["pwd"] == "/obj"
        assert "guides" in info


class TestCaptureRefusesEmpty:
    def test_empty_isolate_raises(self, monkeypatch, tmp_path):
        out = str(tmp_path / "empty.png")
        pixels = [(255, 255, 255)] * (8 * 8)
        _write_rgb_png(out, pixels, 8, 8)

        class Settings:
            def stash(self):
                return self

            def frameRange(self, *a):
                pass

            def output(self, p):
                pass

            def outputToMPlay(self, *a):
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

        vp_settings = types.SimpleNamespace(
            visibleObjects=lambda: "/obj/nobody",
            displayOrthoGrid=lambda: True,
            guideEnabled=lambda g: True,
        )
        viewport = types.SimpleNamespace(
            name=lambda: "persp1",
            cameraPath=lambda: None,
            settings=lambda: vp_settings,
        )

        class Viewer:
            def name(self):
                return "pane1"

            def pwd(self):
                return types.SimpleNamespace(path=lambda: "/obj")

            def curViewport(self):
                return viewport

            def flipbookSettings(self):
                return Settings()

            def isRendererPaused(self):
                return False

            def setRendererPaused(self, v):
                pass

            def hydraRenderers(self):
                return ()

            def currentHydraRenderer(self):
                return None

            def flipbook(self, **kw):
                pass

        monkeypatch.setattr(viewport_mod, "_scene_viewer", lambda viewer=None: Viewer())
        monkeypatch.setattr(viewport_mod, "_hscript_viewport_path",
                            lambda sv, vp: "Build.pane1.world.persp1")
        monkeypatch.setattr(viewport_mod, "count_visible_objects", lambda p, children=None: 0)
        monkeypatch.setattr(viewport_mod.hou, "frame", lambda: 1, raising=False)
        with pytest.raises(RuntimeError, match="capture refused"):
            capture_screenshot(output_path=out, source="viewport")
