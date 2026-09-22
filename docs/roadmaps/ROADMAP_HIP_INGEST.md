# Roadmap: .hip File Ingest & Pattern Extraction

## Goal

Build a procedural pipeline — a script anyone can run after cloning the repo — that auto-detects the local Houdini install, crawls its `help/` directory for `.hip` example files, parses them (pure text, no Houdini needed), extracts network patterns, and indexes them for searchable retrieval.

Every Houdini install ships with example `.hip` files. They're version-matched, SideFX-authored, and cover the full range of workflows. This is the corpus.

## Design Principles

- **Procedural, not curated.** No committed `.hip` files. The pipeline discovers them on the user's machine.
- **Version-aware.** Houdini best practices change between versions. Patterns extracted from 21.0 examples reflect 21.0 workflows.
- **Zero deps.** Same philosophy as `houdini_rag.py` — stdlib only, no Houdini process needed (except Phase 3 for HDAs).
- **One script, two modes.** `scripts/ingest_hips.py` works as both a standalone CLI (mechanical extraction) and a micro-MCP server (LLM-driven annotation via any MCP client).

## Execution Model

The ingest pipeline has two parts with different requirements:

### Tier 1: Mechanical (No LLM)

```bash
python scripts/ingest_hips.py
```

Pure Python. Finds Houdini install → discovers `.hip` files → parses → extracts patterns → builds BM25 index. No LLM, no API keys, no MCP client. Works for everyone with Python + Houdini installed.

### Tier 2: Micro-MCP Server (Any MCP Client)

```bash
# Start as MCP server — any client can connect
uv run python scripts/ingest_hips.py --serve
```

The same script also runs as a lightweight MCP server (FastMCP, stdio). Exposes annotation tools that let an LLM read the extracted patterns and write explanations. Any MCP client works — Claude Code, Claude Desktop, Cursor, etc. No assumption about which LLM or client.

Micro-MCP tools exposed:
- `list_unannotated` — list patterns that haven't been annotated yet
- `get_pattern` — read a specific extracted pattern (nodes, connections, params)
- `annotate_pattern` — write an LLM-generated summary/explanation for a pattern
- `get_progress` — how many patterns annotated vs. total

This means:
- **Claude Code users** — can run it as an agent task, use subagents, overnight runs
- **Claude Desktop users** — add to `claude_desktop_config.json`, chat-driven annotation
- **Cursor / other MCP clients** — same, just add the server config
- **No MCP client** — Tier 1 still works, you just don't get annotations

### Tier 3: Claude Code (Richest Experience)

Claude Code can orchestrate the full pipeline — run the mechanical extraction, then drive the annotation pass with agent tasks and parallelism. Best for overnight bulk processing of large `.hip` corpora.

## Decisions

- **Granularity:** Both full scene graphs AND focused subgraphs. Store the full graph but also extract focused subgraphs (SOP chains, lighting rigs, ROP configs) for targeted search.
- **Install integration:** `install.py` prompts the user — "Run .hip ingest now? (y/n)". Keeps install fast by default, but surfaces the option.
- **LLM annotation:** Available via micro-MCP server mode. Any MCP client can drive it. Not hardcoded to a specific LLM or client.
- **Search integration:** Extend existing `search_docs` to also cover `hip_patterns/`. One search tool, multiple indices. No separate `search_patterns` tool.

## Phase 1: Houdini Install Detection & .hip Discovery

**Goal:** Auto-detect the Houdini install directory (`$HFS`) and catalog all `.hip` files in its `help/` tree. This is the entry point — everything else depends on it.

### Install Detection

Find `$HFS` (the Houdini install root) across platforms:

| Platform | Default Install Path | Detection Method |
|----------|---------------------|------------------|
| Linux    | `/opt/hfs<version>` | `$HFS` env var → glob `/opt/hfs*` → search `PATH` for `houdini` binary |
| macOS    | `/Applications/Houdini/Houdini<X.X.XXX>` | `$HFS` env var → glob `/Applications/Houdini/*` |
| Windows  | `C:\Program Files\Side Effects Software\Houdini <X.Y.Z>` | `$HFS` env var → glob `Program Files\Side Effects*\Houdini*` |

