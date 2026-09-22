"""Viewport and pane helpers.

H21/H22 notes (verified on tmlenovo):
- GeometryViewport has no saveAsImage — use SceneViewer.flipbook.
- GeometryViewportSettings.setDisplaySet does not exist — use
  displaySet(hou.displaySetType.SceneObject).setShadedMode(...)
  and/or `viewdispset -s shade scene <desk.pane.group.viewport>`.
- Never call hou.ui.desktops() / curDesktop(); H22 + studio 123.py
  has crashed houdini-bin (exit 5) that way. pane().desktop() is fine.
- LOP Scene Viewer hscript group is `solaris`, not `world`.
- USD look-through: viewport.setCamera("/world/cam") as a string.
  LOP nodes are not OBJ cameras.
- setHydraRenderer is enough to switch XPU. restartRenderer() + sleep
  + viewwrite on the MCP QTimer stalls the session.
- capture_screenshot is a snapshot: FlipbookSettings frame time limit,
  not an XPU converge. Always restore renderer pause state afterwards.
"""
import fnmatch
import os
import struct
import tempfile
import zlib

import hou

# Progressive Hydra (Karma XPU) will otherwise wait for 100% / ~20s in
# SceneViewer.flipbook() and stall the MCP QTimer. Grab current pixels.
FLIPBOOK_FRAME_TIME_LIMIT = 0.15

_GLOB_CHARS = set("*?[]")
_OBJECT_CATEGORIES = ("Object", "Obj")


def _node_category_name(node):
    try:
        return node.type().category().name()
    except Exception:
        return ""


def _node_path(node):
    try:
        return node.path()
    except Exception:
        return ""


def _node_parent(node):
    try:
        return node.parent()
    except Exception:
        return None


def resolve_isolate_path(isolate, lookup=None):
    """visibleObjects is OBJ-level. SOP paths silently hid the whole scene.

    Returns {requested, applied, rewritten}. Raises ValueError if the path
    exists as a non-OBJ with no Object parent, or is a missing exact path.
    Globs (`/obj/mcp_*`) pass through.
    """
    if isolate is None:
        return None
    requested = str(isolate).strip()
    if requested in ("", "*"):
        return {"requested": isolate, "applied": "*", "rewritten": False}
    if any(c in requested for c in _GLOB_CHARS):
        return {"requested": requested, "applied": requested, "rewritten": False}

    lookup = lookup or hou.node
    node = lookup(requested)
    if node is None:
        raise ValueError(
            "isolate %r matches no node. visibleObjects is OBJ-level — "
            "pass /obj/geo, not a SOP path." % isolate
        )
    if _node_category_name(node) in _OBJECT_CATEGORIES:
        return {"requested": requested, "applied": _node_path(node) or requested,
                "rewritten": False}
    parent = _node_parent(node)
    while parent is not None:
        if _node_category_name(parent) in _OBJECT_CATEGORIES:
            ppath = _node_path(parent)
            return {"requested": requested, "applied": ppath, "rewritten": True}
        parent = _node_parent(parent)
    raise ValueError(
        "isolate %r is not an OBJ node and has no Object parent. "
        "visibleObjects cannot use SOP/LOP paths." % isolate
    )


def count_visible_objects(pattern, children=None):
    """How many /obj nodes match a visibleObjects pattern. -1 means all (`*`)."""
    if not pattern or pattern == "*":
        return -1
    if children is None:
        obj = hou.node("/obj")
        children = list(obj.children()) if obj else []
    paths = []
    for child in children:
        try:
            paths.append(child.path())
        except Exception:
            paths.append(str(child))
    if any(c in pattern for c in _GLOB_CHARS):
        n = 0
        for p in paths:
            name = p.rsplit("/", 1)[-1]
            if fnmatch.fnmatch(p, pattern) or fnmatch.fnmatch(name, pattern):
                n += 1
        return n
    if pattern in paths:
        return 1
    lookup = getattr(hou, "node", None)
    if lookup and lookup(pattern) is not None:
        return 1
    return 0


def evaluate_capture_guard(visible_objects, matched_objects, file_exists,
                           file_bytes, grid_on=False, looks_grid_only=False):
    """Reasons a flipbook is not a beauty. Empty list = ok."""
    reasons = []
    vis = visible_objects or ""
    isolated = vis not in ("", "*")
    if isolated and matched_objects == 0:
        reasons.append("empty_isolate")
    if not file_exists or int(file_bytes or 0) <= 0:
        reasons.append("missing_file")
    # Default hip (vis=* or "") with the reference plane on is a real snapshot.
    # grid_only is the isolate-emptied-the-scene lie from #20.
    if isolated and grid_on and (looks_grid_only or matched_objects == 0):
        reasons.append("grid_only")
    return reasons


