"""Reload handler modules without restarting houdini-bin.

Prefs copy is not the running process. `_get_handlers` used to close over
function objects imported at process start, so new keys 404'd until a
restart. bind_handlers() late-imports; reload_plugin() importlib.reload's
every handlers.* module and rebinds the live server's _get_handlers
and execute_command (quiet capture-guard). Does not reload
houdinimcp.server (QTimer is bound to those methods).
Does not stop/start the TCP listener.
"""
import importlib
import os
import pkgutil
import sys
import traceback

import hou

import houdinimcp.handlers as handlers_pkg


def _handler_modnames():
    names = []
    for info in pkgutil.iter_modules(handlers_pkg.__path__, handlers_pkg.__name__ + "."):
        if info.name.endswith(".__init__"):
            continue
        names.append(info.name)
    names.sort()
    # Reload this module last so bind_handlers/reload_plugin stay consistent.
    here = __name__
    if here in names:
        names.remove(here)
        names.append(here)
    return names


def handler_files():
    root = os.path.dirname(os.path.abspath(handlers_pkg.__file__))
    files = [
        os.path.join(root, name)
        for name in os.listdir(root)
        if name.endswith(".py")
    ]
    return files


def disk_mtime():
    files = handler_files()
    if not files:
        return 0.0
    return max(os.path.getmtime(f) for f in files)


def plugin_status():
    disk = disk_mtime()
    loaded = getattr(hou.session, "houdinimcp_handlers_mtime", None)
    stale = False
    if loaded is not None:
        try:
            stale = float(disk) > float(loaded) + 0.05
        except (TypeError, ValueError):
            stale = True
    return {
        "mtime": disk,
        "loaded_mtime": loaded,
        "stale": stale,
        "files": len(handler_files()),
    }


def _mark_loaded():
    try:
        hou.session.houdinimcp_handlers_mtime = disk_mtime()
    except Exception:
        pass


_NOISE_SNIPPETS = (
    "Connected to client:",
    "Client disconnected",
    "Executing handler for",
    "Handler execution complete for",
    "Houdini MCP: additional client",
)
_VERBOSE_LOG_VALUES = ("verbose", "debug", "1", "true", "yes", "on")
_QUIET_LOG_VALUES = ("quiet", "warn", "warning", "0", "false", "no", "off")


def log_level():
    """quiet (default) or verbose. Session overrides env."""
    try:
        v = getattr(hou.session, "houdinimcp_log", None)
        if v:
            v = str(v).strip().lower()
            if v in _VERBOSE_LOG_VALUES:
                return "verbose"
            if v in _QUIET_LOG_VALUES:
                return "quiet"
    except Exception:
        pass
    env = os.environ.get("HOUDINIMCP_LOG", "").strip().lower()
    if env in _VERBOSE_LOG_VALUES:
        return "verbose"
    return "quiet"


def is_session_noise(text):
    if not text:
        return False
    return any(s in text for s in _NOISE_SNIPPETS)


def _filtered_server_print(*args, **kwargs):
    text = " ".join(str(a) for a in args)
    if is_session_noise(text) and log_level() != "verbose":
        return
    stream = kwargs.get("file") or sys.stderr
    end = kwargs.get("end", "\n")
    try:
        stream.write(text + end)
    except Exception:
        pass


def hush_server_prints():
    """Swallow per-command prints on the already-imported server module.

    Live houdini-bin cannot reload houdinimcp.server (QTimer). Injecting
    `print` into that module's globals hushes the old bytecode.
    """
    import houdinimcp.server as srv
    srv.print = _filtered_server_print
    srv._mcp_print_filtered = True
    return {"filtered": True, "log": log_level()}


def set_log_level(level="quiet"):
    """quiet hides connect/execute/disconnect in the Houdini Python shell."""
    raw = str(level or "quiet").strip().lower()
    if raw in _VERBOSE_LOG_VALUES:
        raw = "verbose"
    elif raw in _QUIET_LOG_VALUES:
        raw = "quiet"
    if raw not in ("quiet", "verbose"):
        raise ValueError("level must be quiet or verbose, got %r" % level)
    hou.session.houdinimcp_log = raw
    hush_server_prints()
    return {"log": raw}


