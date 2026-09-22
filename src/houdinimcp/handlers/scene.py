"""Scene management handlers."""
import os
import traceback

import hou


def get_asset_lib_status():
    """Checks if the user toggled asset library usage in hou.session."""
    use_assetlib = getattr(hou.session, "houdinimcp_use_assetlib", False)
    msg = ("Asset library usage is enabled."
           if use_assetlib
           else "Asset library usage is disabled.")
    return {"enabled": use_assetlib, "message": msg}


def get_scene_info():
    """Returns basic info about the current .hip file and a few top-level nodes."""
    try:
        hip_file = hou.hipFile.name()
        scene_info = {
            "name": os.path.basename(hip_file) if hip_file else "Untitled",
            "filepath": hip_file or "",
            "node_count": len(hou.node("/").allSubChildren()),
            "nodes": [],
            "fps": hou.fps(),
            "start_frame": hou.playbar.frameRange()[0],
            "end_frame": hou.playbar.frameRange()[1],
        }

        root = hou.node("/")
        contexts = ["obj", "shop", "out", "ch", "vex", "stage"]
        top_nodes = []

        for ctx_name in contexts:
            ctx_node = root.node(ctx_name)
            if ctx_node:
                children = ctx_node.children()
                for node in children:
                    if len(top_nodes) >= 10:
                        break
                    top_nodes.append({
                        "name": node.name(),
                        "path": node.path(),
                        "type": node.type().name(),
                        "category": ctx_name,
                    })
                if len(top_nodes) >= 10:
                    break

        scene_info["nodes"] = top_nodes
        return scene_info

    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def _expand(path):
    """Expand a path the way Houdini does.

    os.path.expandvars only knows the process environment, so $HIP and $JOB
    pass through unexpanded and $OS silently becomes the operating system
    rather than Houdini's operator name. hou.text.expandString is the
    expander that knows Houdini's variables.
    """
    text = str(path).strip()
    try:
        text = hou.text.expandString(text)
    except Exception:
        text = os.path.expandvars(text)
    return os.path.expanduser(text)


def save_scene(file_path=None):
    """Save the current scene, optionally to a new path."""
    if file_path and str(file_path).strip():
        # hou.hipFile.save() creates intermediate directories itself, so
        # refusing a missing parent rejected paths Houdini would have made.
        hou.hipFile.save(_expand(file_path))
    else:
        hou.hipFile.save()
    return {"saved": True, "file": hou.hipFile.path()}


def load_scene(file_path):
    """Load a .hip file.

    Validates before handing the path to Houdini: an empty or missing path
    surfaced as "file_name cannot be empty" or a bare OperationFailed, which
    says nothing about which argument was wrong.
    """
    if not file_path or not str(file_path).strip():
        raise ValueError(
            "load_scene needs file_path, e.g. "
            "load_scene(file_path='/path/to/scene.hip')"
        )
    path = _expand(file_path)
    if not os.path.isfile(path):
        raise ValueError("Scene file not found: %s" % path)
    hou.hipFile.load(path)
    return {"loaded": True, "file": hou.hipFile.path()}


def set_frame(frame):
    """Set the current frame in Houdini's playbar."""
    hou.setFrame(frame)
    return {"frame": frame}