def read_grid_state(settings, viewer=None):
    """Perspective reference plane the flipbook draws, plus ortho/XZ leftovers.

    H22: the infinite persp grid is SceneViewer.referencePlane()
    (hou.ReferencePlane), not constructionPlane and not viewdisplay -g.
    """
    xz = False
    try:
        g = getattr(hou.viewportGuide, "XZPlane", None)
        if g is not None:
            xz = bool(settings.guideEnabled(g))
    except Exception:
        pass
    ortho = False
    try:
        ortho = bool(settings.displayOrthoGrid())
    except Exception:
        pass
    settings_ref = None
    fn = getattr(settings, "showsReferenceGrid", None)
    if fn:
        try:
            settings_ref = bool(fn())
        except Exception:
            settings_ref = None
    plane_vis = None
    if viewer is not None:
        try:
            plane_vis = bool(viewer.referencePlane().isVisible())
        except Exception:
            plane_vis = None
    on = bool(xz or ortho or settings_ref or plane_vis)
    return {
        "xz_plane": xz,
        "ortho": ortho,
        "reference": settings_ref,
        "reference_plane": plane_vis,
        "on": on,
    }


def apply_grid(settings, enabled, viewer=None, vp_id=None):
    """On/off for the plane the flipbook shows, not just ortho/XZ guides."""
    on = bool(enabled)
    for gname in ("XZPlane", "XYPlane", "YZPlane"):
        g = getattr(hou.viewportGuide, gname, None)
        if g is None:
            continue
        try:
            settings.enableGuide(g, on)
        except Exception:
            pass
    try:
        settings.setDisplayOrthoGrid(on)
    except Exception:
        pass
    for meth in ("showReferenceGrid", "showOrthoGrid"):
        fn = getattr(settings, meth, None)
        if fn:
            try:
                fn(on)
            except Exception:
                pass
    if viewer is not None:
        try:
            viewer.referencePlane().setIsVisible(on)
        except Exception:
            pass
        try:
            viewer.constructionPlane().setIsVisible(on)
        except Exception:
            pass
    if vp_id:
        flag = "on" if on else "off"
        # -x/-y/-z are the reference-plane axes. -g is node guide geometry.
        for cmd in (
            "viewdisplay -x %s -y %s -z %s %s" % (flag, flag, flag, vp_id),
            "vieworthogrid -d %s %s" % (flag, vp_id),
        ):
            try:
                hou.hscript(cmd)
            except Exception:
                pass
    return read_grid_state(settings, viewer=viewer)


def suppress_current_sop_ghost(settings):
    """Rest-skin Current SOP overlay on top of the display SOP (the 'ghost')."""
    g = getattr(hou.viewportGuide, "CurrentGeometry", None)
    if g is not None:
        try:
            settings.enableGuide(g, False)
        except Exception:
            pass
    ds_type = getattr(hou, "displaySetType", None)
    if ds_type is None:
        return {"current_geometry": False}
    for tname in ("CurrentModel", "DisplayModel"):
        try:
            ds = settings.displaySet(getattr(ds_type, tname))
            ds.useGhostedLook(False)
        except Exception:
            pass
    return {"current_geometry": False}


def png_looks_grid_only(path, max_mid_frac=0.08):
    """True if the PNG is high-contrast B/W (reference grid / empty sky)."""
    pixels = _png_rgb_samples(path, limit=4000)
    if len(pixels) < 16:
        return False
    mid = 0
    for r, g, b in pixels:
        luma = (int(r) + int(g) + int(b)) / 3.0
        if 40 < luma < 220:
            mid += 1
    return (mid / float(len(pixels))) < max_mid_frac


