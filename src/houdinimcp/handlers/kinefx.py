"""KineFX / FBX character tools. Mixamo lives here, not in Blender.

Isolation: only create under a parent whose path contains mcp_.

Capybara trap (H22): testgeometry_capybara output 0 is rest skin — not
time-dependent. Animation is output 2 as a motion clip. Wire
kinefx::motionclipevaluate then kinefx::jointdeform
(skin + capture pose + eval). list_joints on the 29k-pt capture mesh
is the wrong tool; pass the skeleton SOP.
"""
import hashlib
import os
import struct

import hou

_MCP_MARK = "mcp_"
_FILE_PARMS = (
    "fbxfile", "file", "filename", "sopfile", "animfile", "source",
)
_SKIN_POINT_LIMIT = 2048
_CAPY_CLIPS = {
    "walk": "walk",
    "clothesline": "clothesline",
    "clothes_line": "clothesline",
    "elbowdrop": "elbowdrop",
    "elbow_drop": "elbowdrop",
    "fall": "fall",
}
_OUTPUTCLIP_PARMS = ("outputclip", "output_clip", "outputmotionclip")
_CLIP_PARMS = ("clip", "animationclip", "animclip")
_JOINT_ALIASES = {
    "hip": "hips",
    "pelvis": "hips",
}


def _require_mcp(path):
    if _MCP_MARK not in (path or ""):
        raise ValueError("KineFX helpers only under mcp_* isolation, got %r" % path)


def _set_file_parm(node, file_path):
    for name in _FILE_PARMS:
        parm = node.parm(name)
        if parm is None:
            continue
        parm.set(file_path)
        return name
    raise ValueError("No FBX file parm on %s (tried %s)" % (node.path(), _FILE_PARMS))


def _geo_container(parent_path, name):
    parent = hou.node(parent_path)
    if not parent:
        raise ValueError("Parent not found: %s" % parent_path)
    existing = parent.node(name)
    if existing:
        return existing
    return parent.createNode("geo", name)


def list_joints(node_path, max_joints=256):
    """Point-based KineFX skeleton: name + P (+ transform if present).

    Refuses a capture/skin mesh (thousands of points, no `name`). Pass the
    Capture Pose / Animated Pose SOP, not rest skin.
    """
    node = hou.node(node_path)
    if not node:
        raise ValueError("Node not found: %s" % node_path)
    geo = node.geometry()
    if geo is None:
        raise ValueError("No geometry: %s" % node_path)
    name_attr = geo.findPointAttrib("name")
    xform_attr = geo.findPointAttrib("transform")
    points = geo.points()
    n_points = len(points)
    if name_attr is None and n_points > _SKIN_POINT_LIMIT:
        raise ValueError(
            "Looks like a capture/skin mesh (%d points, no name attrib). "
            "Pass the skeleton SOP (Capture Pose / Animated Pose), not rest skin. "
            "Use attach_kinefx_deform for jointdeform."
            % n_points
        )
    joints = []
    taken = 0
    for pt in points:
        if taken >= int(max_joints):
            break
        if name_attr:
            name = pt.attribValue("name")
            if not name:
                continue
        rec = {"point": pt.number(), "P": list(pt.position())}
        if name_attr:
            rec["name"] = name
        if xform_attr:
            rec["has_transform"] = True
        joints.append(rec)
        taken += 1
    return {
        "path": node_path,
        "count": len(joints),
        "total_points": n_points,
        "has_name": name_attr is not None,
        "has_transform": xform_attr is not None,
        "point_attribs": [a.name() for a in geo.pointAttribs()],
        "joints": joints,
    }


