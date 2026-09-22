# Agent contract (H22)

You are driving a **live Houdini 22** session through houdini-mcp.

## Loop

1. Inspect (`get_scene_info`, `list_children`, `lop_stage_info`, `get_parameter_schema`)
2. Mutate (`create_node`, `set_parameters` / `set_file`, LOP tools)
3. Cook — read `cook` / `errors` on the result
4. If `execute_code` was used, read `executed`, `error`, `traceback`, `stdout`
5. Picture: `capture_screenshot` source=`viewport` (flipbook). The tool returns the pixels in-band plus a path. Do not invent `saveAsImage`.

## Do not

- Call `hou.ui.desktops()` or `curDesktop()` from `execute_code`
- `setRenderFlag` on LOP nodes
- Assume OBJ camera APIs on `/stage`
- Point package JSON `path` at this Python package (pollutes `HOUDINI_PATH`)
- Talk to a production-tracking / asset-management API from this server

## Solaris cameras

`set_viewport_camera("/world/cam")` — USD prim string. LOP Camera nodes are not OBJ cameras; `setCamera(lop_node, prim)` fails. Switch desk with hscript `desk set Solaris` if the Scene Viewer is still OBJ. Hscript viewport id is `Solaris.pane1.solaris.persp1`, not `.world`.

## Hydra / XPU

- `list_hydra_renderers` / `set_hydra_renderer("xpu"|"cpu"|"vk"|"storm")`
- `set_renderer_paused`, `set_hydra_display` (proxy/guide/render purposes)
- Do **not** `restartRenderer` + sleep + viewwrite in one `execute_code` — stalls the MCP QTimer
- XPU pixels converge asynchronously. Poll `current`, then `capture_screenshot`
- `capture_screenshot` is a **snapshot** (~150ms frame time limit). It does not wait for XPU to finish, and it restores renderer pause state
- `restart_renderer` exists but can stall; avoid unless the delegate is wedged

## Plugin reload

Prefs copy is not the running process. Inner loop while H22 stays up:

1. `python scripts/install.py --houdini-version 22.0`
2. `reload_plugin` — importlib.reload handlers, rebind the command table **and** `execute_command` (quiet `capture refused`). Does **not** restart houdini-bin or the QTimer.
3. `ping` reports `stale` when handler files on disk are newer than what this process loaded. A missing `reload_plugin` key is patched on the next command (`_ensure_reload_hook`).

Do not `importlib.reload(houdinimcp.server)` — that is bound to the TCP QTimer.

Keep **one TCP session**. Do not reconnect per tool. The Houdini Python shell is **quiet** by default (`set_log_level("verbose")` to see connect/execute/disconnect).

Grok stdio command is **venv python + `houdini_mcp_server.py`**, not `uv run`. Isolate is OBJ-level (`/obj/geo`); SOP paths are rewritten. `grid=false` kills the perspective reference plane. Use `frame_bbox`, not `frame_all`, when isolate emptied the scene. Capture of an empty/grid-only view errors.

`start_server()` must be listening (`getsockname`) before it claims success. EADDRINUSE is a Houdini error popup, not "already running." Do not call `start_server()` on this live H22 just to poke it.

## Live smoke

`HOUDINIMCP_LIVE=1 pytest tests/test_live_hydra_smoke.py` — TCP to this houdini-bin. CI must not set the env.

## Files (alembic, usd, texture, vdb, fbx)

Do **not** add `import_alembic` / `import_volume` / `load_texture`. `create_node` the Houdini operator, `list_file_parms`, `set_file`. Dedicated tools only when that loop dies (Hydra, KineFX label crash).

## Character / Mixamo

This is Houdini, not Blender. Mixamo FBX is `kinefx::fbxcharacterimport` + `kinefx::fbxanimimport` under `/obj/mcp_*`. Inspect joints with `list_joints` on the **skeleton SOP**, not the capture mesh.

Built-in capy: `attach_kinefx_deform(source="capybara", clip="elbowdrop")`. HDA output 0 is rest skin (not time-dependent). Animation is output 2 as a motion clip → `kinefx::motionclipevaluate` → `kinefx::jointdeform`. Isolate the OBJ, `grid=false`, `frame_bbox` on the deform SOP. `pose_hash` at two frames must differ. Mixamo-like names: `map_kinefx_joints(rest_skeleton, clip_skeleton)` then `attach_kinefx_deform(source="nodes", map_joints=True)`. Unmapped names raise.

## Lookdev (Solaris)

`lookdev_dome` / `lookdev_preview_surface` / `lookdev_display_color` / `lookdev_camera` / `frame_usd_prim` under `mcp_*`. Look through the **USD prim** (`set_viewport_camera("/mcp_cam")`), never `setCamera(lop_node)`. Assign path is `/materials/<name>`, not `/preview`. Karma samples: `set_karma_quality` — H22 has no viewport pixel-sample HOM; LOP `karmarendersettings` is the knob. `set_renderer_paused` reports `pause_honored` — on this H22 it is a no-op (HOM exists, flag does not stick).

## Docs

`search_docs` / `get_doc` after `python scripts/index_hfs_help.py`. Prefer live `get_parameter_schema` over memory.
