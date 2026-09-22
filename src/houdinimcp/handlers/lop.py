"""USD/Solaris (LOP) handlers."""
import math

import hou

_MCP_MARK = "mcp_"
_DOME_TYPES = ("domelight::3.0", "domelight")
_EXPOSURE_PARMS = (
    "xn__inputsexposure_vya", "xn__inputsexposure_u3an",
    "light_exposure", "exposure",
)
_INTENSITY_PARMS = (
    "xn__inputsintensity_i0a", "xn__inputsintensity_u3an", "intensity",
)
_COLOR_R = ("xn__inputscolor_ztar", "colorr", "light_colorr")
_COLOR_G = ("xn__inputscolor_ztag", "colorg", "light_colorg")
_COLOR_B = ("xn__inputscolor_ztab", "colorb", "light_colorb")
_TEXTURE_PARMS = (
    "xn__inputstexturefile_r3ah", "xn__texturefile_0ta",
    "texturefile", "env_map", "file",
)
_SAMPLES_PARMS = ("samplesperpixel", "xn__karma_global_samplesperpixel_80an")
_PREVIEW_PARMS = ("percentofsamples", "xn__karmaglobalpercentofsamples")
_DIFFUSE_R = ("diffuseColorr", "diffuser", "basecolorr")
_DIFFUSE_G = ("diffuseColorg", "diffuseg", "basecolorg")
_DIFFUSE_B = ("diffuseColorb", "diffuseb", "basecolorb")
_ROUGH_PARMS = ("roughness", "specularRoughness")
_METAL_PARMS = ("metallic", "metalness")
_TX_PARMS = ("tx", "t")
_TY_PARMS = ("ty",)
_TZ_PARMS = ("tz",)
_RX_PARMS = ("rx",)
_RY_PARMS = ("ry",)
_RZ_PARMS = ("rz",)


def lop_stage_info(path):
    """Get USD stage info from a LOP node: prims, layers, time codes."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    root_prims = [str(p.GetPath()) for p in stage.GetPseudoRoot().GetChildren()]
    default_prim = str(stage.GetDefaultPrim().GetPath()) if stage.HasDefaultPrim() else None
    return {
        "path": node.path(),
        "prim_count": len(list(stage.Traverse())),
        "root_prims": root_prims,
        "default_prim": default_prim,
        "layer_count": len(stage.GetLayerStack()),
        "start_time": stage.GetStartTimeCode(),
        "end_time": stage.GetEndTimeCode(),
    }


def lop_prim_get(path, prim_path, include_attrs=False):
    """Get details of a specific USD prim."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        raise ValueError(f"Prim not found: {prim_path}")
    info = {
        "prim_path": str(prim.GetPath()),
        "type": str(prim.GetTypeName()),
        "children": [str(c.GetPath()) for c in prim.GetChildren()],
    }
    if include_attrs:
        attrs = {}
        for attr in prim.GetAttributes():
            val = attr.Get()
            attrs[attr.GetName()] = str(val) if val is not None else None
        info["attributes"] = attrs
    return info


def lop_prim_search(path, pattern, type_name=None):
    """Search for USD prims matching a pattern."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    rule = hou.LopSelectionRule()
    rule.setPathPattern(pattern)
    if type_name:
        rule.setTypeName(type_name)
    prims = rule.expandedPaths(node)
    return {
        "path": node.path(),
        "pattern": pattern,
        "matches": [str(p) for p in prims],
        "count": len(prims),
    }


def lop_layer_info(path):
    """Get USD layer stack info from a LOP node."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    layers = []
    for layer in stage.GetLayerStack():
        layers.append({
            "identifier": layer.identifier,
            "path": layer.realPath,
        })
    return {"path": node.path(), "layers": layers, "count": len(layers)}


def list_usd_prims(path, root_prim="/", max_depth=3):
    """List USD prims up to a given depth."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    prims = []

    def _walk(prim, depth):
        if depth > max_depth:
            return
        prims.append({
            "path": str(prim.GetPath()),
            "type": str(prim.GetTypeName()),
            "depth": depth,
        })
        for child in prim.GetChildren():
            _walk(child, depth + 1)

    root = stage.GetPrimAtPath(root_prim) if root_prim != "/" else stage.GetPseudoRoot()
    if not root:
        raise ValueError(f"Root prim not found: {root_prim}")
    for child in root.GetChildren():
        _walk(child, 1)
    return {"path": path, "count": len(prims), "prims": prims}


def get_usd_attribute(path, prim_path, attr_name):
    """Get a specific USD attribute value."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        raise ValueError(f"Prim not found: {prim_path}")
    attr = prim.GetAttribute(attr_name)
    if not attr:
        raise ValueError(f"Attribute not found: {attr_name}")
    return {"prim": prim_path, "attr": attr_name, "value": str(attr.Get()), "type": str(attr.GetTypeName())}


