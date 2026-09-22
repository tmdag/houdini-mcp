"""Rendering utilities: camera rig, bbox calculation, OpenGL/Karma/Mantra setup."""
import numpy as np
import math
import os
import tempfile

import hou


def find_displayed_geometry():
    """Find all displayed geometry nodes in the scene."""
    displayed_geo = []
    for node in hou.node("/obj").children():
        if node.type().name() in ["geo", "subnet"] and node.isDisplayFlagSet():
            displayed_geo.append(node)

        if node.type().name() in ("subnet", "gltf_hierarchy"):
            for child in node.allSubChildren():
                if child.type().category().name() == "Sop" and child.isDisplayFlagSet():
                    obj_parent = child.parent()
                    while obj_parent and obj_parent.type().category().name() != "Object":
                        obj_parent = obj_parent.parent()
                    if obj_parent and obj_parent not in displayed_geo:
                        displayed_geo.append(obj_parent)

    return displayed_geo


def calculate_bounding_box(nodes):
    """Calculate the collective bounding box of all given nodes."""
    if not nodes:
        return None

    min_bounds = np.array([float('inf'), float('inf'), float('inf')])
    max_bounds = np.array([float('-inf'), float('-inf'), float('-inf')])

    for node in nodes:
        try:
            display_node = node.displayNode()
            if display_node is None:
                continue

            geo = display_node.geometry()
            if geo is None:
                continue

            bbox = geo.boundingBox()
            if bbox is None:
                continue

            transform = node.worldTransform()
            for x in [bbox.minvec()[0], bbox.maxvec()[0]]:
                for y in [bbox.minvec()[1], bbox.maxvec()[1]]:
                    for z in [bbox.minvec()[2], bbox.maxvec()[2]]:
                        point = hou.Vector4(x, y, z, 1.0)
                        transformed_point = point * transform
                        min_bounds[0] = min(min_bounds[0], transformed_point[0])
                        min_bounds[1] = min(min_bounds[1], transformed_point[1])
                        min_bounds[2] = min(min_bounds[2], transformed_point[2])
                        max_bounds[0] = max(max_bounds[0], transformed_point[0])
                        max_bounds[1] = max(max_bounds[1], transformed_point[1])
                        max_bounds[2] = max(max_bounds[2], transformed_point[2])
        except Exception:
            continue

    if np.isinf(min_bounds).any() or np.isinf(max_bounds).any():
        return None

    center = [(min_bounds[0] + max_bounds[0]) / 2,
              (min_bounds[1] + max_bounds[1]) / 2,
              (min_bounds[2] + max_bounds[2]) / 2]

    return {'min': min_bounds.tolist(), 'max': max_bounds.tolist(), 'center': center}


def setup_camera_rig(bbox_center, orthographic=False):
    """Set up a null and camera rig at the given position."""
    null_name = "MCP_CAM_CENTER"
    cam_name = "MCP_CAMERA"

    null = hou.node("/obj/" + null_name)
    camera = hou.node("/obj/" + cam_name)

    if not null:
        null = hou.node("/obj").createNode("null", null_name)
        null.setPosition(hou.Vector2(0, 0))

    if not camera:
        camera = hou.node("/obj").createNode("cam", cam_name)
        camera.setPosition(hou.Vector2(3, 0))
        camera.setFirstInput(null)

    null.parmTuple("r").set((0, 0, 0))
    null.parmTuple("t").set(bbox_center)

    camera.parmTuple("t").set([0, 0, 5])
    camera.parm("resx").set(512)
    camera.parm("resy").set(512)
    camera.parm("aspect").set(1.0)
    camera.parm("projection").set(1 if orthographic else 0)

    return null


def rotate_camera_center(null_node, rotation=(0, 90, 0)):
    """Rotate the camera center null by the specified angles."""
    if not null_node:
        return
    current_rotation = null_node.parmTuple("r").eval()
    new_rotation = [
        current_rotation[0] + rotation[0],
        current_rotation[1] + rotation[1],
        current_rotation[2] + rotation[2],
    ]
    null_node.parmTuple("r").set(new_rotation)


