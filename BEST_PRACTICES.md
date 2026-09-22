# Houdini MCP — Best Practices

Hard-won lessons from real production use of the Houdini MCP. Organized by context so you can jump to what's relevant.

**Contributing:** Keep entries brief — problem, symptom, fix. Check this file before adding to avoid duplicates. Every entry must include the Houdini version it was validated against. Use the anti-pattern format when applicable: "Tried X, it silently failed, do Y instead."

## Index

- [Copernicus COPs (Compositing)](#copernicus-cops-compositing)
  - [Layer Naming](#layer-naming)
  - [ImageLayer Creation](#imagelayer-creation)
  - [Python Snippet COP](#python-snippet-cop)
  - [Temporal Access (Time-Shifting)](#temporal-access-time-shifting)
  - [Node Categories](#node-categories)
  - [COP HDA Output Naming](#cop-hda-output-naming)
  - [Resolution Mismatch at Sequence Boundaries](#resolution-mismatch-at-sequence-boundaries)
  - [HDA matchCurrentDefinition Resets Internals](#hda-matchcurrentdefinition-resets-internals)
  - [COP VEX Wrangle: volumesamplep Is Input-0-Only](#cop-vex-wrangle-volumesamplep-is-input-0-only)
  - [COP VEX Wrangle: Coordinate System Is Image Space](#cop-vex-wrangle-coordinate-system-is-image-space)
  - [COP HDA Callbacks Cannot Modify Internal Node Parms](#cop-hda-callbacks-cannot-modify-internal-node-parms)
  - [COP HDA: Prototype Parm Expressions Don't Persist](#cop-hda-prototype-parm-expressions-dont-persist)
  - [HScript Menu Parm Conditionals Require Integer Comparisons](#hscript-menu-parm-conditionals-require-integer-comparisons)
  - [HDA OnParmChanged Event Section Does Not Fire](#hda-onparmchanged-event-section-does-not-fire)
- [COP2 (Legacy Compositing)](#cop2-legacy-compositing)
  - [COP2 VEX Filter Custom Shaders](#cop2-vex-filter-custom-shaders)
  - [Copernicus to COP2 Translation](#copernicus-to-cop2-translation)
  - [COP2 File Node Frame Range](#cop2-file-node-frame-range)
- [Merge / Blend Mode Math Reference](#merge--blend-mode-math-reference)
- [LOPs / USD](#lops--usd)
  - [Karma viewport has no pixel-sample HOM](#karma-viewport-has-no-pixel-sample-hom)
  - [Standalone husk: Let Karma Author RenderVars, Don't DIY](#standalone-husk-let-karma-author-rendervars-dont-diy)
  - [Standalone husk: productName Time-Sampled vs Default](#standalone-husk-productname-time-sampled-vs-default)
  - [Standalone husk: VEX Shaders Need opdef: URIs](#standalone-husk-vex-shaders-need-opdef-uris)
  - [editmaterialproperties: parm.unexpandedString() Aborts Mid-Node on Non-String Spare Parms](#editmaterialproperties-parmunexpandedstring-aborts-mid-node-on-non-string-spare-parms)
- [SOPs / File Cache](#sops--file-cache)
  - [Capybara HDA output is rest skin](#capybara-hda-output-is-rest-skin)
  - [parm.set() Silently Ignored When Expression Active](#parmset-silently-ignored-when-expression-active)
  - [hbatch render Only Works with ROPs, Not SOPs](#hbatch-render-only-works-with-rops-not-sops)
  - [node.cook(force=True) Does Not Force Its Inputs](#nodecookforcetrue-does-not-force-its-inputs)
  - [filecache::2.0 Does Not Write from pressButton() or rop.render()](#filecache20-does-not-write-from-pressbutton-or-roprender)
  - [hou.Geometry.nearestPoints() Is 24x a Python KD-Tree](#hougeometrynearestpoints-is-24x-a-python-kd-tree)
- [VEX / Wrangles](#vex--wrangles)
  - [attribwrangle class Menu Is Detail, Primitives, Points, Vertices](#attribwrangle-class-menu-is-detail-primitives-points-vertices)
  - [hou.text.vexSyntaxCheck() Does Not Exist](#houtextvexsyntaxcheck-does-not-exist)
  - [Writing Vertex Attributes from a Primitive Wrangle Serialises](#writing-vertex-attributes-from-a-primitive-wrangle-serialises)
- [HScript / Run Script](#hscript--run-script)
  - [File > Run Script Only Accepts .cmd, Not .py](#file--run-script-only-accepts-cmd-not-py)
- [General MCP Usage](#general-mcp-usage)
  - [Connection Discipline](#connection-discipline)
  - [hou.undos.group() Groups, It Does Not Roll Back](#houundosgroup-groups-it-does-not-roll-back)
  - [Node Inspection Caveats](#node-inspection-caveats)
  - [HDA Script Sync](#hda-script-sync)
  - [Diagnostics Workflow](#diagnostics-workflow)

---

## Copernicus COPs (Compositing)

### Layer Naming

> Houdini 21.0.631

**The Layer Merge (average) node matches inputs by layer name, not by input index.** Mismatched names are **silently ignored** — no error, no warning, just missing pixels.

**Anti-pattern:** Created a Python Snippet COP with output named `"C"` feeding into a Layer Merge alongside a `"mono"` input. Merge output contained only the mono input. Zero contribution from the other layer, zero errors.

**Diagnosis:** Check `node.outputNames()` on each input to the merge.

**Fix:** Set your node's `output1_name` parm to match the upstream layer name. The `return` dict key must also match: `return {'mono': out_layer}`.

### ImageLayer Creation

> Houdini 21.0.631

When creating a new `hou.ImageLayer()` from scratch (e.g., in a Python Snippet COP), three things will break downstream nodes:

#### 1. Construction order matters

**Anti-pattern:** Set `setDataWindow()` before `setChannelCount()` / `setStorageType()`. Result: `"Provided buffer incorrect size"` on `setAllBufferElements()`.

Buffer size is calculated from resolution + channels + storage at the time the window is set. Set channel count and storage type **first**.

```python
out_layer = hou.ImageLayer()
out_layer.setChannelCount(1)                            # FIRST
out_layer.setStorageType(hou.imageLayerStorageType.Float32)  # FIRST
out_layer.setDataWindow(0, 0, width, height)            # THEN
out_layer.setDisplayWindow(0, 0, width, height)
out_layer.setAllBufferElements(result.tobytes())
```

#### 2. `setDataWindow` / `setDisplayWindow` take 4 separate args, not a list

**Anti-pattern:** Called `setDataWindow([0, 0, 1920, 1080])`. Fails with `"missing 3 required positional arguments"`.

**Fix:** `setDataWindow(0, 0, 1920, 1080)` — four separate ints.

#### 3. Copy all metadata from the source layer

**Anti-pattern:** Returned a new `hou.ImageLayer()` with correct pixel data but no attributes. Downstream Layer Merge **silently discarded** the entire layer.

A bare `hou.ImageLayer()` has zero attributes. Always copy metadata:

```python
out_layer.setBorder(input_layer.border())
out_layer.setPixelScale(input_layer.pixelScale())
out_layer.setTypeInfo(input_layer.typeInfo())
out_layer.setProjection(input_layer.projection())
out_layer.setAttributes(input_layer.attributes())
```

### Python Snippet COP

> Houdini 21.0.631

#### `kwargs` contains ImageLayer objects, not numpy arrays

Extract pixel data with:

```python
data = layer.allBufferElements(hou.imageLayerStorageType.Float32, channels)
arr = np.frombuffer(data, dtype=np.float32).reshape(height, width).copy()
```

The `.copy()` is required — the original buffer is read-only.

#### Input layers are GPU-resident and NOT frozen

**Anti-pattern:** Tried `setAllBufferElements()`, `makeConstant()`, and `freeze()` on `kwargs` input layers. All fail — they're GPU-resident with `isFrozen=False`.

**Fix:** Always create a new `hou.ImageLayer()` for output. Never modify the input in-place.

#### `hou` module IS accessible

Despite the docs stating "this node can't access the currently evaluating node", `import hou` works. You can call `hou.pwd()`, `hou.frame()`, `hou.node()`, and critically `node.layerAtFrame(frame)` for temporal effects. See [Temporal Access](#temporal-access-time-shifting).

### Temporal Access (Time-Shifting)

> Houdini 21.0.631

**Copernicus has no native timeshift COP.** The old COP2 `shift` node does not exist in Copernicus networks.

**Anti-patterns tried:**
- `op:` syntax in the File COP to reference another COP's output → `"Unable to read file"`
- Searching for `shift`, `timefilter`, `timeshift` in the Cop category → none exist
- File COP `videoframemethod` / `videoframe` with expressions → only works for on-disk sequences, not upstream COP outputs

**Workaround:** `node.layerAtFrame(float)` from Python (via `execute_houdini_code` or inside a Python Snippet COP). Cooks the target node at any frame and returns an `ImageLayer`.

```python
source = hou.pwd().inputs()[0]
layer_past = source.layerAtFrame(hou.frame() - 5)
layer_future = source.layerAtFrame(hou.frame() + 5)
```

**Performance:** Each call triggers a full upstream cook at that frame. 10 echo offsets = 10 extra cooks per frame.

### Node Categories

> Houdini 21.0.631

**Copernicus node category is `"Cop"`, not `"Cop2"`.** Use `node.childTypeCategory()` to query. Old COP2 nodes (`shift`, `timefilter`, `vopcop2filter`, etc.) are not available in Copernicus networks.

```python
parent = hou.node("/path/to/copnet")
for name in sorted(parent.childTypeCategory().nodeTypes().keys()):
    print(name)
```

### COP HDA Output Naming

> Houdini 21.0.631

**For COP HDAs, `outputNames()` is controlled by the `output` line in the DialogScript section of the HDA definition — NOT by the `outputname#` multiparm parm.**

**Anti-pattern:** Created a COP HDA with `outputname1` multiparm (matching the null node pattern) and set it to `"mono"`. `outputNames()` still returned `('output1',)` — the default connector name from the DialogScript. Downstream Layer Merge silently ignored the HDA's output.

**Diagnosis:** Read the HDA's DialogScript section: `hda_def.sections()['DialogScript'].contents()`. Look for the `output` line (format: `output <connector_name> <label>`).

**Fix:** Modify the DialogScript's `output` line to set the desired layer name:

```python
hda_def = node.type().definition()
ds = hda_def.sections()['DialogScript'].contents()
ds = ds.replace('output\toutput1\tC', 'output\tlayer\tlayer')
hda_def.sections()['DialogScript'].setContents(ds)
node.matchCurrentDefinition()
```

**Note:** The `outputname#` multiparm on a COP HDA has no effect on `outputNames()`. It works on built-in nodes like `null` because their output naming is handled in C++, not via DialogScript.

### Resolution Mismatch at Sequence Boundaries

> Houdini 21.0.631

**`layerAtFrame()` returns a default 1024×1024 layer for frames outside the source sequence range.** No error — just wrong resolution.

**Anti-pattern:** Echo effect called `layerAtFrame(frame - 5)` near the start of a sequence (frame 1001). Frames before 1001 returned 1024×1024 instead of the expected 1920×1080. `np.maximum()` then failed or produced garbage due to shape mismatch.

**Fix:** Guard against resolution mismatch before blending:

```python
echo_layer = source.layerAtFrame(echo_frame)
if echo_layer.bufferResolution() != (width, height):
    continue
```

### HDA `matchCurrentDefinition` Resets Internals

> Houdini 21.0.631

**Calling `node.matchCurrentDefinition()` on an unlocked HDA reverts ALL internal edits** — manually created nodes, rewired connections, and parm changes inside the HDA are lost.

**Anti-pattern:** Unlocked an HDA with `allowEditingOfContents()`, created a null node inside, wired it into the chain, then called `matchCurrentDefinition()` to refresh the outer node. The null node disappeared and the internal chain reverted to the saved definition.

**Fix:** Make all changes to the HDA definition (DialogScript, parm template, etc.) BEFORE calling `matchCurrentDefinition()`. Or save the definition (`hda_def.save()`) after internal edits and before refreshing.

### COP VEX Wrangle: `volumesamplep` Is Input-0-Only

> Houdini 21.0

**`volumesamplep(input, "layer", pos)` silently returns `{0,0,0}` for any `input` other than `0`.** There is no error, no warning, and no cook failure — just black pixels.

**Anti-pattern:** Wrangle with source at input 0 (resample) and original image at input 1. Used `volumesamplep(1, "C", tiled_pos)` to sample the original at a custom UV. Always returned zero.

**Fix:** Only input 0 is accessible for custom-position sampling via `volumesamplep`. If you need to sample a different COP input at arbitrary positions, restructure so that input is connected at slot 0. For tiling specifically: force the resample to STRETCH fit mode so its image space is identical to the source's, then sample `volumesamplep(0, "C", tiled_pos)` on the resample — it gives the same result as sampling the source directly.

**Note:** `volumeres(input, "layer")` has the same limitation — returns 0 for non-zero input indices and for layer names that don't exist on the input. Read source dimensions from HDA hidden parms set by Python callbacks instead.

### COP VEX Wrangle: Coordinate System Is Image Space

> Houdini 21.0

**In a COP wrangle, `@P` is in image space — `(-1, -1)` at top-left to `(+1, +1)` at bottom-right — not pixel indices.** `volumesamplep` expects image-space coordinates.

**Verified:** At pixel `(0, 0)` of a 1024-wide image, `@P.x ≈ -0.999`. At pixel `(1023, 0)`, `@P.x ≈ +0.999`.

**Coordinate conversion from tile UV (0..1) to image space:**

```c
// Naïve — lands on cell boundaries at u=0.25, 0.5 etc.; bilinear bleed produces 0.5 gray
float ip_x = 2.0f * u - 1.0f;

// Correct — shifts to voxel center; avoids boundary interpolation
float ip_x = 2.0f * u - 1.0f + 1.0f / src_w;
```

The `+ 1/src_w` half-pixel shift matters whenever your UV lands near a voxel boundary (e.g. at checkerboard cell edges). Without it, bilinear interpolation between a white and a black cell produces 0.5.

**Pixel reads from Python:** Use `layer.bufferIndex(x, y)` to read individual pixels — not `.pixel()` (doesn't exist on `hou.ImageLayer`). `bufferIndexV4(x, y)` returns all four channels.

### COP HDA Callbacks Cannot Modify Internal Node Parms

> Houdini 21.0

**Python callbacks (`OnCreated`, `OnParmChanged`, `OnInputChanged`) raise `hou.PermissionError: locked assets` if they attempt to call `parm.set()` on any node inside the HDA's locked subnet.**

**Anti-pattern:** `onParmChanged` computed a fit mode integer and called `resample.parm("stretch").set(computed_value)` on the internal resample node. Raised `PermissionError` at cook time.

**Fix:** Callbacks may only modify the HDA's **own** parameters. Drive internal node parms exclusively via HScript channel-reference expressions baked in at build time:

```python
# At HDA build time — expressions are locked in permanently:
rs.parm("stretch").setExpression('ch("../fit_mode")', language=hou.exprLanguage.Hscript)

# In OnParmChanged — only touch the HDA's own parms:
def onParmChanged(kwargs):
    node = kwargs["node"]
    node.parm("_computed_res_w").set(...)   # HDA's own hidden parm — OK
    # node.parm("internal_rs_parm").set()  # PermissionError — never do this
```

### COP HDA: Prototype Parm Expressions Don't Persist

> Houdini 21.0

**`parm.setExpression()` called on the prototype/build instance of an HDA is an instance-level override. It is NOT saved into the HDA type definition.** New instances created from the saved HDA get the default value (e.g. `0`), never the expression.

**Anti-pattern:** After `hda_def.setParmTemplateGroup(ptg)` and before `hda_def.save()`, called `hda_node.parm("tile_mode_int").setExpression('ch("tile_mode")')`. The build instance had the expression. Every new instance of the HDA evaluated `tile_mode_int` as `0`.

**Symptom:** A hidden integer mirror parm always reads its default value regardless of what the source menu parm is set to.

**Fix:** Maintain integer-mirror parms via Python callbacks, not expressions:

```python
# In onCreated AND _update():
node.parm("tile_mode_int").set(node.parm("tile_mode").eval())
```

**Also note:** In headless hython, `parm.set()` does **not** fire `OnParmChanged` event handlers. When testing, call your update function manually: `node.hdaModule()._update(node)`.

### HScript Menu Parm Conditionals Require Integer Comparisons

> Houdini 21.0

**Using `chs("parm") == "token"` in an HScript expression causes a "Bad data type for function or operation" cook error.** No visual feedback during build — the error only surfaces when the node cooks.

**Anti-pattern:**

```python
# Breaks at cook time:
FILTER_EXPR = 'if(chs("../filter_mode")=="auto", 4, if(chs(...)==..., ...))'
```

**Fix:** Menu parms (`MenuParmTemplate`) store integer indices. Use `ch("parm")` (not `chs`) and compare against the zero-based index:

```python
# Works — compare index integers, not token strings:
FILTER_EXPR = (
    'if(ch("../filter_mode")==0, 4, '   # auto → catmull-rom
    'if(ch("../filter_mode")==1, 0, '   # point
    # ...
    '1))'
)
```

The token strings shown in the UI (`"auto"`, `"point"`) are only accessible via `chs()`, but `chs()` comparisons in `if()` expressions do not work. Always use the integer index from `ch()`.

### HDA OnParmChanged Event Section Does Not Fire

> Houdini 21.0

**Adding an `OnParmChanged` section to an HDA definition has no effect — Houdini does not fire it when parameters change.** The section is stored silently and never called. `OnCreated` and `OnInputChanged` are the only reliably fired interactive HDA events.

**Anti-pattern:**

```python
hda_def.addSection("OnParmChanged", "kwargs['node'].hdaModule().onParmChanged(kwargs)")
hda_def.setExtraFileOption("OnParmChanged/IsPython", True)
# Never fires — parameters changing in the UI do nothing.
```

**Fix:** Set `script_callback` on each `ParmTemplate` that needs to trigger Python when changed. This fires on interactive edits and is stored in the HDA type definition, so it persists to every new instance without per-instance setup:

```python
def _cb(pt):
    pt.setScriptCallback("kwargs['node'].hdaModule().onParmChanged(kwargs)")
    pt.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    return pt

width_pt = hou.IntParmTemplate("width", "Width", 1)
_cb(width_pt)
```

`kwargs['node']` is the node, `kwargs['parm_name']` is the changed parameter name, `kwargs['script_value']` is the new value.

---

## COP2 (Legacy Compositing)

### COP2 VEX Filter Custom Shaders

> Houdini 21.0.631

**The `vexfilter` node cannot find custom `.vex` shaders by short name from user directories.** It only resolves short names from the system `$HH/vex/Cop2/` directory.

**Anti-pattern:** Compiled a `.vfl` to `~/houdini21.0/vex/Cop2/softlight.vex` (which IS on `HOUDINI_PATH`), set `function` parm to `"softlight"`. Error: `"Could not find VEX Cop2 shader 'softlight'"`.

**Fix:** Use the full absolute path without extension:

```python
node.parm("function").set("/home/user/houdini21.0/vex/Cop2/softlight")
```

**VFL compilation:** `vcc myfilter.vfl` from the target directory. The `cop2` context is declared in the file itself — no `-d` flag needed (that flag means "compile all functions", not "set context").

### Copernicus to COP2 Translation

> Houdini 21.0.631

**Copernicus (`copnet`, child category `Cop`) and COP2 (`cop2net`, child category `Cop2`) are different systems.** Node types don't cross between them.

Key type mappings:

| Copernicus | COP2 | Notes |
|---|---|---|
| `blend` (mode=over) | `over` | Input order swapped: COP2 `over` is FG=in0, BG=in1 (Copernicus blend is A/BG=in0, B/FG=in1) |
| `blend` (mode=max) | `max` | `mask` parm → `effectamount` parm |
| `xform2d` | `xform` | Same parm names (tx, ty, etc.) |
| `constant` | `color` | `f4r/f4g/f4b` → `colorr/colorg/colorb`; COP2 `color` is a generator (set resolution explicitly) |
| `resample` | `scale` | COP2 `scale` uses explicit resolution, not a reference input |
| `rop_image` | `rop_comp` | `filename` → `filename1`; frame range parms differ |
| `channelswap` | `channelcopy` | No direct equivalent; consider skipping if `mono` is downstream |
| `file`, `null`, `mono`, `invert`, `gamma`, `layer` | same name | Parm names may differ (e.g. COP2 file uses `filename1`) |

### COP2 File Node Frame Range

> Houdini 21.0.631

**COP2 `file` node shows a grey dotted X when the current frame is outside the node's `start`/`length` range.** No error — just a blank frame with a grey X overlay.

**Anti-pattern:** File node with expression-based frame offset (e.g. `` `padzero(4,$F-1001)` ``) mapping frames 1002–1265 to files frame_0001.png–frame_0264.png. Default `start=1` and `length=264` meant valid range was frames 1–264, but timeline was at frame 1016.

**Fix:** Set `start` to match the first Houdini frame where a file exists (1002 in this case). The `length` stays at the file count (264).

---

## Merge / Blend Mode Math Reference

Comprehensive reference for compositing blend modes. Useful when implementing custom VEX filters.

Source: [Nuke Merge Operations](https://learn.foundry.com/nuke/9.0/content/comp_environment/merging/merge_operations.html)

Where **A = foreground**, **B = background**, **a/b = respective alpha**:

| Mode | Formula |
|---|---|
| Over | `A + B(1-a)` |
| Under | `A(1-b) + B` |
| Plus / Add | `A + B` |
| Multiply | `AB` |
| Screen | `A + B - AB` |
| Max / Lighten | `max(A, B)` |
| Min / Darken | `min(A, B)` |
| Soft Light | If `AB < 1`: `B(2A + B(1 - AB))`, else: `2AB` |
| Hard Light | If `A < 0.5`: `2AB`, else: `1 - 2(1-A)(1-B)` |
| Overlay | Hard Light with inputs swapped |
| Color Dodge | `B / (1-A)` |
| Color Burn | `1 - (1-B)/A` |
| Difference | `|A - B|` |
| Exclusion | `A + B - 2AB` |

---

## LOPs / USD

### Karma viewport has no pixel-sample HOM

> Houdini 22.0.429

**H22 `hou.SceneViewer` can switch Hydra delegates and pause. It cannot set Karma pixel samples or preview-vs-full.** Those live on the `karmarendersettings` LOP (`samplesperpixel`, `percentofsamples`).

**Anti-pattern:** `setHydraRenderer("xpu")` and assume samples follow. Pause has also been a no-op on XPU in some probes — read `isRendererPaused` / `pause_honored`.

**Fix:** `set_karma_quality(samples=..., preview=..., lop_path=...)`. Viewport sample API is reported `unavailable` rather than faked. `setRendererPaused` on this H22 does **not** stick (`pause_honored=false` on CPU and XPU). Do not treat pause as a quality knob.

### Standalone husk: Let Karma Author RenderVars, Don't DIY

> Houdini 21.0.631

**Symptom:** Manually authored RenderVars produce `Unsupported AOV settings for: C` or black renders. No orderedVars produces `No orderedVars to specify channels`.

**Cause:** Karma in-process and standalone husk validate RenderVar attributes differently (SideFX BUG #134678). Copying the exact values from `karmarendersettings` LOP output (`color4f` + LPE + `color4h`) fails in standalone husk. Manually authoring simpler values (`color3f`/`raw`/`C`) also fails. There is no known manually-authored RenderVar configuration that reliably works across husk versions.

**Anti-patterns tried:**
- `color4f` + `sourceName=C.*[LO]` + `sourceType=lpe` → "Unsupported AOV settings"
- `color3f` + `sourceName=C` + `sourceType=raw` + husk attrs → "Unsupported AOV settings"
- `color3f` + `sourceName=Ci` + `sourceType=raw` (no husk attrs) → warning + black render

**Fix:** Don't author RenderVars yourself. Enable the **Beauty AOV** checkbox on the Karma RenderSettings LOP in the scene. The LOP authors RenderVars through an internal code path that husk accepts. Detect missing orderedVars during auditing and warn the user to enable Beauty.

### Standalone husk: productName Time-Sampled vs Default

> Houdini 21.0.631

**Symptom:** husk writes to a stale path like `/old/path/$HIPNAME.$OS.$F4.exr` instead of the productName you authored.

**Cause:** Karma RenderSettings LOP evaluates `$HIP/render/$HIPNAME.$OS.$F4.exr` at cook time, baking it as a **time-sampled** value on `productName`. After `stage.Flatten()`, setting `attr_spec.default = new_path` is ignored — time-sampled values always win over defaults in USD composition.

**Fix:** Clear time-sampled values before setting the default:

```python
attr = prim.GetAttribute("productName")
if attr and attr.GetTimeSamples():
    attr.Clear()
attr_spec = Sdf.AttributeSpec(prim_spec, "productName", Sdf.ValueTypeNames.Token)
attr_spec.default = new_path
```

**Diagnostic:** `attr.GetTimeSamples()` returns non-empty if time samples exist.

### Standalone husk: VEX Shaders Need opdef: URIs

> Houdini 21.0.631

**Symptom:** `Unhandled node type <name> in material`. Objects render default grey.

**Cause:** VEX shader resolution in husk works ONLY through `opdef:` URI resolution (e.g. `opdef:/Vop/principledshader::2.0?SurfaceVexCode`), which triggers on-demand VEX compilation via `VEX_VexResolver`. There is **no Sdr parser plugin for VEX/VFL** — the Sdr registry only handles `kma`, `mtlx`, `glslfx`, and `USD` source types. Baking opdef: references to VFL files on disk does nothing — husk cannot use them.

**Anti-patterns tried:**
- Baking VFL source to a file inside USDZ → husk can't read files from zip archives
- Extracting VFL to disk and overriding sourceAsset → no Sdr parser for VFL files
- Baking to disk with various file extensions → irrelevant, no parser exists

**Fix:** Preserve `opdef:` URIs for VEX shaders. If you must bake `opdef:` references for USDZ packaging (`CreateNewUsdzPackage` needs real files), override `info:sourceAsset` back to the original `opdef:` URI in a wrapper USDA layer:

```python
# During baking: record original opdef: URIs for Shader prims
# After USDZ creation: wrapper overrides sourceAsset back to opdef:

# In wrapper .usda:
# over "materials" { over "mirror" { over "mirror_surface" {
#     asset info:sourceAsset = @opdef:/Vop/principledshader::2.0?SurfaceVexCode@
# }}}
```

**Requirements:** Karma CPU only (not XPU). Houdini must be installed on the render machine — the OTL libraries (`$HH/otls/OPlibVop.hda`) must be loadable for factory shaders. Custom VOP HDAs need their `.hda` files deployed via `HOUDINI_OTLSCAN_PATH`.

**Fully portable alternative:** Replace VEX shaders with MaterialX (`mtlxstandard_surface`, `ND_*` nodes) or `UsdPreviewSurface`. These work with Karma CPU, XPU, and standalone husk without any Houdini dependencies.

### editmaterialproperties: parm.unexpandedString() Aborts Mid-Node on Non-String Spare Parms

> Houdini 21.0.631

**`editmaterialproperties` LOP nodes have 160+ spare parameters, most of which are non-string types (folders, floats, toggles, vectors). Calling `parm.unexpandedString()` on any of them raises `OperationFailed: Only string parms have unexpanded string`. Without a per-parm try/except, the scan loop aborts on the first non-string spare parm and never reaches later string parms (like file texture paths).**

**Anti-pattern:** Iterating `node.parms()` and calling `parm.unexpandedString()` to scan for file path references. The first spare folder parm raises, killing the loop. File parms like `emission_color_file` appear later in the list and are silently skipped.

**Symptom:** File path parms on `editmaterialproperties` nodes are missed during a scan, even though they contain the search string and `node.parms()` does include them.

**Fix:** Check the parm template type before calling `unexpandedString()`, or guard per-parm:

```python
for p in node.parms():
    if p.parmTemplate().type() != hou.parmTemplateType.String:
        continue
    try:
        val = p.unexpandedString()
    except Exception:
        continue
    if search_string in val:
        hits.append((node.path(), p.name(), val))
```

**Note:** `node.parms()` DOES include spare parameters — that's not the issue. The issue is solely that non-string spare parms raise on `unexpandedString()`.

---

## SOPs / File Cache

### Capybara HDA output is rest skin

> Houdini 22.0.429

**`testgeometry_capybara` output 0 is rest skin with capture weights — not time-dependent.** Displaying that SOP is a T-pose forever. Animation is output 2 (turn on `outputclip`) and needs `kinefx::motionclipevaluate` then `kinefx::jointdeform` (skin + capture pose + eval).

**Anti-pattern:** `list_joints` on the 29k-pt capture mesh. That is the skin, not the skeleton.

**Fix:** `attach_kinefx_deform(source="capybara", clip="elbowdrop")`. Isolate the OBJ, `frame_bbox` the deform SOP, `grid=false`. `pose_hash` at two frames must differ.

### `parm.set()` Silently Ignored When Expression Active

> Houdini 21.0.631

**`parm.set(value)` on a float/int parm is silently ignored if the parm has an active expression or keyframe.** The expression always takes priority. No error, no warning — the value just doesn't stick.

**Anti-pattern:** Created a `filecache::2.0` node and called `fc.parm("f1").set(100)`. The parm still evaluated to `1` because `f1` has a default expression (`$FSTART`). The `set()` call was completely ignored.

**Affected parms on filecache::2.0:** `f1` (`$FSTART`), `f2` (`$FEND`), `f3` (may have `$FINC`). String parms like `basedir` and `basename` are NOT affected — they store raw strings, not expressions.

**Fix:** Call `deleteAllKeyframes()` before `set()` to clear the expression first:

```python
fc.parm("f1").deleteAllKeyframes()
fc.parm("f1").set(100)  # Now actually takes effect
```

**Note:** This applies to any parm with a default expression, not just filecache nodes. Common offenders: `$FSTART`/`$FEND` on frame range parms, `ch("../parm")` on HDA-internal parms.

### hbatch `render` Only Works with ROPs, Not SOPs

> Houdini 21.0.631

**The hbatch `render` command silently does nothing when given a SOP path like a filecache node.** It only works with ROP nodes. No error, no output — just exits cleanly with rc=0.

**Anti-pattern:** `hbatch -c "mread scene.hip; render -f 1 1 /obj/geo/filecache1; quit"` — exits successfully but produces zero cache files.

**Fix:** Use hython with `pressButton()` on the filecache's `execute` parm instead:

```bash
hython -c '
import hou
hou.hipFile.load("scene.hip")
node = hou.node("/obj/geo/filecache1")
node.parm("execute").pressButton()
'
```

`pressButton()` is synchronous in hython — it blocks until all frames are written.

---

### node.cook(force=True) Does Not Force Its Inputs

> Houdini 22.0.429

**`force=True` re-cooks that node only.** Its upstream stays cached. Combined with a Python SOP reading `node.parent().evalParm(...)` -- which does not reliably register a parameter dependency -- a parameter sweep can silently measure the same result every time.

**Anti-pattern:** swept a `simplify` parameter across 0.5 / 2.0 / 5.0 and forced only the last node in the chain. All three runs returned byte-identical geometry, and the second and third reported `cook_s: 0.0`. The parameter change never reached the node that reads it.

**Fix:** force every stage explicitly, upstream first, and check the cook time is non-zero before trusting the numbers. A stage that reports 0.0s did not run.

### filecache::2.0 Does Not Write from pressButton() or rop.render()

> Houdini 22.0.429

**`cache.parm("execute").pressButton()` and `cache.node("render").render()` both return in ~0.02s and write nothing.** No error, no warning; the output directory is created, and it stays empty.

**Fix:** for a single-frame cache, write the upstream geometry directly, then flip `loadfromdisk` on:

```python
path = cache.evalParm("file")
os.makedirs(os.path.dirname(path), exist_ok=True)
upstream.geometry().saveToFile(path)
cache.parm("loadfromdisk").set(1)
```

Worth knowing: a `filecache::2.0` with `loadfromdisk` on and **no file on disk** passes the input through cleanly rather than erroring, so a cached scene stays portable to someone who does not have your cache.

### hou.Geometry.nearestPoints() Is 24x a Python KD-Tree

> Houdini 22.0.429

Measured over 45,051 points, 2,000 queries:

| | per query |
|---|---|
| `geo.nearestPoints(pos, 8)` | 13.8 us |
| hand-written Python kd-tree | 338.3 us |

`hou.Geometry()` constructs standalone (no SOP needed) and `createPoints(positions)` bulk-fills it, so a scratch index costs ~0.1s to build. It ships with every Houdini on every platform -- unlike `scipy.spatial.cKDTree`, which is **not** in Houdini's Python and would make a scene fail to cook for anyone who opens it without scipy.

**Caution:** `nearestPoints` has no "exclude these points" argument. Asking for k-nearest and filtering afterwards looks fine and is a trap: when all k hits are excluded you must widen k, and if the excluded set is most of the geometry, k escalates until the query allocates most of the point count per call. That wedged a 45k-point cook for over 30 minutes. Use the `ptgroup` pattern argument to exclude up front instead.

## VEX / Wrangles

### attribwrangle class Menu Is Detail, Primitives, Points, Vertices

> Houdini 22.0.429

**The `class` parameter menu order is `0 Detail, 1 Primitives, 2 Points, 3 Vertices, 4 Numbers`** -- Primitives before Points, which is the opposite of the order most people write from memory.

**Anti-pattern:** a helper mapped `{"Detail":0, "Points":1, "Vertices":2, "Primitives":3}`. Every value except Detail built the wrong kind of wrangle. Nothing errored: the snippet compiled and cooked, and wrote its attribute to the wrong class. A primitive wrangle ended up writing `uv_rotation` and `Cd` onto vertices, and the vertex wrangle meant to write `uv` ran over points, so `uv` never appeared at all.

**Fix:** read the menu off the node rather than trusting a table.

```python
parm = node.parm("class")
labels = parm.parmTemplate().menuLabels()   # ('Detail (only once)', 'Primitives', ...)
```

### hou.text.vexSyntaxCheck() Does Not Exist

> Houdini 22.0.429

Calling it raises `AttributeError: 'text' object has no attribute 'vexSyntaxCheck'`. It is not in the shipped documentation either.

**Fix:** compile the snippet on a throwaway wrangle and read the node's own errors -- the same thing Houdini does when you press Enter in the parameter.

```python
holder = hou.node("/obj").createNode("geo", run_init_scripts=False)
try:
    w = holder.createNode("attribwrangle")
    w.parm("snippet").set(code)
    try:
        w.cook(force=True)
    except hou.OperationFailed:
        pass                       # a compile failure is the answer, not an exception
    errors = [str(e) for e in (w.errors() or [])]
finally:
    holder.destroy()
```

### Writing Vertex Attributes from a Primitive Wrangle Serialises

> Houdini 22.0.429

A primitive wrangle can only reach vertices through `setvertexattrib()`, and that path is far slower than it looks. Computing per-field planar UVs over 8,408 polygons / 125,575 vertices:

| | time |
|---|---|
| one primitive wrangle using `setvertexattrib` | **9.6 s** |
| primitive wrangle writing prim attributes, then a vertex wrangle writing `v@uv` | **0.01 s** |

The single-pass version was slower than the Python SOP it replaced. **Fix:** compute the per-primitive frame in a Primitives wrangle, then read it back with `prim(0, "name", @primnum)` in a Vertices wrangle and assign `v@uv` directly.

## HScript / Run Script

### File > Run Script Only Accepts .cmd, Not .py

> Houdini 21.0.631

**The File > Run Script... menu maps to HScript's `source` command, which parses HScript only.** Picking a `.py` file fails with `Application doesn't support input redirection` (HScript tries to interpret the Python content). Renaming a Python file to `.cmd` doesn't help — same parser, same failure.

**Anti-pattern:** Shipped a plugin's setup as `<plugin>_setup.py` and told users to File > Run Script it. Users hit cryptic HScript parse errors on the first non-comment line.

**Fix — dispatcher pattern:** Ship a tiny `.cmd` that resolves its own path via `$arg0` and exec's a sibling `.py`:

```
python -c "import os; p=os.path.join(os.path.dirname(os.path.abspath(r'$arg0')),'setup.py'); exec(compile(open(p).read(),p,'exec'),{'__name__':'__main__','__file__':p})"
```

Two extra notes:
- HScript's `python -c "..."` argument **must be a single line** — embedded newlines break because HScript reparses subsequent lines as commands. Backslash continuation joins lines but strips the newline.
- `$arg0` inside a sourced `.cmd` evaluates to the `.cmd`'s own absolute path, which is the cleanest way to find sibling files (HDAs, .py modules) the user dropped next to it.

## General MCP Usage

### Connection Discipline

> Houdini 22.0.429

**The plugin is a session, not a phone call.** It already multiplexes persistent clients. One-shot connect/execute/close still works, but it used to print four lines to the Houdini Python shell *per command*.

1. **Keep the TCP socket.** The stdio bridge reuses one connection. Do not reconnect per tool. Do not wait 1s between calls.
2. **Console is quiet by default.** `Connected to client` / `Executing handler` / `Client disconnected` only appear when `set_log_level("verbose")` or `HOUDINIMCP_LOG=verbose`.
3. **Ping before starting work** — verify connectivity before issuing commands.
4. **If you get a connection error, stop** — don't retry in a loop. The plugin likely needs a restart.
5. **Use `batch` for bulk operations** — one undo entry, but *not* a transaction. See [hou.undos.group() Groups, It Does Not Roll Back](#houundosgroup-groups-it-does-not-roll-back).

**Anti-pattern:** A live-smoke / agent helper that `socket()`+`close()` around every `set_frame` and `capture_screenshot`. Symptom: the Houdini console scrolls connect/disconnect faster than the viewport updates.

**Fix:** One client socket for the lookdev loop. `batch` when you can. `set_log_level("quiet")` if an old houdini-bin is still shouting (then `reload_plugin` so the print filter lands without restarting).

### hou.undos.group() Groups, It Does Not Roll Back

> Houdini 22.0.429

**`with hou.undos.group(...)` collapses everything inside into one undo entry. It does not undo that entry when the block raises.** There is no implicit rollback and no error — the partially-applied scene just stays.

**Anti-pattern:** `batch` was documented as executing "atomically in a single undo group". A three-operation batch whose third operation was an unknown command type returned `Error: Unknown operation in batch` *and left the two nodes the first two operations had created*. An agent that trusts the word "atomically" reads the error as "nothing happened", retries the whole batch, and ends up with `geo1`/`geo2` plus `geo3`/`geo4`.

**Fix:** validate everything you can before the first mutation, and report how far you got when you can't.

- Unknown command types are now rejected up front — nothing runs.
- A handler that raises mid-batch produces `completed`, `completed_count`, `failed_index`, `failed_type` and `rolled_back: false` in the error payload. Read those before retrying.
- If you genuinely need rollback, you have to call `hou.undos.performUndo()` yourself, and be certain the group captured only your own operations.

### Node Inspection Caveats

> Houdini 21.0.631

**`get_node_info` can crash on certain node types.** We encountered a `'Color' object is not iterable` error when calling it on nodes with non-standard color configurations.

**Workaround:** Use `execute_houdini_code` to inspect nodes manually when `get_node_info` fails. Iterate `node.parms()`, `node.inputs()`, `node.outputs()` directly.

### HDA Script Sync

> Houdini 21.0.631

**Editing HDA script files on disk does NOT update the embedded code inside the `.hdalc`.** The HDA definition carries its own copy of `PythonModule.py`, `OnCreated.py`, etc. If you only change the on-disk files, the live HDA keeps running the old code.

**Anti-pattern:** Changed `PythonModule.py` in the repo, committed, but didn't update the HDA definition. The node in Houdini still ran the old logic.

**Fix:** After modifying any HDA script file, push the updated code into the HDA definition — via Type Properties → Scripts in the Houdini UI, or via MCP (`set_hda_section_content` / `update_hda`). Treat HDA sync as part of the commit.

### Diagnostics Workflow

> Houdini 21.0.631

When something looks wrong in a COP network, use `execute_houdini_code` to inspect systematically:

1. **Check network topology** — iterate `parent.children()`, print inputs/outputs for each node.
2. **Check for errors** — `node.errors()` and `node.warnings()` on each node in the chain.
3. **Check layer names first** — `node.outputNames()` mismatches are the #1 cause of silent failures in Copernicus. See [Layer Naming](#layer-naming).
4. **Compare pixel values** — `layer.allBufferElements()` + numpy at specific coordinates. Don't trust visual inspection alone.
5. **Compare layer metadata** — `outputNames()`, `channelCount()`, `attributes()`, `typeInfo()` between working and broken paths.
6. **Use a switch node for A/B testing** — insert a switch to isolate which part of the chain causes the issue.