Priority: `$HFS` env var first (set when Houdini is sourced), then platform-specific glob, then CLI flag `--hfs-dir`.

Extend or reuse the detection pattern from `scripts/install.py:find_houdini_prefs()`.

### .hip Discovery

- [ ] Create `find_houdini_install()` — returns the `$HFS` path or `None`
- [ ] Walk `$HFS/help/` recursively, collect all `*.hip` and `*.hipnc` files
- [ ] Also catalog `*.hda` and `*.otl` files (for Phase 3)
- [ ] Log what's found: file count, total size, subdirectory breakdown
- [ ] Allow `--hfs-dir` override for non-standard installs
- [ ] Allow additional `--extra-dir` for user's own `.hip` collection

**Output:** A function that returns a list of `.hip` file paths (and `.hda` paths) from the local Houdini install.

## Phase 2: Format Discovery & Parser

**Goal:** Understand the `.hip` text format, then build a parser.

- [ ] Read several `.hip` files from the discovered `help/` tree to understand the format
- [ ] Document the structure in `docs/hip_format.md`: node blocks, parameter syntax, connection syntax, network nesting
- [ ] Identify signal vs. noise (UI layout positions, viewport state = noise; nodes, params, connections = signal)
- [ ] Create `hip_parser.py` (stdlib only) that parses a `.hip` file into structured data:
  - **Nodes**: type, path, name, category (SOP/OBJ/ROP/LOP/etc.)
  - **Parameters**: name-value pairs per node (skip defaults/unchanged)
  - **Connections**: input/output wiring between nodes (the network graph)
  - **Network hierarchy**: parent-child nesting (e.g., `/obj/geo1/` contains SOPs)
- [ ] Handle edge cases: expressions, channel references, string params with special chars
- [ ] Tests: parse known `.hip` files, assert expected node counts, connections, param values

**Output:** `hip_parser.py` + tests + format reference doc.

## Phase 3: HDA Network Extraction (Requires Houdini)

**Goal:** Extract node networks from `.hda` files discovered in Phase 1. HDAs are binary — they require a running Houdini process to read.

Many essential SideFX example workflows are shipped as HDAs, not `.hip` files. Skipping them would leave gaps in the pattern library.