def pose_hash(node_path, max_points=64):
    """Stable hash of a SOP's point positions. Proof that a clip is not T-pose."""
    node = hou.node(node_path)
    if not node:
        raise ValueError("Node not found: %s" % node_path)
    geo = node.geometry()
    if geo is None:
        raise ValueError("No geometry: %s" % node_path)
    points = geo.points()
    n = len(points)
    if n == 0:
        raise ValueError("No points on %s" % node_path)
    step = max(1, n // int(max_points))
    digest = hashlib.md5()
    sampled = 0
    for i in range(0, n, step):
        p = points[i].position()
        digest.update(struct.pack("fff", float(p[0]), float(p[1]), float(p[2])))
        sampled += 1
        if sampled >= int(max_points):
            break
    return {
        "path": node_path,
        "hash": digest.hexdigest(),
        "points": n,
        "sampled": sampled,
        "frame": hou.intFrame() if hasattr(hou, "intFrame") else None,
    }


def normalize_joint_name(name):
    """Strip Mixamo prefixes and punctuation so clip names can match rest."""
    s = (name or "").strip()
    if not s:
        return ""
    if ":" in s:
        s = s.rsplit(":", 1)[-1]
    key = s.lower().replace(" ", "").replace("_", "").replace("-", "")
    return _JOINT_ALIASES.get(key, key)


def map_joint_names(rest_names, clip_names):
    """Map clip joint names onto rest skeleton names.

    Mixamo-like `mixamorig:Hips` matches `hips`. Unmapped clip names raise.
    Extra rest joints are allowed.
    """
    rest_idx = {}
    for n in rest_names:
        key = normalize_joint_name(n)
        if key:
            rest_idx[key] = n
    mapped = []
    unmapped = []
    for c in clip_names:
        if not c:
            continue
        key = normalize_joint_name(c)
        if key in rest_idx:
            mapped.append({"clip": c, "rest": rest_idx[key]})
        else:
            unmapped.append(c)
    if unmapped:
        raise ValueError("Unmapped clip joints: %s" % ", ".join(unmapped))
    if not mapped:
        raise ValueError("No joints mapped (need name attribs on both skeletons)")
    return mapped


def map_kinefx_joints(rest_path, clip_path, max_joints=4096):
    """Inspect two skeleton SOPs and return a Mixamo-style name map."""
    rest = list_joints(rest_path, max_joints=max_joints)
    clip = list_joints(clip_path, max_joints=max_joints)
    rest_names = [j.get("name") for j in rest["joints"] if j.get("name")]
    clip_names = [j.get("name") for j in clip["joints"] if j.get("name")]
    mapping = map_joint_names(rest_names, clip_names)
    return {
        "rest": rest_path,
        "clip": clip_path,
        "count": len(mapping),
        "map": mapping,
    }


def _apply_name_map(geo, src_node, mapping, name="name_map"):
    wrangle = geo.node(name) or geo.createNode("attribwrangle", name)
    wrangle.setInput(0, src_node)
    lines = [
        'if (s@name == "%s") { s@name = "%s"; }' % (
            m["clip"].replace('"', '\\"'), m["rest"].replace('"', '\\"'))
        for m in mapping
    ]
    snippet = "\n".join(lines)
    if wrangle.parm("snippet") is not None:
        wrangle.parm("snippet").set(snippet)
    if wrangle.parm("class") is not None:
        try:
            wrangle.parm("class").set(0)
        except Exception:
            pass
    return wrangle


def _set_parm(node, names, value):
    for name in names:
        parm = node.parm(name)
        if parm is None:
            continue
        parm.set(value)
        return name
    return None


def _motionclip_range(node, default=(1, 64)):
    geo = None
    try:
        geo = node.geometry()
    except Exception:
        geo = None
    if geo is None:
        return list(default)
    try:
        val = geo.attribValue("clipinfo")
        if val is not None and hasattr(val, "__getitem__") and len(val) >= 2:
            return [int(val[0]), int(val[1])]
    except Exception:
        pass
    try:
        prims = geo.prims()
        if prims:
            return [1, max(1, len(prims))]
    except Exception:
        pass
    return list(default)


def _ensure_mcp_geo(parent_path, geo_name=None):
    _require_mcp(parent_path)
    parent = hou.node(parent_path)
    if parent is not None:
        if parent.type().name() == "geo":
            return parent
        if parent.path() == "/obj":
            name = geo_name or "mcp_character"
            if not name.startswith(_MCP_MARK):
                raise ValueError("geo name must start with mcp_")
            existing = parent.node(name)
            return existing or parent.createNode("geo", name)
        return parent
    obj = hou.node("/obj")
    if obj is None:
        raise ValueError("/obj missing")
    geo_name = (parent_path or "").rstrip("/").split("/")[-1] or "mcp_character"
    if not geo_name.startswith(_MCP_MARK):
        raise ValueError("geo name must start with mcp_")
    return obj.createNode("geo", geo_name)


def import_fbx_character(file_path, parent_path="/obj/mcp_character",
                         name="fbx_character"):
    """kinefx::fbxcharacterimport under an mcp_* geo."""
    _require_mcp(parent_path)
    if not os.path.isfile(file_path):
        raise ValueError("FBX not found: %s" % file_path)
    parent = hou.node(parent_path)
    if parent is None:
        # /obj/mcp_character — create geo container
        obj = hou.node("/obj")
        if obj is None:
            raise ValueError("/obj missing")
        geo_name = parent_path.rstrip("/").split("/")[-1]
        if not geo_name.startswith(_MCP_MARK):
            raise ValueError("geo name must start with mcp_")
        parent = obj.createNode("geo", geo_name)
        parent_path = parent.path()
    if parent.type().name() == "geo" or parent.path() == "/obj":
        geo = parent if parent.type().name() == "geo" else _geo_container(parent.path(), name)
        if parent.path() == "/obj":
            _require_mcp(geo.path())
        node = geo.createNode("kinefx::fbxcharacterimport", name)
    else:
        node = parent.createNode("kinefx::fbxcharacterimport", name)
    parm = _set_file_parm(node, file_path)
    try:
        node.cook(force=False)
    except Exception as e:
        cook_error = str(e)
    else:
        cook_error = None
    joints = None
    try:
        joints = list_joints(node.path())
    except Exception:
        joints = None
    return {
        "path": node.path(),
        "parent": parent_path,
        "file": file_path,
        "file_parm": parm,
        "type": node.type().name(),
        "cook_error": cook_error,
        "joints": None if joints is None else {
            "count": joints["count"],
            "has_name": joints["has_name"],
            "has_transform": joints["has_transform"],
        },
    }


def import_fbx_animation(file_path, parent_path="/obj/mcp_character",
                         name="fbx_anim"):
    """kinefx::fbxanimimport — Mixamo clip onto a sibling of the character."""
    _require_mcp(parent_path)
    if not os.path.isfile(file_path):
        raise ValueError("FBX not found: %s" % file_path)
    parent = hou.node(parent_path)
    if parent is None:
        raise ValueError("Parent not found: %s (create the character geo first)" % parent_path)
    if parent.type().name() == "geo":
        node = parent.createNode("kinefx::fbxanimimport", name)
    else:
        node = parent.createNode("kinefx::fbxanimimport", name)
    parm = _set_file_parm(node, file_path)
    warnings = []
    try:
        node.cook(force=False)
        warnings = list(node.warnings() or [])
    except Exception as e:
        warnings = [str(e)]
    joints = None
    try:
        joints = list_joints(node.path())
    except Exception:
        joints = None
    return {
        "path": node.path(),
        "file": file_path,
        "file_parm": parm,
        "type": node.type().name(),
        "warnings": warnings,
        "joints": None if joints is None else {
            "count": joints["count"],
            "has_name": joints["has_name"],
        },
    }


def attach_kinefx_deform(parent_path="/obj/mcp_character", source="capybara",
                         clip="elbowdrop", rest_path=None, capture_path=None,
                         anim_path=None, name="jointdeform", proof=True,
                         map_joints=False):
    """Skin + capture pose + animated pose → kinefx::jointdeform.

    source='capybara': built-in testgeometry_capybara with motion-clip output
    (outputclip on) + kinefx::motionclipevaluate. Not Mixamo.
    source='nodes': wire rest_path / capture_path / anim_path.

    Display flag lands on the deform SOP. Playback range follows the clip.
    proof=True hashes deform geo at start and end frames (must differ).
    """
    geo = _ensure_mcp_geo(parent_path)
    parent_path = geo.path()
    warnings = []
    capy_path = None
    eval_path = None
    joint_map = None
    clip_token = _CAPY_CLIPS.get((clip or "").lower(), clip)

    if source in ("capybara", "capy"):
        capy = geo.node("capybara") or geo.createNode(
            "testgeometry_capybara", "capybara")
        capy_path = capy.path()
        if _set_parm(capy, _OUTPUTCLIP_PARMS, 1) is None:
            warnings.append("outputclip parm missing")
        if clip_token and _set_parm(capy, _CLIP_PARMS, clip_token) is None:
            warnings.append("clip parm missing (%s)" % clip_token)
        _set_parm(capy, ("applylocomotion",), 0)
        # Embedded shader without a GL light is a black flipbook.
        _set_parm(capy, ("addshader",), 0)
        _set_parm(capy, ("addnormalmap",), 0)
        _set_parm(capy, ("sss_enable",), 0)
        eval_node = geo.node("clip_eval") or geo.createNode(
            "kinefx::motionclipevaluate", "clip_eval")
        eval_node.setInput(0, capy, 2)
        eval_path = eval_node.path()
        rest_node, capture_node, anim_node = capy, capy, eval_node
        rest_out, capture_out, anim_out = 0, 1, 0
    elif source in ("nodes", "sop"):
        if not (rest_path and capture_path and anim_path):
            raise ValueError(
                "source='nodes' needs rest_path, capture_path, and anim_path")
        rest_node = hou.node(rest_path)
        capture_node = hou.node(capture_path)
        anim_node = hou.node(anim_path)
        if rest_node is None:
            raise ValueError("rest_path not found: %s" % rest_path)
        if capture_node is None:
            raise ValueError("capture_path not found: %s" % capture_path)
        if anim_node is None:
            raise ValueError("anim_path not found: %s" % anim_path)
        rest_out = capture_out = anim_out = 0
        if map_joints:
            joint_map = map_kinefx_joints(capture_path, anim_path)
            anim_node = _apply_name_map(geo, anim_node, joint_map["map"])
            warnings.append("mapped %d joints" % joint_map["count"])
    else:
        raise ValueError("source must be 'capybara' or 'nodes', got %r" % source)

    deform = geo.node(name) or geo.createNode("kinefx::jointdeform", name)
    deform.setInput(0, rest_node, rest_out)
    deform.setInput(1, capture_node, capture_out)
    deform.setInput(2, anim_node, anim_out)
    try:
        deform.setDisplayFlag(True)
        deform.setRenderFlag(True)
    except Exception as e:
        warnings.append("flags: %s" % e)
    try:
        geo.layoutChildren()
    except Exception:
        pass

    range_src = hou.node(eval_path) if eval_path else anim_node
    frame_range = _motionclip_range(range_src)
    try:
        hou.playbar.setFrameRange(frame_range[0], frame_range[1])
        hou.playbar.setPlaybackRange(frame_range[0], frame_range[1])
    except Exception as e:
        warnings.append("playbar: %s" % e)

    hashes = {}
    if proof:
        try:
            hou.setFrame(frame_range[0])
            hashes["start"] = pose_hash(deform.path())
            hou.setFrame(frame_range[1])
            hashes["end"] = pose_hash(deform.path())
            hashes["moved"] = hashes["start"]["hash"] != hashes["end"]["hash"]
            hou.setFrame(frame_range[0])
        except Exception as e:
            warnings.append("proof: %s" % e)
            hashes["moved"] = False

    cook_error = None
    try:
        deform.cook(force=False)
    except Exception as e:
        cook_error = str(e)

    return {
        "path": deform.path(),
        "parent": parent_path,
        "source": source,
        "clip": clip_token,
        "capy": capy_path,
        "eval": eval_path,
        "rest": rest_node.path(),
        "capture": capture_node.path(),
        "anim": anim_node.path(),
        "type": deform.type().name(),
        "range": frame_range,
        "hashes": hashes,
        "cook_error": cook_error,
        "warnings": warnings,
        "joint_map": None if joint_map is None else {
            "count": joint_map["count"],
            "map": joint_map["map"],
        },
    }