def set_usd_attribute(path, prim_path, attr_name, value):
    """Set a USD attribute value."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        raise ValueError(f"Prim not found: {prim_path}")
    attr = prim.GetAttribute(attr_name)
    if not attr:
        raise ValueError(f"Attribute not found: {attr_name}")
    attr.Set(value)
    return {"prim": prim_path, "attr": attr_name, "set": True}


def get_usd_prim_stats(path, prim_path):
    """Get stats about a USD prim: child count, attr count, etc."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        raise ValueError(f"Prim not found: {prim_path}")
    return {
        "prim": prim_path,
        "type": str(prim.GetTypeName()),
        "child_count": len(prim.GetChildren()),
        "attr_count": len(prim.GetAttributes()),
        "is_active": prim.IsActive(),
        "has_payload": prim.HasPayload(),
    }


def get_last_modified_prims(path, count=10):
    """Get recently modified prims from the edit target layer."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    edit_layer = stage.GetEditTarget().GetLayer()
    prims = []
    for prim_path in edit_layer.rootPrims:
        prims.append(str(prim_path))
        if len(prims) >= count:
            break
    return {"path": path, "prims": prims}


def create_lop_node(parent_path, node_type, name=None):
    """Create a LOP node."""
    parent = hou.node(parent_path)
    if not parent:
        raise ValueError(f"Parent not found: {parent_path}")
    node = parent.createNode(node_type, node_name=name)
    return {"path": node.path(), "name": node.name(), "type": node_type}


def get_usd_composition(path, prim_path):
    """Get composition arcs (references, payloads, inherits, etc.) for a prim."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        raise ValueError(f"Prim not found: {prim_path}")
    arcs = {
        "references": bool(prim.GetReferences()),
        "payloads": bool(prim.GetPayloads()),
        "inherits": bool(prim.GetInherits()),
        "specializes": bool(prim.GetSpecializes()),
    }
    return {"prim": prim_path, "composition": arcs}


def get_usd_variants(path, prim_path):
    """Get variant sets and selections for a prim."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        raise ValueError(f"Prim not found: {prim_path}")
    variant_sets = {}
    for vs_name in prim.GetVariantSets().GetNames():
        vs = prim.GetVariantSet(vs_name)
        variant_sets[vs_name] = {
            "choices": vs.GetVariantNames(),
            "selection": vs.GetVariantSelection(),
        }
    return {"prim": prim_path, "variant_sets": variant_sets}


def inspect_usd_layer(path, layer_index=0):
    """Inspect a specific USD layer by index in the stack."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    layers = stage.GetLayerStack()
    if layer_index >= len(layers):
        raise ValueError(f"Layer index {layer_index} out of range (max {len(layers) - 1})")
    layer = layers[layer_index]
    return {
        "index": layer_index,
        "identifier": layer.identifier,
        "path": layer.realPath,
        "root_prims": [str(p) for p in layer.rootPrims],
    }