def _png_rgb_samples(path, limit=4000):
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        w, h = im.size
        step = max(1, int((w * h) ** 0.5 // max(1, int(limit ** 0.5))))
        out = []
        for y in range(0, h, step):
            for x in range(0, w, step):
                out.append(im.getpixel((x, y))[:3])
                if len(out) >= limit:
                    return out
        return out
    except Exception:
        pass
    return _png_rgb_samples_stdlib(path, limit)


def _png_rgb_samples_stdlib(path, limit=4000):
    """RGB samples from an 8-bit RGB/RGBA PNG. Best-effort; empty on failure."""
    try:
        raw = open(path, "rb").read()
    except Exception:
        return []
    sig = b"\x89PNG\r\n\x1a\n"
    if not raw.startswith(sig):
        return []
    pos = 8
    width = height = None
    color_type = bit_depth = None
    idat = []
    while pos + 8 <= len(raw):
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        ctype = raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", data[:10])
        elif ctype == b"IDAT":
            idat.append(data)
        elif ctype == b"IEND":
            break
    if not width or not height or bit_depth != 8 or color_type not in (2, 6):
        return []
    try:
        data = zlib.decompress(b"".join(idat))
    except Exception:
        return []
    bpp = 3 if color_type == 2 else 4
    stride = 1 + width * bpp
    if len(data) < stride * height:
        return []
    prev = bytearray(width * bpp)
    recon = []
    for y in range(height):
        row = data[y * stride:(y + 1) * stride]
        filt = row[0]
        cur = bytearray(row[1:])
        for i, val in enumerate(cur):
            a = cur[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if filt == 1:
                val = (val + a) & 255
            elif filt == 2:
                val = (val + b) & 255
            elif filt == 3:
                val = (val + ((a + b) // 2)) & 255
            elif filt == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                val = (val + pr) & 255
            cur[i] = val
        prev = cur
        recon.append(cur)
    step = max(1, (width * height) // limit)
    out = []
    i = 0
    for row in recon:
        for x in range(width):
            if i % step == 0:
                o = x * bpp
                out.append((row[o], row[o + 1], row[o + 2]))
                if len(out) >= limit:
                    return out
            i += 1
    return out


def _require_ui():
    if not hou.isUIAvailable():
        raise RuntimeError("Houdini UI is not available (headless)")


def _scene_viewer(name=None):
    """Prefer a Scene Viewer whose pwd is /stage (LOP / Hydra)."""
    _require_ui()
    stage_viewer = None
    named = None
    first = None
    for tab in hou.ui.paneTabs():
        if tab.type() != hou.paneTabType.SceneViewer:
            continue
        if first is None:
            first = tab
        if name and tab.name() == name:
            named = tab
        try:
            pwd = tab.pwd()
            if pwd and (pwd.path() == "/stage" or pwd.path().startswith("/stage/")):
                if stage_viewer is None:
                    stage_viewer = tab
        except Exception:
            pass
    viewer = named or stage_viewer or first or hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        raise RuntimeError("No Scene Viewer pane (open the Stage or Build desktop)")
    return viewer


def _desktop_name(viewer):
    try:
        pane = viewer.pane()
        desktop = pane.desktop() if pane else None
        if desktop is not None:
            return desktop.name()
    except Exception:
        pass
    return None


def _viewport_group(viewer):
    """Hscript viewer group: solaris for LOP, world for OBJ."""
    try:
        pwd = viewer.pwd()
        if pwd and (pwd.path() == "/stage" or pwd.path().startswith("/stage/")):
            return "solaris"
    except Exception:
        pass
    return "world"


def _hscript_viewport_path(viewer, viewport):
    """desk.pane.group.viewport id. Must not call hou.ui.desktops()."""
    desk = _desktop_name(viewer) or "Build"
    group = _viewport_group(viewer)
    prefix = "%s.%s." % (desk, viewer.name())
    try:
        out, _err = hou.hscript("viewls -n")
        names = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
        candidates = [n for n in names if n.startswith(prefix)]
        preferred = prefix + group
        for n in candidates:
            if n == preferred or n.endswith("." + group):
                return "%s.%s" % (n, viewport.name())
        if candidates:
            return "%s.%s" % (candidates[0], viewport.name())
    except Exception:
        pass
    return "%s.%s.%s.%s" % (desk, viewer.name(), group, viewport.name())


def _resolve_hydra_name(viewer, name):
    available = list(viewer.hydraRenderers() or ())
    if not available:
        raise RuntimeError("No Hydra renderers (is this a LOP Scene Viewer?)")
    if name in available:
        return name
    key = name.lower().replace(" ", "").replace("_", "")
    aliases = {
        "xpu": "Karma XPU",
        "karmaxpu": "Karma XPU",
        "karma": "Karma XPU",
        "cpu": "Karma CPU",
        "karmacpu": "Karma CPU",
        "vk": "Houdini VK",
        "vulkan": "Houdini VK",
        "gl": "Houdini VK",
        "houdinigl": "Houdini VK",
        "houdinivk": "Houdini VK",
        "houdini": "Houdini VK",
        "storm": "Storm",
        "hydra": "Houdini VK",
    }
    hinted = aliases.get(key)
    if hinted in available:
        return hinted
    for a in available:
        if key in a.lower().replace(" ", ""):
            return a
    raise ValueError("Unknown Hydra renderer %r. Available: %s" % (name, available))


def _hydra_snapshot(viewer):
    snap = {
        "available": [],
        "current": None,
        "paused": None,
    }
    try:
        snap["available"] = list(viewer.hydraRenderers() or ())
        snap["current"] = viewer.currentHydraRenderer()
        snap["paused"] = viewer.isRendererPaused()
    except Exception as e:
        snap["error"] = str(e)
    return snap


def _qt_core():
    try:
        from PySide6 import QtCore
        return QtCore
    except Exception:
        try:
            from PySide2 import QtCore
            return QtCore
        except Exception:
            return None


def _qt_single_shot(ms, fn):
    """Best-effort QTimer.singleShot. Missing Qt/mock → no-op."""
    qtcore = _qt_core()
    timer = getattr(qtcore, "QTimer", None) if qtcore is not None else None
    shot = getattr(timer, "singleShot", None) if timer is not None else None
    if shot is None:
        return False
    try:
        shot(int(ms), fn)
        return True
    except Exception:
        return False


def _restore_renderer_paused(viewer, was_paused, defer=True):
    """Put the Hydra delegate back. Capture must not leave XPU paused.

    was_paused None (couldn't read) → resume. Artist-paused stays paused.
    Flipbook often re-pauses after return; defer a couple of follow-up sets.
    """
    desired = False if was_paused is None else bool(was_paused)

    def _apply():
        last = None
        for _ in range(3):
            try:
                viewer.setRendererPaused(desired)
                last = viewer.isRendererPaused()
                if last == desired:
                    return last
            except Exception:
                pass
        return last if last is not None else desired

    last = _apply()
    if defer:
        # Flipbook re-pauses after we return. Do not processEvents here —
        # a nested loop eats the singleShot. Let the MCP QTimer fire these.
        _qt_single_shot(0, _apply)
        _qt_single_shot(250, _apply)
    return last


def list_panes():
    """List pane tabs on the current UI. Avoids desktops() enumeration."""
    _require_ui()
    panes = []
    for tab in hou.ui.paneTabs():
        rec = {
            "name": tab.name(),
            "type": str(tab.type()),
            "is_current": tab.isCurrentTab(),
        }
        try:
            rec["pwd"] = tab.pwd().path() if tab.pwd() else None
        except Exception:
            rec["pwd"] = None
        if tab.type() == hou.paneTabType.SceneViewer:
            rec.update(_hydra_snapshot(tab))
            try:
                rec["viewport"] = tab.curViewport().name()
                rec["camera_path"] = tab.curViewport().cameraPath()
            except Exception:
                pass
        panes.append(rec)
    return {"count": len(panes), "panes": panes}


def get_viewport_info(viewer=None):
    """Current scene-viewer viewport info, including Hydra delegate."""
    sv = _scene_viewer(viewer)
    viewport = sv.curViewport()
    settings = viewport.settings()
    cam = viewport.camera()
    camera_path = None
    try:
        camera_path = viewport.cameraPath() or None
    except Exception:
        camera_path = None
    shaded = None
    try:
        ds = settings.displaySet(hou.displaySetType.SceneObject)
        shaded = str(ds.shadedMode())
    except Exception as e:
        shaded = "unavailable: %s" % e
    pwd = None
    try:
        pwd = sv.pwd().path() if sv.pwd() else None
    except Exception:
        pass
    vis = ""
    try:
        vis = settings.visibleObjects() or ""
    except Exception:
        vis = ""
    grid_state = read_grid_state(settings, viewer=sv)
    current_geo = None
    try:
        g = getattr(hou.viewportGuide, "CurrentGeometry", None)
        if g is not None:
            current_geo = bool(settings.guideEnabled(g))
    except Exception:
        current_geo = None
    node_guides = None
    try:
        g = getattr(hou.viewportGuide, "NodeGuides", None)
        if g is not None:
            node_guides = bool(settings.guideEnabled(g))
    except Exception:
        node_guides = None
    info = {
        "viewer": sv.name(),
        "pwd": pwd,
        "desktop": _desktop_name(sv),
        "name": viewport.name(),
        "type": str(viewport.type()),
        "camera": cam.path() if cam else None,
        "camera_path": camera_path,
        "shaded_mode": shaded,
        "hscript_path": _hscript_viewport_path(sv, viewport),
        "visibleObjects": vis,
        "grid": grid_state,
        "grid_on": grid_state.get("on"),
        "guides": {
            "current_geometry": current_geo,
            "node_guides": node_guides,
        },
    }
    info.update(_hydra_snapshot(sv))
    # aliases used by older clients
    info["hydra_renderer"] = info.get("current")
    info["hydra_renderers"] = info.get("available")
    return info


def set_viewport_camera(camera_path, camera_prim=None, viewer=None):
    """Look through an OBJ camera node or a USD camera prim.

    LOP Camera nodes are not OBJ cameras. For Solaris pass the USD path
    (e.g. /world/cam) or camera_path=<lop> + camera_prim=<usd>.
    """
    sv = _scene_viewer(viewer)
    viewport = sv.curViewport()
    node = hou.node(camera_path)
    used = None
    errors = []

    if camera_prim and node is not None:
        try:
            viewport.setCamera(node, camera_prim)
            used = "node+prim"
        except Exception as e:
            errors.append("node+prim: %s" % e)

    if used is None and node is not None:
        try:
            viewport.setCamera(node)
            used = "node"
        except Exception as e:
            errors.append("node: %s" % e)

    if used is None:
        usd = camera_prim or camera_path
        try:
            viewport.setCamera(usd)
            used = "usd"
        except Exception as e:
            errors.append("usd: %s" % e)
            raise ValueError(
                "Could not look through %r. %s" % (camera_path, "; ".join(errors))
            )

    look = None
    try:
        look = viewport.cameraPath() or None
    except Exception:
        pass
    cam = viewport.camera()
    return {
        "camera": camera_path,
        "camera_prim": camera_prim,
        "method": used,
        "look_through": look,
        "obj_camera": cam.path() if cam else None,
        "viewport": viewport.name(),
        "errors": errors,
    }


def set_viewport_display(shading_mode=None, guide=None, isolate=None, grid=None,
                         viewer=None):
    """Set shading / guides / visible-objects mask on the current scene viewer.

    shading_mode: wireframe|flat|smooth|smooth_wire
    isolate: node path or '*' for everything
    grid: bool — perspective reference plane (XZ)
    """
    sv = _scene_viewer(viewer)
    viewport = sv.curViewport()
    settings = viewport.settings()
    changes = []

    mode_map = {
        "wireframe": hou.glShadingType.Wire,
        "wire": hou.glShadingType.Wire,
        "flat": hou.glShadingType.Flat,
        "smooth": hou.glShadingType.Smooth,
        "shade": hou.glShadingType.Smooth,
        "smooth_wire": hou.glShadingType.SmoothWire,
        "shade_wire": hou.glShadingType.SmoothWire,
    }
    hscript_mode = {
        "wireframe": "wire",
        "wire": "wire",
        "flat": "flat",
        "smooth": "shade",
        "shade": "shade",
        "smooth_wire": "shade_wire",
        "shade_wire": "shade_wire",
    }

    if shading_mode is not None:
        mode = mode_map.get(shading_mode)
        if mode is None:
            raise ValueError("Unknown shading_mode %r. Use: %s" % (
                shading_mode, sorted(mode_map)))
        for tname in ("SceneObject", "DisplayModel", "CurrentModel"):
            ds = settings.displaySet(getattr(hou.displaySetType, tname))
            ds.setShadedMode(mode)
            try:
                ds.useLighting(True)
            except Exception:
                pass
        vp_id = _hscript_viewport_path(sv, viewport)
        hs = hscript_mode.get(shading_mode, "shade")
        for display_set in ("scene", "display", "current"):
            hou.hscript("viewdispset -s %s -l on %s %s" % (hs, display_set, vp_id))
        changes.append("shading=%s" % shading_mode)

    if guide is not None:
        settings.enableGuide(hou.viewportGuide.NodeGuides, bool(guide))
        changes.append("guides=%s" % bool(guide))

    if grid is not None:
        vp_id = _hscript_viewport_path(sv, viewport)
        grid_state = apply_grid(settings, bool(grid), viewer=sv, vp_id=vp_id)
        changes.append("grid=%s" % bool(grid))
        changes.append("grid_on=%s" % grid_state.get("on"))

    isolate_info = None
    if isolate is not None:
        isolate_info = resolve_isolate_path(isolate)
        settings.setVisibleObjects(isolate_info["applied"])
        changes.append("visibleObjects=%s" % isolate_info["applied"])
        if isolate_info.get("rewritten"):
            changes.append("isolate_rewritten=%s->%s" % (
                isolate_info["requested"], isolate_info["applied"]))
        suppress_current_sop_ghost(settings)
        changes.append("current_geometry=False")

    return {"changes": changes, "viewport": viewport.name(),
            "hscript_path": _hscript_viewport_path(sv, viewport),
            "visibleObjects": (
                isolate_info["applied"] if isolate_info else None
            ) or (settings.visibleObjects() if hasattr(settings, "visibleObjects") else None),
            "isolate": isolate_info,
            "grid": read_grid_state(settings, viewer=sv)}


def list_hydra_renderers(viewer=None):
    """Hydra delegates on the LOP Scene Viewer (Houdini VK, Karma CPU/XPU, Storm)."""
    sv = _scene_viewer(viewer)
    snap = _hydra_snapshot(sv)
    snap["viewer"] = sv.name()
    snap["pwd"] = None
    try:
        snap["pwd"] = sv.pwd().path() if sv.pwd() else None
    except Exception:
        pass
    snap["desktop"] = _desktop_name(sv)
    return snap


def set_hydra_renderer(renderer, wait=False, viewer=None):
    """Switch LOP viewport delegate. renderer: 'xpu', 'cpu', 'vk', 'storm', or exact name.

    Does not restart or sleep. XPU pixels converge asynchronously — poll
    list_hydra_renderers / get_viewport_info, then capture later.
    `wait` is accepted and ignored (restartRenderer stalls the MCP thread).
    """
    sv = _scene_viewer(viewer)
    resolved = _resolve_hydra_name(sv, renderer)
    sv.setHydraRenderer(resolved)
    snap = _hydra_snapshot(sv)
    snap.update({
        "requested": renderer,
        "resolved": resolved,
        "viewer": sv.name(),
        "wait_ignored": bool(wait),
    })
    return snap


def restart_renderer(viewer=None):
    """Rebuild the active LOP Hydra delegate. Can stall the UI/MCP thread."""
    sv = _scene_viewer(viewer)
    sv.restartRenderer()
    snap = _hydra_snapshot(sv)
    snap.update({"restarted": True, "viewer": sv.name()})
    return snap


def set_renderer_paused(paused=True, viewer=None):
    sv = _scene_viewer(viewer)
    requested = bool(paused)
    sv.setRendererPaused(requested)
    snap = _hydra_snapshot(sv)
    snap["viewer"] = sv.name()
    snap["requested_paused"] = requested
    actual = snap.get("paused")
    snap["pause_honored"] = (actual is True) if requested else (actual is False)
    if snap["pause_honored"] is False:
        snap["pause_note"] = (
            "setRendererPaused(%s) did not stick (isRendererPaused=%r). "
            "H22 HOM has no other pause API; report unavailable rather than fake it."
            % (requested, actual)
        )
    snap["pause_api"] = "hou.SceneViewer.setRendererPaused"
    return snap


_VIEWPORT_SAMPLE_SETTERS = (
    "setHydraSamples", "setPixelSamples", "setKarmaSamples",
    "setHydraPixelSamples", "setViewportSamples",
)
_VIEWPORT_SAMPLE_GETTERS = (
    "hydraSamples", "pixelSamples", "karmaSamples",
    "hydraPixelSamples", "viewportSamples",
)
_VIEWPORT_PREVIEW_SETTERS = (
    "setPreviewMode", "setHydraPreview", "setKarmaPreview",
)


def set_karma_quality(samples=None, preview=None, paused=None,
                      lop_path=None, parent_path=None, viewer=None):
    """Karma viewport quality. H22 has no pixel-sample HOM on SceneViewer.

    Sets LOP karmarendersettings when lop_path is given. Always reports
    viewport sample API availability instead of pretending.
    """
    sv = _scene_viewer(viewer)
    snap = _hydra_snapshot(sv)
    viewport = {
        "samples": "unavailable",
        "preview": "unavailable",
        "tried": [],
    }
    for name in _VIEWPORT_SAMPLE_SETTERS:
        fn = getattr(sv, name, None)
        viewport["tried"].append(name)
        if fn is None or samples is None:
            continue
        try:
            fn(int(samples))
            viewport["samples"] = {"method": name, "value": int(samples)}
            break
        except Exception as e:
            viewport["samples"] = {"method": name, "error": str(e)}
    if viewport["samples"] == "unavailable" and samples is not None:
        for name in _VIEWPORT_SAMPLE_GETTERS:
            if getattr(sv, name, None) is not None:
                viewport["samples"] = {"method": name, "note": "getter only"}
                break
    if preview is not None:
        honoured = False
        for name in _VIEWPORT_PREVIEW_SETTERS:
            fn = getattr(sv, name, None)
            viewport["tried"].append(name)
            if fn is None:
                continue
            try:
                fn(bool(preview))
                viewport["preview"] = {"method": name, "value": bool(preview)}
                honoured = True
                break
            except Exception as e:
                viewport["preview"] = {"method": name, "error": str(e)}
        if not honoured and viewport["preview"] == "unavailable":
            viewport["preview"] = "unavailable"
    lop = None
    if lop_path is not None and (samples is not None or preview is not None):
        from houdinimcp.handlers.lop import set_karma_samples
        lop = set_karma_samples(
            lop_path, samples=samples, preview=preview,
            parent_path=parent_path,
        )
    pause = None
    if paused is not None:
        pause = set_renderer_paused(paused, viewer=viewer)
    snap.update({
        "viewer": sv.name(),
        "viewport_quality": viewport,
        "lop": lop,
        "pause": pause,
    })
    return snap


def frame_usd_prim(path, prim_path, viewer=None):
    """Frame the LOP viewer on a USD prim's bbox. Not OBJ visibleObjects."""
    from houdinimcp.handlers.lop import usd_prim_bbox
    box = usd_prim_bbox(path, prim_path)
    result = frame_bbox(min_vec=box["min"], max_vec=box["max"], viewer=viewer)
    result["prim"] = prim_path
    result["lop"] = path
    result["bbox"] = box
    return result


def set_hydra_display(proxy=None, guide=None, render=None, materials=None,
                      procedurals=None, viewer=None):
    """USD purpose / material vis on the LOP Hydra viewer (per current delegate)."""
    sv = _scene_viewer(viewer)
    changes = []
    mapping = (
        ("proxy", proxy, "showProxyPurpose"),
        ("guide", guide, "showGuidePurpose"),
        ("render", render, "showRenderPurpose"),
        ("materials", materials, "showMaterials"),
        ("procedurals", procedurals, "showHydraProcedurals"),
    )
    for label, value, method in mapping:
        if value is None:
            continue
        fn = getattr(sv, method, None)
        if fn is None:
            changes.append("%s=unavailable" % label)
            continue
        fn(bool(value))
        changes.append("%s=%s" % (label, bool(value)))
    snap = _hydra_snapshot(sv)
    snap.update({"changes": changes, "viewer": sv.name()})
    return snap


def set_viewport_renderer(renderer, viewer=None):
    """LOP Hydra delegate (xpu/cpu/vk/storm) or OBJ view type (persp/top/front)."""
    sv = _scene_viewer(viewer)
    key = renderer.lower().replace(" ", "")
    hydra_keys = ("xpu", "cpu", "vk", "vulkan", "storm", "karma", "hydra", "houdini", "gl")
    hydra_available = ()
    try:
        hydra_available = sv.hydraRenderers() or ()
    except Exception:
        hydra_available = ()
    if any(k in key for k in hydra_keys) or renderer in hydra_available:
        return set_hydra_renderer(renderer, viewer=viewer)
    viewport = sv.curViewport()
    vtype = hou.geometryViewportType.__dict__.get(renderer)
    if vtype is None:
        dir_map = {
            "front": hou.geometryViewportType.Front,
            "back": hou.geometryViewportType.Back,
            "left": hou.geometryViewportType.Left,
            "right": hou.geometryViewportType.Right,
            "top": hou.geometryViewportType.Top,
            "bottom": hou.geometryViewportType.Bottom,
            "persp": hou.geometryViewportType.Perspective,
            "perspective": hou.geometryViewportType.Perspective,
        }
        vtype = dir_map.get(renderer.lower())
    if vtype is None:
        raise ValueError(
            "Unknown renderer %r. Hydra: %s. Or view types: persp/top/front/..."
            % (renderer, list(hydra_available))
        )
    viewport.changeType(vtype)
    return {"view_type": renderer, "viewer": sv.name()}


def frame_selection(viewer=None):
    sv = _scene_viewer(viewer)
    sv.curViewport().frameSelected()
    return {"framed": "selection", "viewer": sv.name()}


def frame_all(viewer=None):
    sv = _scene_viewer(viewer)
    viewport = sv.curViewport()
    vis = ""
    try:
        vis = viewport.settings().visibleObjects() or ""
    except Exception:
        vis = ""
    if vis not in ("", "*"):
        matched = count_visible_objects(vis)
        if matched == 0:
            raise ValueError(
                "frame_all refused: isolate %r matches no objects; use frame_bbox"
                % vis
            )
    viewport.frameAll()
    return {"framed": "all", "viewer": sv.name(), "visibleObjects": vis}


def frame_bbox(min_vec=None, max_vec=None, node_path=None, viewer=None):
    """Frame a world bbox or a node's geometry. Does not home the grid."""
    sv = _scene_viewer(viewer)
    viewport = sv.curViewport()
    bbox = None
    source = None
    if node_path:
        node = hou.node(node_path)
        if node is None:
            raise ValueError("Node not found: %s" % node_path)
        geo = None
        try:
            geo = node.geometry()
        except Exception:
            geo = None
        if geo is None:
            try:
                dn = node.displayNode()
                geo = dn.geometry() if dn else None
            except Exception:
                geo = None
        if geo is None:
            raise ValueError("No geometry on %s" % node_path)
        bbox = geo.boundingBox()
        source = node_path
    elif min_vec is not None and max_vec is not None:
        if len(min_vec) != 3 or len(max_vec) != 3:
            raise ValueError("min_vec and max_vec must be 3-floats")
        bbox = hou.BoundingBox(
            float(min_vec[0]), float(min_vec[1]), float(min_vec[2]),
            float(max_vec[0]), float(max_vec[1]), float(max_vec[2]),
        )
        source = "explicit"
    else:
        raise ValueError("frame_bbox needs node_path or min_vec+max_vec")
    viewport.frameBoundingBox(bbox)
    try:
        mn = tuple(bbox.minvec())
        mx = tuple(bbox.maxvec())
    except Exception:
        mn = tuple(min_vec) if min_vec is not None else None
        mx = tuple(max_vec) if max_vec is not None else None
    return {
        "framed": "bbox",
        "viewer": sv.name(),
        "source": source,
        "min": mn,
        "max": mx,
    }


def set_viewport_direction(direction, viewer=None):
    sv = _scene_viewer(viewer)
    viewport = sv.curViewport()
    dir_map = {
        "front": hou.geometryViewportType.Front,
        "back": hou.geometryViewportType.Back,
        "left": hou.geometryViewportType.Left,
        "right": hou.geometryViewportType.Right,
        "top": hou.geometryViewportType.Top,
        "bottom": hou.geometryViewportType.Bottom,
        "persp": hou.geometryViewportType.Perspective,
    }
    vtype = dir_map.get(direction)
    if vtype is None:
        raise ValueError("Unknown direction: %s. Use: %s" % (direction, list(dir_map)))
    viewport.changeType(vtype)
    return {"direction": direction, "viewer": sv.name()}


def capture_screenshot(output_path=None, source="viewport", resolution=None,
                       viewer=None):
    """Capture what the artist sees, or a beauty pass.

    source:
      viewport — SceneViewer flipbook snapshot of the current Hydra buffer
      opengl   — OpenGL ROP (OBJ-centric; weaker for pure LOP stages)
    Desktop/UI grabs belong on the MCP *bridge* (outside houdini-bin).

    Does not wait for Karma XPU to converge. Restores renderer pause.
    """
    if not output_path:
        output_path = os.path.join(tempfile.gettempdir(), "houdini_mcp_viewport.png")
    source = (source or "viewport").lower()
    res = resolution or [1600, 900]
    if source == "opengl":
        return _capture_opengl(output_path, res)
    if source not in ("viewport", "flipbook"):
        raise ValueError("source must be 'viewport' or 'opengl', got %r" % source)
    return _capture_flipbook(output_path, res, viewer=viewer)


def _capture_flipbook(output_path, res, viewer=None):
    sv = _scene_viewer(viewer)
    viewport = sv.curViewport()
    was_paused = None
    try:
        was_paused = bool(sv.isRendererPaused())
    except Exception:
        was_paused = None

    settings = sv.flipbookSettings().stash()
    frame = hou.frame()
    settings.frameRange((frame, frame))
    settings.output(output_path)
    settings.outputToMPlay(False)
    for meth, args in (
        ("leaveFrameAtEnd", (False,)),
        ("initializeSimulations", (False,)),
        ("useMotionBlur", (False,)),
        ("renderAllViewports", (False,)),
        ("appendFramesToCurrent", (False,)),
    ):
        fn = getattr(settings, meth, None)
        if fn is None:
            continue
        try:
            fn(*args)
        except Exception:
            pass
    # Snapshot: do not wait for progressive Hydra to finish the frame.
    try:
        settings.setUseFrameTimeLimit(True)
        settings.setFrameTimeLimit(FLIPBOOK_FRAME_TIME_LIMIT)
    except Exception:
        pass
    try:
        settings.setUseFrameProgressLimit(False)
    except Exception:
        pass
    try:
        settings.useResolution(True)
        settings.resolution((int(res[0]), int(res[1])))
    except Exception:
        pass

    # Freeze the current Hydra buffer so flipbook does not wait for XPU.
    if was_paused is False:
        try:
            sv.setRendererPaused(True)
        except Exception:
            pass
    try:
        sv.flipbook(viewport=viewport, settings=settings)
    finally:
        _restore_renderer_paused(sv, was_paused)

    snap = _hydra_snapshot(sv)
    look = None
    try:
        look = viewport.cameraPath() or None
    except Exception:
        pass
    vis = ""
    try:
        vis = viewport.settings().visibleObjects() or ""
    except Exception:
        vis = ""
    matched = count_visible_objects(vis)
    grid_state = read_grid_state(viewport.settings(), viewer=sv)
    exists = os.path.isfile(output_path)
    nbytes = os.path.getsize(output_path) if exists else 0
    looks_grid = False
    if exists and nbytes > 0:
        try:
            looks_grid = bool(png_looks_grid_only(output_path))
        except Exception:
            looks_grid = False
    # PNG high-contrast is the infinite grid OR a blown-out/unlit mesh.
    # Only refuse as grid_only when HOM also says the reference plane is on.
    grid_on = bool(grid_state.get("on"))
    reasons = evaluate_capture_guard(
        vis, matched, exists, nbytes,
        grid_on=grid_on,
        looks_grid_only=(looks_grid and grid_on),
    )
    payload = {
        "filepath": output_path,
        "source": "viewport",
        "viewport": viewport.name(),
        "viewer": sv.name(),
        "hscript_path": _hscript_viewport_path(sv, viewport),
        "camera_path": look,
        "hydra_renderer": snap.get("current"),
        # `paused` is the restored artist state. Flipbook's immediate
        # isRendererPaused() is often still True; QTimer 0/250ms finishes it.
        "paused": False if was_paused is None else bool(was_paused),
        "paused_before": was_paused,
        "paused_immediate": snap.get("paused"),
        "paused_restored_to": False if was_paused is None else bool(was_paused),
        "snapshot": True,
        "frame_time_limit": FLIPBOOK_FRAME_TIME_LIMIT,
        "exists": exists,
        "bytes": nbytes,
        "visibleObjects": vis,
        "matched_objects": matched,
        "grid": grid_state,
        "empty": "empty_isolate" in reasons,
        "grid_only": "grid_only" in reasons,
    }
    if reasons:
        payload["error"] = "capture refused: %s" % ",".join(reasons)
        raise RuntimeError(payload["error"])
    return payload


def _capture_opengl(output_path, res):
    out = hou.node("/out")
    if not out:
        raise RuntimeError("/out not found")
    rop = out.node("mcp_gl_capture")
    if rop is None:
        rop = out.createNode("opengl", "mcp_gl_capture")
    rop.parm("picture").set(output_path)
    if rop.parm("tres"):
        rop.parm("tres").set(True)
    if rop.parm("res1"):
        rop.parm("res1").set(int(res[0]))
    if rop.parm("res2"):
        rop.parm("res2").set(int(res[1]))
    if rop.parm("trange"):
        rop.parm("trange").set(0)
    if rop.parm("usegeocolor"):
        rop.parm("usegeocolor").set(True)
    try:
        sv = _scene_viewer()
        cam = sv.curViewport().camera()
        if cam and rop.parm("camera"):
            rop.parm("camera").set(cam.path())
    except Exception:
        pass
    rop.render()
    return {
        "filepath": output_path,
        "source": "opengl",
        "exists": os.path.isfile(output_path),
        "bytes": os.path.getsize(output_path) if os.path.isfile(output_path) else 0,
    }


def set_current_network(path):
    """Focus a network editor on a node. Does not enumerate desktops."""
    _require_ui()
    editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
    if not editor:
        raise RuntimeError("No network editor found")
    node = hou.node(path)
    if not node:
        raise ValueError("Node not found: %s" % path)
    editor.setCurrentNode(node)
    return {"path": path}