def _compute_camera_params(camera):
    """Return (min_fov, aspect_ratio) from camera node."""
    aperture = camera.parm("aperture")
    if aperture:
        fov = aperture.eval()
        aspect_ratio = camera.parm("aspect").eval()
    else:
        resx = camera.parm("resx").eval()
        resy = camera.parm("resy").eval()
        aspect_ratio = float(resx) / float(resy)
        fov = 36.0
    focal = camera.parm("focal")
    focal_length = focal.eval() if focal else 30.0
    h_fov = 2 * math.atan((fov / 2) / focal_length)
    v_fov = 2 * math.atan(math.tan(h_fov / 2) / aspect_ratio)
    return min(h_fov, v_fov), aspect_ratio


def adjust_camera_to_fit_bbox(camera, bbox, padding_factor=1.1):
    """Adjust camera distance or ortho width to encompass the bounding box."""
    if not camera or not bbox:
        return

    is_ortho = camera.parm("projection").eval() == 1

    bbox_width = bbox['max'][0] - bbox['min'][0]
    bbox_height = bbox['max'][1] - bbox['min'][1]
    bbox_depth = bbox['max'][2] - bbox['min'][2]
    bbox_diagonal = math.sqrt(bbox_width**2 + bbox_height**2 + bbox_depth**2)
    bbox_view_diagonal = math.sqrt(bbox_width**2 + bbox_height**2)

    null_node = hou.node("/obj/MCP_CAM_CENTER")
    if null_node:
        null_r = hou.Vector3(null_node.parmTuple("r").eval())
        has_significant_rotation = any(abs(null_r[i] % 360) > 5 for i in range(3))
        if has_significant_rotation:
            controlling_dimension = bbox_view_diagonal * 1.2
            depth_for_clipping = bbox_diagonal / 2
        else:
            controlling_dimension = max(bbox_width, bbox_height)
            depth_for_clipping = bbox_depth
    else:
        controlling_dimension = bbox_view_diagonal
        depth_for_clipping = bbox_depth

    min_fov, _ = _compute_camera_params(camera)

    # distance = (size/2) / tan(FOV/2), plus depth for clipping
    required_distance = (controlling_dimension * padding_factor / 2) / math.tan(min_fov / 2)
    required_distance += depth_for_clipping
    required_distance = max(5.0, required_distance)

    camera.parmTuple("t").set([0, 0, required_distance])
    if is_ortho:
        camera.parm("orthowidth").set(controlling_dimension * padding_factor)


def setup_render_node(render_engine="opengl", karma_engine="cpu", render_path=None,
                      camera_path="/obj/MCP_CAMERA", view_name=None, rotation=None,
                      is_ortho=False):
    """Create/reuse a render node. Returns (render_node, filepath)."""
    if not render_path:
        render_path = tempfile.gettempdir()
    if not os.path.exists(render_path):
        os.makedirs(render_path)

    engine_lower = render_engine.lower()
    if engine_lower == "karma":
        render_node_name = f"MCP_{karma_engine.upper()}_KARMA"
        node_type = "karma"
    elif engine_lower == "mantra":
        render_node_name = "MCP_MANTRA"
        node_type = "ifd"
    else:
        render_node_name = "MCP_OGL_RENDER"
        node_type = "opengl"

    proj_type = "ortho" if is_ortho else "persp"
    if view_name:
        filename = f"{render_node_name}_{view_name}_{proj_type}.jpg"
    elif rotation:
        rot_str = f"rot_{int(rotation[0])}_{int(rotation[1])}_{int(rotation[2])}"
        filename = f"{render_node_name}_{proj_type}_{rot_str}.jpg"
    else:
        filename = f"{render_node_name}_{proj_type}.jpg"
    filepath = os.path.join(render_path, filename)

    render_node = hou.node("/out/" + render_node_name)
    if not render_node:
        render_node = hou.node("/out").createNode(node_type, render_node_name)
    if not render_node:
        return None, None

    camera = hou.node(camera_path)
    if not camera:
        return render_node, filepath

    resx = camera.parm("resx").eval()
    resy = camera.parm("resy").eval()

    if engine_lower == "opengl":
        if render_node.parm("camera"):
            render_node.parm("camera").set(camera_path)
        if render_node.parm("tres"):
            render_node.parm("tres").set(True)
            render_node.parm("res1").set(resx)
            render_node.parm("res2").set(resy)
        if render_node.parm("picture"):
            render_node.parm("picture").set(filepath)

    elif engine_lower == "karma":
        if render_node.parm("camera"):
            render_node.parm("camera").set(camera_path)
        if render_node.parm("engine"):
            render_node.parm("engine").set("xpu" if karma_engine.lower() == "gpu" else "cpu")
        elif render_node.parm("XPU"):
            render_node.parm("XPU").set(1 if karma_engine.lower() == "gpu" else 0)
        if render_node.parm("resolution1"):
            render_node.parm("resolution1").set(resx)
            render_node.parm("resolution2").set(resy)
        if render_node.parm("picture"):
            render_node.parm("picture").set(filepath)

    elif engine_lower == "mantra":
        if render_node.parm("camera"):
            render_node.parm("camera").set(camera_path)
        if render_node.parm("override_camerares"):
            render_node.parm("override_camerares").set(True)
            render_node.parm("res_fraction").set("specific")
            if render_node.parm("res_overridex"):
                render_node.parm("res_overridex").set(resx)
                render_node.parm("res_overridey").set(resy)
            elif render_node.parm("res_override_x"):
                render_node.parm("res_override_x").set(resx)
                render_node.parm("res_override_y").set(resy)
        if render_node.parm("vm_picture"):
            render_node.parm("vm_picture").set(filepath)

    if render_node.parm("trange"):
        render_node.parm("trange").set(0)

    return render_node, filepath