def bind_handlers(server):
    """Build the command dict from *current* handler module attributes."""
    from houdinimcp.handlers.scene import (
        get_scene_info, save_scene, load_scene, set_frame, get_asset_lib_status,
    )
    from houdinimcp.handlers.nodes import (
        create_node, modify_node, delete_node, get_node_info, set_material,
        connect_nodes, disconnect_node_input, set_node_flags,
        layout_children, set_node_color, set_expression, find_error_nodes,
        copy_node, move_node, rename_node, list_children, find_nodes,
        list_node_types, connect_nodes_batch, reorder_inputs,
    )
    from houdinimcp.handlers.context import (
        get_network_overview, get_cook_chain, explain_node, get_scene_summary,
        get_selection, set_selection,
    )
    from houdinimcp.handlers.parameters import (
        get_parameter, set_parameter, set_parameters, get_parameter_schema,
        get_expression, revert_parameter, link_parameters, lock_parameter,
        create_spare_parameter, create_spare_parameters,
        list_file_parms, set_file,
    )
    from houdinimcp.handlers.animation import (
        set_keyframe, set_keyframes, delete_keyframe, get_keyframes,
        get_frame, set_frame_range, set_playback_range, playbar_control,
    )
    from houdinimcp.handlers.vex import (
        create_wrangle, set_wrangle_code, get_wrangle_code,
        create_vex_expression, validate_vex,
    )
    from houdinimcp.handlers.materials import (
        list_materials, get_material_info, create_material_network,
        assign_material, list_material_types,
    )
    from houdinimcp.handlers.code import (
        execute_code, execute_hscript, evaluate_expression, get_env_variable,
        get_last_log,
    )
    from houdinimcp.handlers.geometry import (
        get_geo_summary, geo_export, get_points, get_prims, get_attrib_values,
        set_detail_attrib, get_groups, get_group_members, get_bounding_box,
        get_prim_intrinsics, find_nearest_point,
    )
    from houdinimcp.handlers.pdg import (
        pdg_cook, pdg_status, pdg_workitems, pdg_dirty, pdg_cancel,
    )
    from houdinimcp.handlers.lop import (
        lop_stage_info, lop_prim_get, lop_prim_search, lop_layer_info, lop_import,
        list_usd_prims, get_usd_attribute, set_usd_attribute, get_usd_prim_stats,
        get_last_modified_prims, create_lop_node, get_usd_composition,
        get_usd_variants, inspect_usd_layer, list_lights,
        usd_prim_bbox, lookdev_dome, lookdev_preview_surface,
        lookdev_display_color, lookdev_camera, set_karma_samples,
    )
    from houdinimcp.handlers.workflow import (
        setup_pyro_sim, setup_rbd_sim, setup_flip_sim, setup_vellum_sim,
        create_material_workflow, assign_material_workflow, build_sop_chain,
        setup_render,
    )
    from houdinimcp.handlers.cops import (
        get_cop_info, get_cop_geometry, get_cop_layer, create_cop_node,
        set_cop_flags, list_cop_node_types, get_cop_vdb,
    )
    from houdinimcp.handlers.chops import (
        get_chop_data, create_chop_node, list_chop_channels, export_chop_to_parm,
    )
    from houdinimcp.handlers.takes import (
        list_takes, get_current_take, set_current_take, create_take,
    )
    from houdinimcp.handlers.cache import (
        list_caches, get_cache_status, clear_cache, write_cache,
    )
    from houdinimcp.handlers.hda import (
        hda_list, hda_get, hda_install, hda_create,
        uninstall_hda, reload_hda, update_hda,
        get_hda_sections, get_hda_section_content, set_hda_section_content,
    )
    from houdinimcp.handlers.dops import (
        get_simulation_info, list_dop_objects, get_dop_object, get_dop_field,
        get_dop_relationships, step_simulation, reset_simulation,
        get_sim_memory_usage,
    )
    from houdinimcp.handlers.kinefx import (
        list_joints, import_fbx_character, import_fbx_animation,
        attach_kinefx_deform, pose_hash, map_kinefx_joints,
    )
    from houdinimcp.handlers.viewport import (
        list_panes, get_viewport_info, set_viewport_camera, set_viewport_display,
        set_viewport_renderer, frame_selection, frame_all, frame_bbox, set_viewport_direction,
        capture_screenshot, set_current_network,
        list_hydra_renderers, set_hydra_renderer, set_renderer_paused,
        restart_renderer, set_hydra_display, set_karma_quality, frame_usd_prim,
    )
    from houdinimcp.handlers.rendering import (
        handle_render_single_view, handle_render_quad_view,
        handle_render_specific_camera, render_flipbook,
        list_render_nodes, get_render_settings, set_render_settings,
        create_render_node, start_render, get_render_progress,
    )

    hush_server_prints()
    handlers = {
        "ping": server.ping,
        "reload_plugin": reload_plugin,
        "set_log_level": set_log_level,
        "get_scene_info": get_scene_info,
        "create_node": create_node,
        "modify_node": modify_node,
        "delete_node": delete_node,
        "get_node_info": get_node_info,
        "execute_code": execute_code,
        "get_last_log": get_last_log,
        "set_material": set_material,
        "get_asset_lib_status": get_asset_lib_status,
        "connect_nodes": connect_nodes,
        "disconnect_node_input": disconnect_node_input,
        "set_node_flags": set_node_flags,
        "save_scene": save_scene,
        "load_scene": load_scene,
        "set_expression": set_expression,
        "set_frame": set_frame,
        "get_geo_summary": get_geo_summary,
        "geo_export": geo_export,
        "layout_children": layout_children,
        "set_node_color": set_node_color,
        "find_error_nodes": find_error_nodes,
        "pdg_cook": pdg_cook,
        "pdg_status": pdg_status,
        "pdg_workitems": pdg_workitems,
        "pdg_dirty": pdg_dirty,
        "pdg_cancel": pdg_cancel,
        "lop_stage_info": lop_stage_info,
        "lop_prim_get": lop_prim_get,
        "lop_prim_search": lop_prim_search,
        "lop_layer_info": lop_layer_info,
        "lop_import": lop_import,
        "hda_list": hda_list,
        "hda_get": hda_get,
        "hda_install": hda_install,
        "hda_create": hda_create,
        "batch": server.batch,
        "get_pending_events": server.get_pending_events,
        "subscribe_events": server.subscribe_events,
        "render_single_view": handle_render_single_view,
        "render_quad_view": handle_render_quad_view,
        "render_specific_camera": handle_render_specific_camera,
        "render_flipbook": render_flipbook,
        "get_network_overview": get_network_overview,
        "get_cook_chain": get_cook_chain,
        "explain_node": explain_node,
        "get_scene_summary": get_scene_summary,
        "get_selection": get_selection,
        "set_selection": set_selection,
        "get_parameter": get_parameter,
        "set_parameter": set_parameter,
        "set_parameters": set_parameters,
        "list_file_parms": list_file_parms,
        "set_file": set_file,
        "get_parameter_schema": get_parameter_schema,
        "get_expression": get_expression,
        "revert_parameter": revert_parameter,
        "link_parameters": link_parameters,
        "lock_parameter": lock_parameter,
        "create_spare_parameter": create_spare_parameter,
        "create_spare_parameters": create_spare_parameters,
        "copy_node": copy_node,
        "move_node": move_node,
        "rename_node": rename_node,
        "list_children": list_children,
        "find_nodes": find_nodes,
        "list_node_types": list_node_types,
        "connect_nodes_batch": connect_nodes_batch,
        "reorder_inputs": reorder_inputs,
        "get_points": get_points,
        "get_prims": get_prims,
        "get_attrib_values": get_attrib_values,
        "set_detail_attrib": set_detail_attrib,
        "get_groups": get_groups,
        "get_group_members": get_group_members,
        "get_bounding_box": get_bounding_box,
        "get_prim_intrinsics": get_prim_intrinsics,
        "find_nearest_point": find_nearest_point,
        "execute_hscript": execute_hscript,
        "evaluate_expression": evaluate_expression,
        "get_env_variable": get_env_variable,
        "set_keyframe": set_keyframe,
        "set_keyframes": set_keyframes,
        "delete_keyframe": delete_keyframe,
        "get_keyframes": get_keyframes,
        "get_frame": get_frame,
        "set_frame_range": set_frame_range,
        "set_playback_range": set_playback_range,
        "playbar_control": playbar_control,
        "create_wrangle": create_wrangle,
        "set_wrangle_code": set_wrangle_code,
        "get_wrangle_code": get_wrangle_code,
        "create_vex_expression": create_vex_expression,
        "validate_vex": validate_vex,
        "list_materials": list_materials,
        "get_material_info": get_material_info,
        "create_material_network": create_material_network,
        "assign_material": assign_material,
        "list_material_types": list_material_types,
        "get_simulation_info": get_simulation_info,
        "list_dop_objects": list_dop_objects,
        "get_dop_object": get_dop_object,
        "get_dop_field": get_dop_field,
        "get_dop_relationships": get_dop_relationships,
        "step_simulation": step_simulation,
        "reset_simulation": reset_simulation,
        "get_sim_memory_usage": get_sim_memory_usage,
        "list_panes": list_panes,
        "get_viewport_info": get_viewport_info,
        "set_viewport_camera": set_viewport_camera,
        "set_viewport_display": set_viewport_display,
        "set_viewport_renderer": set_viewport_renderer,
        "list_hydra_renderers": list_hydra_renderers,
        "set_hydra_renderer": set_hydra_renderer,
        "set_renderer_paused": set_renderer_paused,
        "restart_renderer": restart_renderer,
        "set_hydra_display": set_hydra_display,
        "frame_selection": frame_selection,
        "frame_all": frame_all,
        "frame_bbox": frame_bbox,
        "set_viewport_direction": set_viewport_direction,
        "capture_screenshot": capture_screenshot,
        "set_current_network": set_current_network,
        "list_render_nodes": list_render_nodes,
        "get_render_settings": get_render_settings,
        "set_render_settings": set_render_settings,
        "create_render_node": create_render_node,
        "start_render": start_render,
        "get_render_progress": get_render_progress,
        "get_cop_info": get_cop_info,
        "get_cop_geometry": get_cop_geometry,
        "get_cop_layer": get_cop_layer,
        "create_cop_node": create_cop_node,
        "set_cop_flags": set_cop_flags,
        "list_cop_node_types": list_cop_node_types,
        "get_cop_vdb": get_cop_vdb,
        "get_chop_data": get_chop_data,
        "create_chop_node": create_chop_node,
        "list_chop_channels": list_chop_channels,
        "export_chop_to_parm": export_chop_to_parm,
        "list_takes": list_takes,
        "get_current_take": get_current_take,
        "set_current_take": set_current_take,
        "create_take": create_take,
        "list_caches": list_caches,
        "get_cache_status": get_cache_status,
        "clear_cache": clear_cache,
        "write_cache": write_cache,
        "uninstall_hda": uninstall_hda,
        "reload_hda": reload_hda,
        "update_hda": update_hda,
        "get_hda_sections": get_hda_sections,
        "get_hda_section_content": get_hda_section_content,
        "set_hda_section_content": set_hda_section_content,
        "list_usd_prims": list_usd_prims,
        "get_usd_attribute": get_usd_attribute,
        "set_usd_attribute": set_usd_attribute,
        "get_usd_prim_stats": get_usd_prim_stats,
        "get_last_modified_prims": get_last_modified_prims,
        "create_lop_node": create_lop_node,
        "get_usd_composition": get_usd_composition,
        "get_usd_variants": get_usd_variants,
        "inspect_usd_layer": inspect_usd_layer,
        "list_lights": list_lights,
        "setup_pyro_sim": setup_pyro_sim,
        "setup_rbd_sim": setup_rbd_sim,
        "setup_flip_sim": setup_flip_sim,
        "setup_vellum_sim": setup_vellum_sim,
        "create_material_workflow": create_material_workflow,
        "assign_material_workflow": assign_material_workflow,
        "build_sop_chain": build_sop_chain,
        "setup_render": setup_render,
        "list_joints": list_joints,
        "import_fbx_character": import_fbx_character,
        "import_fbx_animation": import_fbx_animation,
        "attach_kinefx_deform": attach_kinefx_deform,
        "pose_hash": pose_hash,
        "map_kinefx_joints": map_kinefx_joints,
        "usd_prim_bbox": usd_prim_bbox,
        "lookdev_dome": lookdev_dome,
        "lookdev_preview_surface": lookdev_preview_surface,
        "lookdev_display_color": lookdev_display_color,
        "lookdev_camera": lookdev_camera,
        "set_karma_samples": set_karma_samples,
        "set_karma_quality": set_karma_quality,
        "frame_usd_prim": frame_usd_prim,
    }
    if getattr(hou.session, "houdinimcp_use_assetlib", False):
        handlers.update({
            "get_asset_categories": server.get_asset_categories,
            "search_assets": server.search_assets,
            "import_asset": server.import_asset,
        })
    return handlers


