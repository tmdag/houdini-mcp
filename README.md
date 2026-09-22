# houdini-mcp

Drive a **live Houdini session** from an MCP client (Claude, Grok, Codex, …).

Houdini 22-first. Pipeline-safe by design: this is hands in `houdini-bin`, not a
shot database — it does not talk to any asset-management or production-tracking
API, and it does not ship HDAs.

Backlog: [issues](https://github.com/tmdag/houdini-mcp/issues)

Upstream seed: [kleer001/houdini-mcp](https://github.com/kleer001/houdini-mcp) (MCP bridge + TCP plugin). This fork changed the contract.

## What it is

```
AI client  --stdio MCP-->  houdini_mcp_server.py  --TCP :9876-->  plugin in houdini-bin  -->  hou
```

The plugin is **per Houdini process**. The MCP client config is **per user**.
Ship it as its own package if you vendor it into a facility environment — it is
not meant to live inside a shared HDA library.

## H22 contract

- Start hook: `$HOUDINI_USER_PREF_DIR/python3.13libs/uiready.py` (not `scripts/pythonrc.py`)
- Houdini package JSON: `PYTHONPATH` only — never `path:` onto `HOUDINI_PATH`
- No `hou.ui.desktops()` / shelf UI from MCP (H22 plus a site `123.py` has crashed houdini-bin)
- LOP nodes have no `setRenderFlag`
- `execute_code` returns `{executed, stdout, stderr, error, traceback}` — never drops TCP
- Viewport capture = Scene Viewer **flipbook**. OpenGL ROP is OBJ-only. Desktop grab runs **outside** houdini-bin.
- Solaris viewport: `set_hydra_renderer("xpu"|"cpu"|"vk"|"storm")`. Do not `restartRenderer` + sleep + viewwrite on the MCP thread. USD look-through is `set_viewport_camera("/world/cam")`.

## Install

```bash
git clone https://github.com/tmdag/houdini-mcp
cd houdini-mcp
uv sync
python scripts/install.py --houdini-version 22.0
```

`install.py` copies the plugin into your Houdini preferences directory and
writes the package JSON that auto-starts it. It honours
`HOUDINI_USER_PREF_DIR`; pass `--prefs-dir` if you keep prefs somewhere
unusual, and `--dry-run` to see what it would touch first.

Claude Code / Claude Desktop:

```json
{
  "mcpServers": {
    "houdini": {
      "command": "/path/to/houdini-mcp/.venv/bin/python",
      "args": ["/path/to/houdini-mcp/houdini_mcp_server.py"]
    }
  }
}
```

Grok:

```toml
[mcp_servers.houdini]
command = "/path/to/houdini-mcp/.venv/bin/python"
args = ["/path/to/houdini-mcp/houdini_mcp_server.py"]
enabled = true

[mcp_servers.houdini.env]
HOUDINIMCP_NO_HEADLESS = "1"
HOUDINIMCP_PROFILE = "stage"
```

In Houdini, Python Shell if uiready missed this session:

```python
import houdinimcp
houdinimcp.start_server()
```

## Profiles

191 tools is ~17k tokens of schema before any work starts, so the advertised
surface is trimmed by default. Everything still exists — the profile only
changes what is *listed*, and the server tells the client how many tools it
is hiding and how to get them back.

`HOUDINIMCP_PROFILE`:

- `stage` (default) — 82 tools: Solaris/LOP + inspect + cook + screenshot + execute_code + everything the server instructions reference
- `sop` — `/obj` modeling extras too
- `all` — all 191

Anything named in the server's own instructions is guaranteed to survive
`stage`; `tests/test_tool_surface.py` fails the build otherwise.

## Platform support

| | plugin | bridge | `capture_desktop` | notes |
|---|---|---|---|---|
| Linux | tested | tested | `grim` / `import` / `gnome-screenshot` / `spectacle` | primary target |
| Windows | untested | untested | PowerShell | see [TROUBLESHOOTING § Windows](docs/TROUBLESHOOTING.md#windows) — read it before the first install |
| macOS | untested | untested | `screencapture` | needs Screen Recording permission |

Windows and macOS paths are implemented and unit-tested, but nobody has run
them end to end yet.

## Tuning

| env var | default | what it does |
|---|---|---|
| `HOUDINIMCP_PORT` | `9876` | plugin TCP port |
| `HOUDINIMCP_PROFILE` | `stage` | advertised tool surface |
| `HOUDINIMCP_TIMEOUT` | `60` | bridge deadline for ordinary commands |
| `HOUDINIMCP_LONG_TIMEOUT` | `900` | deadline for renders, sims, cooks, I/O |
| `HOUDINIMCP_POLL_MS` | `20` | plugin socket poll interval |
| `HOUDINIMCP_SEND_TIMEOUT` | `60` | plugin deadline for writing one response |
| `HOUDINIMCP_NO_HEADLESS` | unset | `1` disables hython auto-launch |
| `HOUDINIMCP_LOG` | `quiet` | `verbose` for per-command console output |

## Offline Houdini docs

Index **your** Houdini's help (not a random GitHub dump):

```bash
python scripts/index_hfs_help.py
```

Uses `$HFS/houdini/help` (`hom.zip`, `nodes.zip`, loose `.txt`). Output is gitignored.

## Reload handlers (H22 stays up)

```bash
python scripts/install.py --houdini-version 22.0
```

Then `reload_plugin`. Do not restart houdini-bin for handler changes. Do not `importlib.reload` the TCP server module (QTimer).

TCP frames are `HMC1` + length + JSON. The bridge still speaks bare JSON until the plugin answers in HMC1, so an older houdini-bin keeps working. A second MCP client does not steal the first session; `ping.clients` / `peer_warning` say so.

## Live smoke (H22 already running)

Does **not** boot Houdini. Against a GUI `houdini-bin` with the plugin on `:9876`:

```bash
HOUDINIMCP_LIVE=1 pytest tests/test_live_hydra_smoke.py -q
```

Fails if `list_hydra_renderers` 404s, `set_hydra_renderer` current ≠ requested, USD look-through isn't `/world/cam`, or the flipbook isn't tagged Karma XPU.

## License

MIT (upstream). Not affiliated with SideFX.