def render_single_view(orthographic=False, rotation=(0, 90, 0), render_path=None,
                       render_engine="opengl", karma_engine="cpu"):
    """Set up camera rig and render a single view with specified rotation."""
    displayed_geo = find_displayed_geometry()
    if not displayed_geo:
        return None

    bbox = calculate_bounding_box(displayed_geo)
    if not bbox:
        return None

    null = setup_camera_rig(bbox['center'], orthographic)
    rotate_camera_center(null, rotation)

    camera = hou.node("/obj/MCP_CAMERA")
    if not camera:
        return None
    adjust_camera_to_fit_bbox(camera, bbox)

    render_node, filepath = setup_render_node(
        render_engine=render_engine, karma_engine=karma_engine,
        render_path=render_path, camera_path="/obj/MCP_CAMERA",
        rotation=rotation, is_ortho=orthographic,
    )
    if not render_node:
        return None

    render_node.render()
    return filepath


def render_quad_view(orthographic=True, render_path=None, render_engine="opengl",
                     karma_engine="cpu"):
    """Render four standard views: Front, Left, Top, Perspective."""
    rendered_files = []
    views = [
        {"name": "Front", "rotation": (0, 0, 0), "ortho": orthographic},
        {"name": "Left", "rotation": (0, -90, 0), "ortho": orthographic},
        {"name": "Top", "rotation": (-90, 0, 0), "ortho": orthographic},
        {"name": "Perspective", "rotation": (-45, -45, 0), "ortho": orthographic},
    ]

    displayed_geo = find_displayed_geometry()
    if not displayed_geo:
        return rendered_files

    bbox = calculate_bounding_box(displayed_geo)
    if not bbox:
        return rendered_files

    for view in views:
        null = setup_camera_rig(bbox['center'], view['ortho'])
        rotate_camera_center(null, view['rotation'])

        camera = hou.node("/obj/MCP_CAMERA")
        if not camera:
            continue
        adjust_camera_to_fit_bbox(camera, bbox)

        render_node, filepath = setup_render_node(
            render_engine=render_engine, karma_engine=karma_engine,
            render_path=render_path, camera_path="/obj/MCP_CAMERA",
            view_name=view['name'].lower(), is_ortho=view['ortho'],
        )
        if not render_node:
            continue

        render_node.render()
        if filepath:
            rendered_files.append(filepath)

    return rendered_files


def render_specific_camera(camera_path, render_path=None, render_engine="opengl",
                           karma_engine="cpu"):
    """Render using a specific camera that already exists in the scene."""
    camera = hou.node(camera_path)
    if not camera:
        return None
    if camera.type().name() != "cam":
        return None

    is_ortho = camera.parm("projection").eval() == 1
    camera_parent = camera.parent()
    if camera_parent and camera_parent.type().name() == "null":
        rotation = camera_parent.parmTuple("r").eval()
    else:
        rotation = camera.parmTuple("r").eval()

    render_node, filepath = setup_render_node(
        render_engine=render_engine, karma_engine=karma_engine,
        render_path=render_path, camera_path=camera_path,
        view_name=camera.name(), is_ortho=is_ortho,
    )
    if not render_node:
        return None

    render_node.render()
    return filepath
