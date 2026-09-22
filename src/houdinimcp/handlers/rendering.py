"""Rendering handlers (OpenGL, Karma, Mantra, flipbook)."""
import os
import tempfile
import traceback

import hou
from ..HoudiniMCPRender import render_single_view, render_quad_view, render_specific_camera


def _process_rendered_image(filepath, camera_path=None, view_name=None):
    """Return metadata for a rendered image file."""
    if not filepath or not os.path.exists(filepath):
        return {"status": "error", "message": f"Rendered file not found: {filepath}",
                "origin": "_process_rendered_image"}

    _, ext = os.path.splitext(filepath)
    fmt = ext[1:].lower() if ext else 'unknown'

    resolution = [0, 0]
    if camera_path:
        cam_node = hou.node(camera_path)
        if cam_node and cam_node.parm("resx") and cam_node.parm("resy"):
            resolution = [cam_node.parm("resx").eval(), cam_node.parm("resy").eval()]

    result_data = {
        "status": "success",
        "format": fmt,
        "resolution": resolution,
        "filepath": filepath,
    }
    if view_name:
        result_data["view_name"] = view_name
    return result_data


def handle_render_single_view(orthographic=False, rotation=(0, 90, 0),
                               render_path=None, render_engine="opengl",
                               karma_engine="cpu"):
    """Handles the 'render_single_view' command."""
    if not render_path:
        render_path = tempfile.gettempdir()
    try:
        if isinstance(rotation, list):
            rotation = tuple(rotation)
        filepath = render_single_view(
            orthographic=orthographic,
            rotation=rotation,
            render_path=render_path,
            render_engine=render_engine,
            karma_engine=karma_engine
        )
        return _process_rendered_image(filepath, "/obj/MCP_CAMERA")
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": f"Render Single View Failed: {str(e)}",
                "origin": "handle_render_single_view"}


def handle_render_quad_view(orthographic=True, render_path=None,
                             render_engine="opengl", karma_engine="cpu"):
    """Handles the 'render_quad_view' command."""
    if not render_path:
        render_path = tempfile.gettempdir()
    try:
        filepaths = render_quad_view(
            orthographic=orthographic,
            render_path=render_path,
            render_engine=render_engine,
            karma_engine=karma_engine
        )
        results = []
        camera_path = "/obj/MCP_CAMERA"
        for fp in filepaths:
            view_name = None
            try:
                filename = os.path.basename(fp)
                parts = filename.split('_')
                if len(parts) > 2:
                    view_name = parts[2]
            except Exception:
                pass
            results.append(_process_rendered_image(fp, camera_path, view_name))
        return {"status": "success", "results": results}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": f"Render Quad View Failed: {str(e)}",
                "origin": "handle_render_quad_view"}


def handle_render_specific_camera(camera_path, render_path=None,
                                   render_engine="opengl", karma_engine="cpu"):
    """Handles the 'render_specific_camera' command."""
    if not render_path:
        render_path = tempfile.gettempdir()
    if not camera_path or not hou.node(camera_path):
        return {"status": "error",
                "message": f"Camera path '{camera_path}' is invalid or node not found.",
                "origin": "handle_render_specific_camera"}
    try:
        filepath = render_specific_camera(
            camera_path=camera_path,
            render_path=render_path,
            render_engine=render_engine,
            karma_engine=karma_engine
        )
        return _process_rendered_image(filepath, camera_path)
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": f"Render Specific Camera Failed: {str(e)}",
                "origin": "handle_render_specific_camera"}


def list_render_nodes():
    """List all ROP (render) nodes in the scene."""
    out_node = hou.node("/out")
    if not out_node:
        return {"count": 0, "nodes": []}
    nodes = []
    for child in out_node.children():
        nodes.append({
            "name": child.name(),
            "path": child.path(),
            "type": child.type().name(),
        })
    return {"count": len(nodes), "nodes": nodes}


def get_render_settings(path):
    """Get render settings from a ROP node."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    settings = {}
    for parm_name in ["camera", "picture", "res_overridex", "res_overridey",
                       "trange", "f1", "f2", "f3"]:
        parm = node.parm(parm_name)
        if parm:
            settings[parm_name] = str(parm.eval())
    return {"path": path, "type": node.type().name(), "settings": settings}


def set_render_settings(path, settings):
    """Set render settings on a ROP node."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    changes = []
    for name, value in settings.items():
        parm = node.parm(name)
        if parm:
            parm.set(value)
            changes.append(name)
    return {"path": path, "changed": changes}


def create_render_node(render_type="opengl", name=None, parent_path="/out"):
    """Create a ROP node."""
    parent = hou.node(parent_path)
    if not parent:
        raise ValueError(f"Parent not found: {parent_path}")
    node = parent.createNode(render_type, node_name=name)
    return {"path": node.path(), "name": node.name(), "type": render_type}


def start_render(path, frame_range=None):
    """Start a render from a ROP node."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    if frame_range and len(frame_range) == 2:
        node.render(frame_range=(frame_range[0], frame_range[1]))
    else:
        node.render()
    return {"path": path, "rendering": True}


def get_render_progress(path):
    """Get render progress from a ROP node."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    return {
        "path": path,
        "is_cooking": node.isCooking() if hasattr(node, "isCooking") else False,
    }


def render_flipbook(frame_range=None, output=None, resolution=None):
    """Render a flipbook sequence from the viewport."""
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        raise RuntimeError("No scene viewer found for flipbook")
    settings = viewer.flipbookSettings().stash()
    if frame_range and len(frame_range) == 2:
        settings.frameRange((frame_range[0], frame_range[1]))
    if not output:
        output = os.path.join(tempfile.gettempdir(), "mcp_flipbook.$F4.jpg")
    settings.output(output)
    if resolution and len(resolution) == 2:
        settings.resolution((resolution[0], resolution[1]))
    viewer.flipbook(settings=settings)
    return {"flipbook": True, "output": output}
