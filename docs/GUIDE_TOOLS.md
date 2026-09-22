# MCP Tool Reference

HoudiniMCP provides 41+ tools organized by category. All tools that interact with
Houdini require a running Houdini instance with the plugin loaded. Documentation
search tools work offline.

## How Tools Work

Each tool sends a JSON command over TCP to the Houdini plugin, which executes it
and returns a JSON response. Mutating commands (create, modify, delete) are wrapped
in Houdini undo groups so they can be undone with Ctrl+Z.

---

## Scene Management

### `ping`
Health check. Returns server status (alive, host, port, client connected). Also `stale` / `mtime` / `commands` for the in-process handler table vs prefs copy.

### `reload_plugin`
`importlib.reload` every `houdinimcp.handlers.*` module and rebind the TCP command table. Does **not** restart houdini-bin or the listener.

Inner loop: `install.py --houdini-version 22.0` then `reload_plugin`. If the key 404s, the next `ping` / command runs `_ensure_reload_hook` and patches the instance.

### `get_connection_status`
Returns connection details: whether connected, port, command count, timing info.

### `get_scene_info`
Returns scene summary: file path, current frame, FPS, frame range, and node counts
for /obj, /shop, /stage.

### `save_scene`
Save the current scene. Optionally pass `file_path` to save to a new location.

### `load_scene`
Load a .hip file. Pass `file_path` (e.g., `/path/to/scene.hip`).

### `set_frame`
Set the current frame in Houdini's playbar. Pass `frame` (float).

---

## Node Operations

### `create_node`
Create a new node. Parameters:
- `node_type` (required): e.g., "geo", "box", "sphere"
- `parent_path`: default "/obj"
- `name`: optional custom name

### `modify_node`
Modify an existing node. Parameters:
- `path` (required): node path
- `parameters`: dict of parm name → value
- `position`: [x, y] in network editor
- `name`: rename the node

### `delete_node`
Delete a node by its path.

### `get_node_info`
Returns detailed info: type, parameters (names + values), inputs, outputs,
flags, position, and error state.

### `connect_nodes`
Wire two nodes together. Parameters:
- `src_path`, `dst_path` (required)
- `dst_input_index`: default 0
- `src_output_index`: default 0

### `disconnect_node_input`
Disconnect a specific input on a node.

### `set_node_flags`
Set display, render, and/or bypass flags.

### `set_node_color`
Set a node's color as `[r, g, b]` (0-1 range).

### `layout_children`
Auto-layout child nodes in the network editor. Pass `node_path` (default "/obj").

### `find_error_nodes`
Recursively scan a hierarchy for nodes with cook errors or warnings.

---

## Code Execution

### `execute_houdini_code`
Execute arbitrary Python code in Houdini's environment. Parameters:
- `code` (required): Python source code string
- `allow_dangerous`: default False. When False, blocks patterns like `os.remove`,
  `subprocess`, `hou.exit`, etc.

Returns stdout and stderr from the code execution.

---

## Materials

### `set_material`
Create or apply a material. Parameters:
- `node_path` (required): OBJ node to apply material to
- `material_type`: default "principledshader"
- `name`: material name
- `parameters`: material parameter overrides

---

## Geometry

### `get_geo_summary`
Get geometry statistics for a SOP node: point/prim/vertex counts, bounding box
dimensions, and attribute names (point, prim, vertex, detail).

### `geo_export`
Export geometry to a file. Parameters:
- `node_path` (required)
- `format`: "obj", "gltf", "glb", "usd", "usda", "ply", "bgeo.sc"
- `output`: file path (auto-generated if not specified)

---

## Rendering

### `render_single_view`
Render a single viewport. Parameters:
- `orthographic`: default False
- `rotation`: [rx, ry, rz] default [0, 90, 0]
- `render_engine`: "opengl", "karma", or "mantra"
- `karma_engine`: "cpu" or "xpu"

### `render_quad_views`
Render 4 canonical orthographic views (front, right, top, perspective).

### `render_specific_camera`
Render from a specific camera node in the scene.

### `render_flipbook`
Render a flipbook sequence from the viewport. Parameters:
- `frame_range`: [start, end]
- `output`: file path with `$F4` for frame number
- `resolution`: [width, height]

---

## PDG/TOPs

### `pdg_cook`
Start cooking a TOP network (non-blocking).

### `pdg_status`
Get cook status: waiting, cooking, cooked, and failed work item counts.

### `pdg_workitems`
List work items with their state and output files. Optionally filter by state.

### `pdg_dirty`
Dirty work items for re-cooking. Pass `dirty_all=True` to dirty everything.

### `pdg_cancel`
Cancel a running PDG cook.

---

## USD/Solaris (LOP)

### `lop_stage_info`
Get USD stage summary from a LOP node: prim count, root prims, default prim,
layer count, time codes.

### `lop_prim_get`
Get details of a specific prim. Pass `include_attrs=True` for attribute values.

### `lop_prim_search`
Search for prims by pattern (e.g., `/**/*light*`). Optionally filter by type.

### `lop_layer_info`
Get the USD layer stack (identifiers and file paths).

### `lop_import`
Import a USD file via reference or sublayer.

