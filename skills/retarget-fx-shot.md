# Skill: retarget-fx-shot (Houdini)

Retarget an existing FX rig from one shot to another. Duplicates a named node
group in the network, renames shot-coded nodes, then remaps all file references
from the source shot's sequences to their analogues in the target shot.

## Invoke

> "Retarget the [netbox/group name] network from [SOURCE_SHOT] to [TARGET_SHOT]."

Or supply the three inputs explicitly:

| Input | Description | Example |
|---|---|---|
| `SOURCE_NODES` | List of node paths + netbox name to copy | `/stage/objnet_PARK003`, `__netbox1` |
| `SOURCE_DIR` | Root directory of the source shot's sequences | `/path/to/raw_videos/PARK003/` |
| `TARGET_DIR` | Root directory of the target shot's sequences | `/path/to/raw_videos/CWG006/` |

---

## Phases

### 1. Copy

- Ping Houdini. Confirm connection before any work.
- Read the position of every source node using `execute_houdini_code`.
- Read the netbox via `parent.networkBoxes()` — get its `position()` and `size()`.
- Compute `offset_x` = netbox width + a gap of at least 4 units (typically ~15).
- Duplicate all nodes with `hou.copyNodesTo(src_nodes, parent)`.
- Move each new node: `node.setPosition(pos + hou.Vector2(offset_x, 0))`.
- Create a new netbox at the same offset: `parent.createNetworkBox()`, copy size and comment, add all new nodes to it.

### 2. Rename

- Scan new node names (and their subchildren names) for the source shot code,
  case-insensitive and zero padding insentive (e.g. `PARK003`, `park00003`).
- Also catch Houdini's auto-increment artefacts: if the source node was named
  `objnet_PARK003`, the copy will be `objnet_PARK004` — the shot suffix digit
  incremented, not the shot code itself. Detect these by checking for the source
  shot code stem (e.g. `PARK`).
- Propose renames: replace source shot code with target shot code
  (e.g. `PARK003` → `CWG006`, `PARK0003` → `CWG0006`).
- **Show the rename list and get user confirmation before applying.**
- Apply with `node.setName(new_name)`.

### 3. Scan

- Deep-scan every new node and all its subchildren (`node.allSubChildren()`).
- For each node, iterate `node.parms()`. **Before calling `parm.unexpandedString()`, check
  that the parm is a string type** (`parm.parmTemplate().type() == hou.parmTemplateType.String`).
  Skip non-string parms entirely. LOP nodes such as `editmaterialproperties` have 160+ spare
  parameters of mixed types; calling `unexpandedString()` on a non-string spare raises
  `OperationFailed` and aborts the loop for that node, silently dropping all subsequent parms
  (including file texture paths like `emission_color_file`).
- Also wrap each `unexpandedString()` call in a `try/except` as a belt-and-suspenders guard.
- Collect every hit where the value contains the source shot directory path.
- Report: node path | parameter name | current value.

### 4. Match

- List the source shot directory with `os.listdir()` — collect sequence folder names.
- List the target shot directory — collect sequence folder names.
- Match sequences semantically, in this priority order:
  1. **Shot plate** — keywords: `pl01_ref`, `ref`, `HD_ref`, `plate`
  2. **Clean plate** — keywords: `cp01`, `cleanPlate`, `clean_plate`
  3. **Roto** — keywords: `roto`, `matte`
  4. **Render passes** — match by pass name: `Normal`, `Depth`, `Alpha`,
     `BaseColor`, `Roughness`, `Metallic`, `Specular`, `Source`
- Use process of elimination: once a source sequence is matched, remove it from
  the candidate pool for subsequent matches.
- Flag format changes (`.exr` ↔ `.png`) — note these explicitly.
- Flag unmatched source sequences — leave their parameters unchanged.

**Frame expression translation table:**

| Source pattern | Detected by | New pattern |
|---|---|---|
| `` `padzero(6,$F-N)` `` | backtick + padzero | `$F6` (if files are 6-digit from frame 1001) |
| `` `padzero(5,$F-N)` `` | backtick + padzero | `$F` (if target uses bare frame number) |
| `$F6` | literal | `$F6` (usually unchanged) |
| `$F` | literal | `$F` (usually unchanged) |

Determine which pattern applies by inspecting the first filename in the target
sequence folder: count the digits, check for leading zeros, check whether the
frame number matches `$F` directly or requires an offset.

### 5. Confirm

- Present the full mapping table before touching any parameters:
  - Old path → New path
  - Expression change (if any)
  - Format change (if any)
  - Unmatched sequences (listed separately)
- **Do not proceed until the user approves.**

### 6. Remap

- For each approved mapping, call `parm.set(new_value)` on the parameter.
- Use plain `$F` / `$F6` / `$F4` tokens in the new string — do not use backtick
  expressions unless the target naming convention genuinely requires an offset.
- Apply to every node/parm pair found in the scan (multiple nodes may share the
  same source path).

### 7. Save

- Call `save_scene` after all remaps are applied.
- Report a final summary: N nodes copied, M nodes renamed, P parameters remapped,
  Q sequences unmatched.

---

## Notes

- **Do not remap** any unmatched-sequence parameters — leave them pointing at
  the source shot. The effect in those nodes will be wrong, but that is expected
  and preferable to a silent bad remap. The user handles them manually.
- If the source shot directory has render-pass subdirectories at the root level
  (e.g. `PARK003/Normal/`, `PARK003/Depth/`), treat those as named render passes
  for matching purposes.
- The netbox comment is copied verbatim. Suggest the user update it to reflect
  the target shot after the retarget is complete.