def list_lights(path):
    """List all light prims in a USD stage."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    lights = []
    for prim in stage.Traverse():
        type_name = str(prim.GetTypeName())
        if "Light" in type_name:
            lights.append({
                "path": str(prim.GetPath()),
                "type": type_name,
            })
    return {"path": path, "count": len(lights), "lights": lights}


def lop_import(path, file, method="reference", prim_path=None):
    """Import a USD file via reference or sublayer."""
    parent = hou.node(path)
    if not parent:
        raise ValueError(f"Parent path not found: {path}")
    if method == "reference":
        node = parent.createNode("reference", "usd_import")
        node.parm("filepath1").set(file)
        if prim_path:
            node.parm("primpath").set(prim_path)
    elif method == "sublayer":
        node = parent.createNode("sublayer", "usd_import")
        node.parm("filepath1").set(file)
    else:
        raise ValueError(f"Unknown import method: {method}")
    return {"imported": True, "path": node.path(), "file": file, "method": method}


def _require_mcp_lop(parent_path, name):
    parent_path = parent_path or ""
    name = name or ""
    if _MCP_MARK in parent_path:
        return
    if parent_path.rstrip("/") in ("/stage",) and name.startswith(_MCP_MARK):
        return
    raise ValueError(
        "Lookdev helpers only under mcp_* isolation, got parent=%r name=%r"
        % (parent_path, name)
    )


def _set_control(node, value_name):
    """LOP 'set vs default' companion parm. Without this, values are ignored."""
    control = node.parm(value_name + "_control")
    if control is not None:
        try:
            control.set("set")
            return True
        except Exception:
            pass
    # Punycode companions: xn__inputsexposure_control_wcb next to xn__inputsexposure_vya
    stem = value_name.rsplit("_", 1)[0]
    for p in node.parms():
        n = p.name()
        if n.endswith("_control") and stem in n:
            try:
                p.set("set")
                return True
            except Exception:
                continue
    return False


def _set_parm(node, names, value):
    for name in names:
        parm = node.parm(name)
        if parm is None:
            continue
        _set_control(node, name)
        parm.set(value)
        return name
    return None


def _create_typed(parent, types, name):
    existing = parent.node(name)
    if existing:
        return existing, existing.type().name(), True
    last_err = None
    for node_type in types:
        try:
            node = parent.createNode(node_type, name)
            return node, node_type, False
        except Exception as e:
            last_err = e
    raise ValueError("Could not create %s (%s): %s" % (name, types, last_err))


def _stage_of(path):
    node = hou.node(path)
    if not node:
        raise ValueError("Node not found: %s" % path)
    stage = node.stage()
    if not stage:
        raise ValueError("No USD stage on: %s" % path)
    return node, stage


def _bbox_from_prim(prim):
    try:
        from pxr import UsdGeom
        imageable = UsdGeom.Imageable(prim)
        bound = imageable.ComputeWorldBound(0.0, "default")
        box = bound.ComputeAlignedBox() if hasattr(bound, "ComputeAlignedBox") else bound.GetBox()
        mn = box.GetMin()
        mx = box.GetMax()
        return [float(mn[0]), float(mn[1]), float(mn[2])], [
            float(mx[0]), float(mx[1]), float(mx[2])
        ]
    except Exception:
        pass
    attr = prim.GetAttribute("extent") if hasattr(prim, "GetAttribute") else None
    val = attr.Get() if attr else None
    if val is not None and len(val) == 2:
        a, b = val[0], val[1]
        return [float(a[0]), float(a[1]), float(a[2])], [
            float(b[0]), float(b[1]), float(b[2])
        ]
    raise ValueError("No world bound / extent on prim")


def usd_prim_bbox(path, prim_path):
    """World-ish bbox of a USD prim. Used to frame / place a lookdev camera."""
    node, stage = _stage_of(path)
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        raise ValueError("Prim not found: %s" % prim_path)
    mn, mx = _bbox_from_prim(prim)
    center = [(mn[i] + mx[i]) * 0.5 for i in range(3)]
    size = [mx[i] - mn[i] for i in range(3)]
    return {
        "path": path,
        "prim": prim_path,
        "min": mn,
        "max": mx,
        "center": center,
        "size": size,
    }


def _lookat_angles(eye, target):
    dx = target[0] - eye[0]
    dy = target[1] - eye[1]
    dz = target[2] - eye[2]
    dist_xz = math.hypot(dx, dz)
    ry = math.degrees(math.atan2(dx, dz))
    rx = -math.degrees(math.atan2(dy, dist_xz)) if dist_xz or dy else 0.0
    return rx, ry, 0.0


def lookdev_dome(parent_path="/stage", name="mcp_dome", input_path=None,
                 exposure=0.0, color=None, texture=None, primpath=None):
    """Create/edit a Dome Light LOP under mcp_* isolation."""
    _require_mcp_lop(parent_path, name)
    parent = hou.node(parent_path)
    if parent is None:
        raise ValueError("Parent not found: %s" % parent_path)
    node, created_type, existed = _create_typed(parent, _DOME_TYPES, name)
    if input_path:
        src = hou.node(input_path)
        if src is None:
            raise ValueError("input_path not found: %s" % input_path)
        node.setInput(0, src)
    set_parms = {}
    hit = _set_parm(node, _EXPOSURE_PARMS, float(exposure))
    if hit:
        set_parms[hit] = exposure
    hit = _set_parm(node, _INTENSITY_PARMS, 1.0)
    if hit:
        set_parms[hit] = 1.0
    if color is not None:
        if len(color) != 3:
            raise ValueError("color must be 3 floats")
        for names, val, key in (
            (_COLOR_R, color[0], "r"),
            (_COLOR_G, color[1], "g"),
            (_COLOR_B, color[2], "b"),
        ):
            hit = _set_parm(node, names, float(val))
            if hit:
                set_parms[hit] = val
    if texture:
        hit = _set_parm(node, _TEXTURE_PARMS, texture)
        if hit:
            set_parms[hit] = texture
    if primpath:
        hit = _set_parm(node, ("primpath", "primpattern"), primpath)
        if hit:
            set_parms[hit] = primpath
    lights = None
    try:
        lights = list_lights(node.path())
    except Exception:
        lights = None
    return {
        "path": node.path(),
        "type": node.type().name(),
        "created_type": created_type,
        "existed": existed,
        "parms": set_parms,
        "lights": lights,
    }


def lookdev_preview_surface(parent_path="/stage", name="mcp_preview",
                            input_path=None, prim_pattern="/world/hero",
                            color=None, roughness=0.4, metallic=0.0):
    """USD Preview Surface in a materiallibrary + assignmaterial, mcp_* only."""
    _require_mcp_lop(parent_path, name)
    parent = hou.node(parent_path)
    if parent is None:
        raise ValueError("Parent not found: %s" % parent_path)
    color = list(color) if color is not None else [0.15, 0.45, 0.85]
    if len(color) != 3:
        raise ValueError("color must be 3 floats")
    lib_name = name + "_lib"
    assign_name = name + "_assign"
    lib, _, _ = _create_typed(parent, ("materiallibrary",), lib_name)
    surface = lib.node("preview") or lib.createNode("usdpreviewsurface", "preview")
    _set_parm(surface, _DIFFUSE_R, float(color[0]))
    _set_parm(surface, _DIFFUSE_G, float(color[1]))
    _set_parm(surface, _DIFFUSE_B, float(color[2]))
    _set_parm(surface, _ROUGH_PARMS, float(roughness))
    _set_parm(surface, _METAL_PARMS, float(metallic))
    assign, _, _ = _create_typed(parent, ("assignmaterial",), assign_name)
    upstream = hou.node(input_path) if input_path else lib
    if input_path:
        src = hou.node(input_path)
        if src is None:
            raise ValueError("input_path not found: %s" % input_path)
        lib.setInput(0, src)
        assign.setInput(0, lib)
    else:
        assign.setInput(0, lib)
        upstream = lib
    prefix = "/materials/"
    pref_parm = lib.parm("matpathprefix")
    if pref_parm:
        try:
            prefix = pref_parm.eval() or prefix
        except Exception:
            pass
    if not prefix.endswith("/"):
        prefix += "/"
    mat_path = prefix + surface.name()
    _set_parm(assign, ("primpattern1", "primpattern"), prim_pattern)
    _set_parm(assign, ("matspecpath1", "matspecpath"), mat_path)
    return {
        "library": lib.path(),
        "surface": surface.path(),
        "assign": assign.path(),
        "prim_pattern": prim_pattern,
        "material": mat_path,
        "color": color,
        "roughness": roughness,
        "metallic": metallic,
        "upstream": upstream.path() if upstream else None,
    }


def lookdev_display_color(path, prim_path, color):
    """Set primvars:displayColor on a mesh prim (GL/Karma fallback colour)."""
    if color is None or len(color) != 3:
        raise ValueError("color must be 3 floats")
    node, stage = _stage_of(path)
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        raise ValueError("Prim not found: %s" % prim_path)
    rgb = [float(color[0]), float(color[1]), float(color[2])]
    method = None
    try:
        from pxr import UsdGeom, Gf
        gprim = UsdGeom.Gprim(prim)
        gprim.CreateDisplayColorAttr([Gf.Vec3f(*rgb)])
        method = "UsdGeom.Gprim"
    except Exception:
        attr = prim.GetAttribute("primvars:displayColor")
        if attr is None and hasattr(prim, "CreateAttribute"):
            attr = prim.CreateAttribute("primvars:displayColor", "color3f[]")
        if attr is None:
            raise ValueError("Cannot author displayColor on %s" % prim_path)
        attr.Set([rgb])
        method = "primvars:displayColor"
    return {"path": path, "prim": prim_path, "color": rgb, "method": method}


def lookdev_camera(parent_path="/stage", name="mcp_cam", look_at="/world/hero",
                   input_path=None, lop_path=None, distance_scale=2.2):
    """Place a LOP Camera looking at a prim's bbox (hero + a bit of ground).

    Does not call viewport.setCamera on a LOP node — that is InvalidNodeType.
    Returns the USD prim string for set_viewport_camera.
    """
    _require_mcp_lop(parent_path, name)
    parent = hou.node(parent_path)
    if parent is None:
        raise ValueError("Parent not found: %s" % parent_path)
    stage_path = lop_path or input_path
    if not stage_path:
        raise ValueError("lop_path or input_path required (LOP with a stage)")
    box = usd_prim_bbox(stage_path, look_at)
    center = box["center"]
    size = box["size"]
    span = max(0.001, math.sqrt(sum(s * s for s in size)))
    dist = span * float(distance_scale)
    eye = [center[0] + dist * 0.7, center[1] + dist * 0.45, center[2] + dist]
    rx, ry, rz = _lookat_angles(eye, center)
    cam, _, existed = _create_typed(parent, ("camera",), name)
    if input_path:
        src = hou.node(input_path)
        if src is None:
            raise ValueError("input_path not found: %s" % input_path)
        cam.setInput(0, src)
    _set_parm(cam, _TX_PARMS, float(eye[0]))
    _set_parm(cam, _TY_PARMS, float(eye[1]))
    _set_parm(cam, _TZ_PARMS, float(eye[2]))
    if cam.parm("lookatenable") is not None:
        cam.parm("lookatenable").set(True)
        if cam.parm("lookatprim") is not None:
            cam.parm("lookatprim").set(look_at)
        elif cam.parm("lookatpositionx") is not None:
            cam.parm("lookatpositionx").set(float(center[0]))
            cam.parm("lookatpositiony").set(float(center[1]))
            cam.parm("lookatpositionz").set(float(center[2]))
    else:
        _set_parm(cam, _RX_PARMS, float(rx))
        _set_parm(cam, _RY_PARMS, float(ry))
        _set_parm(cam, _RZ_PARMS, float(rz))
    usd_prim = None
    try:
        parm = cam.parm("primpath")
        usd_prim = parm.eval() if parm else None
    except Exception:
        usd_prim = None
    if not usd_prim:
        usd_prim = "/" + cam.name()
    return {
        "path": cam.path(),
        "existed": existed,
        "look_at": look_at,
        "usd_prim": usd_prim,
        "eye": eye,
        "rotate": [rx, ry, rz],
        "bbox": box,
        "note": "Look through usd_prim with set_viewport_camera; LOP Camera nodes are not OBJ cameras.",
    }


def set_karma_samples(lop_path, samples=None, preview=None, parent_path=None,
                      name="mcp_karma"):
    """Set Karma LOP samplesperpixel / percentofsamples.

    Viewport Hydra has no pixel-sample HOM on H22 — this is the real knob.
    """
    node = hou.node(lop_path) if lop_path else None
    created = False
    if node is None:
        raise ValueError("LOP not found: %s" % lop_path)
    type_name = node.type().name()
    if "karma" not in type_name.lower() or "render" not in type_name.lower():
        parent = hou.node(parent_path) if parent_path else node.parent()
        if parent is None:
            raise ValueError("Parent not found for karmarendersettings")
        _require_mcp_lop(parent.path(), name)
        karma, _, existed = _create_typed(
            parent, ("karmarendersettings",), name)
        if not existed:
            created = True
            karma.setInput(0, node)
        node = karma
        type_name = node.type().name()
    set_parms = {}
    if samples is not None:
        hit = _set_parm(node, _SAMPLES_PARMS, int(samples))
        if hit is None:
            raise ValueError("No samplesperpixel parm on %s" % node.path())
        set_parms[hit] = int(samples)
    if preview is not None:
        pct = 25 if preview else 100
        hit = _set_parm(node, _PREVIEW_PARMS, int(pct))
        if hit:
            set_parms[hit] = pct
        set_parms["preview"] = bool(preview)
    return {
        "path": node.path(),
        "type": type_name,
        "created": created,
        "parms": set_parms,
        "viewport_samples": "unavailable",
        "note": "H22 SceneViewer has no pixel-sample HOM; LOP karmarendersettings is the quality control.",
    }