def _rebind_server_module():
    """Copy public callables from handler modules onto houdinimcp.server."""
    import houdinimcp.server as srv
    rebound = []
    for name in _handler_modnames():
        mod = sys.modules.get(name) or importlib.import_module(name)
        for attr, val in vars(mod).items():
            if attr.startswith("_") or not callable(val):
                continue
            setattr(srv, attr, val)
            rebound.append("%s.%s" % (name.rsplit(".", 1)[-1], attr))
    try:
        from houdinimcp.handlers.code import DANGEROUS_PATTERNS
        srv.DANGEROUS_PATTERNS = DANGEROUS_PATTERNS
        srv.HoudiniMCPServer.DANGEROUS_PATTERNS = DANGEROUS_PATTERNS
    except Exception:
        pass
    return rebound


def is_quiet_command_error(exc):
    """Expected agent-facing failures. No Houdini console traceback."""
    return str(exc).startswith("capture refused")


def _error_payload(exc):
    from houdinimcp.server import _say
    tb = traceback.format_exc()
    quiet = is_quiet_command_error(exc)
    if not quiet:
        _say("Error executing command: %s" % exc, error=True)
        _say(tb, error=True)
    payload = {
        "status": "error",
        "message": str(exc),
        "traceback": "" if quiet else tb,
    }
    completed = getattr(exc, "completed", None)
    if completed is not None:
        # BatchError: say what already landed so the caller does not retry
        # the whole batch and duplicate the finished half.
        payload["completed"] = completed
        payload["completed_count"] = len(completed)
        payload["failed_index"] = getattr(exc, "index", None)
        payload["failed_type"] = getattr(exc, "cmd_type", None)
        payload["rolled_back"] = False
    try:
        hou.session.houdinimcp_last = payload
    except Exception:
        pass
    return payload