---

## HDA Management

### `hda_list`
List available HDA definitions. Optionally filter by `category` (e.g., "Sop").

### `hda_get`
Detailed info about an HDA: label, library path, version, max inputs, sections.

### `hda_install`
Install an HDA file into the current session.

### `hda_create`
Create an HDA from an existing node. Parameters:
- `node_path`, `name`, `label`, `file_path` (all required)

---

## Batch Operations

### `batch`
Execute multiple operations atomically in a single undo group. Each operation is
`{"type": "command_name", "params": {...}}`.

---

## Event System

### `get_houdini_events`
Get pending events that occurred since the last poll. Returns:
`{count, events: [{type, timestamp, details}, ...]}`.

Event types: `scene_loaded`, `scene_saved`, `scene_cleared`, `node_created`,
`node_deleted`, `frame_changed`.

### `subscribe_houdini_events`
Filter which events to collect. Pass `types` as a list, or omit for all events.

---

## Viewport / Hydra (Solaris)

### `list_hydra_renderers`
Hydra delegates on the LOP Scene Viewer (`Houdini VK`, `Karma CPU`, `Karma XPU`, `Storm`) plus `current` and `paused`.

### `set_hydra_renderer`
Switch the LOP viewport delegate. Aliases: `xpu`, `cpu`, `vk`, `storm`, or the exact name.

Does **not** restart or sleep. XPU pixels converge asynchronously — poll `list_hydra_renderers`, then `capture_screenshot`.

### `restart_renderer`
Rebuild the active delegate from scratch. Can stall the UI/MCP thread. Avoid unless the renderer is wedged.

### `set_renderer_paused`
Pause or resume the active LOP Hydra delegate.

### `set_hydra_display`
USD purpose vis for the current delegate: `proxy`, `guide`, `render`, `materials`, `procedurals`.

### `set_viewport_camera`
Look through an OBJ camera **or** a USD prim (`/world/cam`). LOP Camera nodes are not OBJ cameras.

### `get_viewport_info`
Camera, shading, Hydra current/available, `hscript_path` (`Solaris.pane1.solaris.persp1` for LOPs — not `.world`).

### `list_file_parms`
File/path parms on a node. Alembic, USD, texture, VDB, FBX. Not a new importer.

### `set_file`
Set the file parm (`create_node` + `set_file`). Pass `parm_name` if there are several.

### `list_joints`
KineFX skeleton on a SOP: point `name` + `P`. Character inspect (Mixamo, capybara, whatever has a skeleton).

### `import_fbx_character`
`kinefx::fbxcharacterimport` under an `mcp_*` geo. Rest pose / skinned mesh.

### `import_fbx_animation`
`kinefx::fbxanimimport` — Mixamo clip. Parent geo must exist (`/obj/mcp_character`).

### `attach_kinefx_deform`
Skin + capture pose + animated pose → `kinefx::jointdeform` under `mcp_*`. `source=capybara` uses `testgeometry_capybara` with `outputclip` + `kinefx::motionclipevaluate` (HDA output 0 is rest skin and does not animate; `addshader` is forced off). `source=nodes` + `map_joints=true` remaps Mixamo-like clip names. `proof=True` hashes deform geo at clip start vs end.

### `map_kinefx_joints`
Map clip skeleton `name` attribs onto a rest skeleton. `mixamorig:Hips` → `hips`. Unmapped clip names raise.

### `pose_hash`
MD5 of a SOP's point positions. Clip proof: two frames must differ.

### `lookdev_dome` / `lookdev_preview_surface` / `lookdev_display_color` / `lookdev_camera`
Solaris lookdev under `mcp_*`. Dome light, USD Preview Surface + assign, mesh displayColor, look-at camera from a prim bbox. Look through the USD prim, not the LOP node.

### `frame_usd_prim`
Frame the LOP viewer on a USD prim bbox. Not OBJ `visibleObjects`.

### `set_karma_quality`
Karma samples / preview / pause. H22 SceneViewer has no pixel-sample HOM — reports `unavailable` and sets LOP `karmarendersettings` when `lop_path` is given. `pause_honored` is the pause truth.

### `capture_screenshot`
Scene Viewer flipbook **snapshot** (~150ms) of whatever the current Hydra delegate is showing. **Not a converged husk / Karma beauty.** Caps progressive Hydra (Karma XPU) so the MCP QTimer is not stalled. Restores `isRendererPaused` afterwards.

The MCP bridge returns **JSON metadata plus an in-band image** (MCP `ImageContent`) so the model can see the pixels without a second filesystem tool. Metadata still includes `filepath`, `hydra_renderer`, `camera_path`, `paused`, `snapshot`. Files larger than 4MB stay path-only.

---

## Documentation Search (offline)

### `search_docs`
BM25 search across Houdini documentation. Parameters:
- `query` (required): search text
- `top_k`: number of results (default 5)

Returns ranked results with path, title, preview (500 chars), and relevance score.

### `get_doc`
Read the full content of a documentation page. Pass `path` as returned by
`search_docs`.

These tools work without a Houdini connection. Requires running
`python scripts/fetch_houdini_docs.py` first.