- [ ] Create `scripts/extract_hda_networks.py` — requires Houdini's `hou` module
- [ ] Use `hou.hda.definitionsInFile()` to list all definitions in an HDA file
- [ ] For each definition: walk contained nodes, extract the same structured data as the `.hip` parser (nodes, params, connections, hierarchy)
- [ ] Export as JSON or text files that the pattern extraction pipeline can consume alongside parsed `.hip` data
- [ ] Process `.hda` / `.otl` files cataloged in Phase 1
- [ ] Must run inside Houdini (via `hython` or the MCP plugin's `execute_houdini_code`)
- [ ] Tests: mock `hou.hda` module, verify extraction logic

**Output:** `scripts/extract_hda_networks.py`. Run via `hython` or from within Houdini. Produces text/JSON files that feed into the same pattern extraction pipeline as `.hip` files.

**Note:** This is the only phase that requires a Houdini process. It can be skipped — the pipeline works without it, you just don't get HDA patterns. All other phases work on text output.

## Phase 4: Pattern Extraction

**Goal:** Distill parsed scenes into reusable workflow patterns. Extract both full scene graphs and focused subgraphs.

- [ ] Define "pattern" vocabulary:
  - **Network pattern**: a subgraph (e.g., "geo → material → light → mantra ROP")
  - **Node recipe**: a node type + its non-default parameter values (e.g., "Mantra ROP with GI settings")
  - **Connection idiom**: common wiring patterns (e.g., "merge SOPs feeding into a null output")
- [ ] Write `hip_patterns.py` — takes parser output, extracts patterns:
  - Store full scene graph for context
  - Also extract focused subgraphs by context (SOP chains, lighting rigs, ROP configs, LOP networks)
  - Extract "interesting" parameter sets (non-default values that define the setup)
- [ ] Deduplicate across all discovered `.hip` files — find recurring patterns
- [ ] Tag patterns by source file and Houdini version
- [ ] Consume HDA-extracted networks (from Phase 3) alongside `.hip` data, if available

**Output:** `hip_patterns.py`. Takes parsed scene data, returns named patterns with node types, connections, and key parameters. Both full graphs and focused subgraphs.

## Phase 5: Indexing & Storage

**Goal:** Make extracted patterns searchable via the existing `search_docs` tool.

- [ ] Store patterns as text documents in `hip_patterns/` (gitignored — generated per-machine)
- [ ] Extend `houdini_rag.py` BM25 to index `hip_patterns/` alongside `houdini_docs/`
- [ ] `search_docs` searches both indices transparently — one tool, multiple knowledge sources
- [ ] Patterns are regenerated any time the user runs the ingest script (version upgrade → re-run → fresh patterns)

**Output:** Indexed, searchable pattern library. Gitignored, machine-local, version-matched.

## Phase 6: Micro-MCP Server & LLM Annotation

**Goal:** `ingest_hips.py --serve` runs as a micro-MCP server, exposing annotation tools for any MCP client.

### Micro-MCP Tools

| Tool | Description |
|------|-------------|
| `list_unannotated` | List patterns that haven't been annotated yet. Returns IDs, source file, node count. |
| `get_pattern` | Read a specific pattern: full graph or focused subgraph, nodes, connections, params. |
| `annotate_pattern` | Write an LLM-generated summary for a pattern: what it does, why nodes are connected this way, what params achieve. |
| `get_progress` | Annotation progress: N annotated / M total, estimated remaining. |

### MCP Client Configuration

Any MCP client can connect. Example configs:

**Claude Desktop / Cursor (`claude_desktop_config.json`):**
```json
{
  "mcpServers": {
    "houdini-ingest": {
      "command": "uv",
      "args": ["--directory", "/path/to/houdini-mcp", "run", "python", "scripts/ingest_hips.py", "--serve"]
    }
  }
}
```

**Claude Code:**
```bash
claude --mcp-config ingest_mcp.json
# Then: "Annotate all unannotated patterns"
```

### Workflow

1. User runs `python scripts/ingest_hips.py` first (Tier 1, mechanical)
2. User starts `--serve` mode and connects their MCP client
3. LLM calls `list_unannotated` → `get_pattern` → `annotate_pattern` in a loop
4. Can run overnight — no human in the loop
5. Progress is persistent — can stop and resume

**Output:** Annotated pattern library. Richer search results, better context for Claude. Works with any MCP client.

## Phase 7: End-to-End Script

**Goal:** `scripts/ingest_hips.py` — one script, multiple modes.

```bash
# Tier 1: Mechanical extraction (no LLM needed)
python scripts/ingest_hips.py                          # auto-detect, parse, index
python scripts/ingest_hips.py --hfs-dir /opt/hfs21.0   # explicit install dir
python scripts/ingest_hips.py --extra-dir ~/my_hips     # add user's own files
python scripts/ingest_hips.py --no-index                # parse only, skip indexing

# Tier 2: Micro-MCP server (any MCP client drives annotation)
python scripts/ingest_hips.py --serve                   # start MCP server on stdio
uv run python scripts/ingest_hips.py --serve            # with uv
```

- [ ] Detect Houdini install
- [ ] Discover `.hip` files (and HDA-extracted networks if available)
- [ ] Parse each file, extract patterns (full + focused subgraphs)
- [ ] Build index (extends `search_docs`)
- [ ] Progress reporting (file N of M, patterns found)
- [ ] `--serve` mode: start micro-MCP server for LLM annotation
- [ ] Runs headless, no Houdini process needed (except Phase 3 for HDAs)

**Output:** One script, flexible execution. Clone repo → install → run ingest → optionally connect any MCP client for annotation → Claude has workflow knowledge matched to the user's Houdini version.

## Gitignore Additions

```
hip_patterns/
hip_patterns_index.json
```