def dispatch_command(inst, command):
    """execute_command body. Patchable onto a live instance without reloading server.py."""
    try:
        inst._ensure_reload_hook()
    except Exception:
        pass
    try:
        cmd_type = command.get("type", "")
        mutating = getattr(inst, "MUTATING_COMMANDS", ())
        if cmd_type in mutating:
            with hou.undos.group("MCP: %s" % cmd_type):
                return inst._execute_command_internal(command)
        return inst._execute_command_internal(command)
    except Exception as e:
        return _error_payload(e)


def _patch_instance(inst):
    """Point the live server at bind_handlers + quiet execute_command.

    Does not touch its QTimer. Does not reload houdinimcp.server.
    """
    def _get_handlers(self):
        from houdinimcp.handlers.plugin import bind_handlers as bind
        return bind(self)

    def execute_command(self, command):
        from houdinimcp.handlers.plugin import dispatch_command as dispatch
        return dispatch(self, command)

    inst._get_handlers = _get_handlers.__get__(inst, type(inst))
    inst.execute_command = execute_command.__get__(inst, type(inst))


def reload_plugin():
    """importlib.reload handlers.* and rebind the live command table.

    Safe during a lookdev session. Does not restart houdini-bin or the
    TCP listener. New command *keys* appear because bind_handlers is
    re-imported after this module is reloaded.
    """
    reloaded = []
    errors = []
    for name in _handler_modnames():
        try:
            mod = sys.modules.get(name)
            if mod is None:
                mod = importlib.import_module(name)
            else:
                importlib.reload(mod)
            reloaded.append(name)
        except Exception as e:
            errors.append("%s: %s" % (name, e))
    rebound = _rebind_server_module()
    inst = getattr(hou.session, "houdinimcp_server", None)
    patched = False
    commands = []
    if inst is not None:
        _patch_instance(inst)
        patched = True
        try:
            commands = sorted(inst._get_handlers())
        except Exception as e:
            errors.append("bind: %s" % e)
    _mark_loaded()
    status = plugin_status()
    return {
        "reloaded": reloaded,
        "rebound": len(rebound),
        "patched_instance": patched,
        "execute_command_patched": bool(
            patched and getattr(inst, "execute_command", None)
        ),
        "commands": commands,
        "command_count": len(commands),
        "errors": errors,
        "stale": status.get("stale"),
        "mtime": status.get("mtime"),
        "qtimer_untouched": True,
    }


def bootstrap_reload():
    """execute_code entry: patch this process, then reload.

    Use when TCP `reload_plugin` 404s (command table from process start).
    """
    inst = getattr(hou.session, "houdinimcp_server", None)
    if inst is None:
        raise RuntimeError("Houdini MCP server is not running")
    _patch_instance(inst)
    return reload_plugin()
