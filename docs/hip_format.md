# .hip File Format Reference

## Overview

Houdini `.hip` files use a legacy **cpio archive** format (pre-SVR4/odc). The
archive contains multiple named sections, each holding a different part of the
scene state. The format is text-based (ASCII) with null bytes as delimiters.

## Cpio Section Headers

Each section starts with a fixed-width header:

```
070707<octal metadata><name_length><body_length><name>\0<body>
```

- Magic: `070707` (always 6 chars)
- Followed by fixed-width octal fields (device, inode, mode, uid, gid, nlinks,
  rdev, mtime, name_length, body_length)
- Section name is null-terminated
- Body follows immediately after the null byte

The layout after the 6-byte magic is: dev(6) + ino(6) + mode(6) + uid(6) +
gid(6) + nlinks(6) + rdev(6) + mtime(11) + namesize(6) + filesize(11) = 70
bytes, for a total header of 76 bytes. Name size is at offset 59 (6 octal
digits), file size at offset 65 (11 octal digits).

The final section is named `TRAILER!!!` and signals the end of the archive.

## Top-Level Sections

| Section | Content |
|---------|---------|
| `.start` | Playback settings, frame range, fps, units |
| `.variables` | Global variables (HIP, HIPNAME, JOB, save version, etc.) |
| `.aliases` | Command aliases |
| `.takeconfig` | Take system config |
| `.hou.session` | Python session code |
| `.OPlibraries` | HDA library references |
| `.OPpreferences` | Operator preferences |
| `.OPdummydefs` | Embedded HDA definitions (binary INDX blocks) |
| `expression.func` | Custom expression functions |
| `.application` | UI layout (viewport, panes, network editor state) |
| `.takes` | Take definitions |
| `.cwd` | Current working directory |
| `.custompanels` | Custom panel definitions |
| `TRAILER!!!` | End of archive marker |

## Node Context Sections

Houdini organizes nodes into contexts. Each context has a set of sections at
the top level:

| Context | Description |
|---------|-------------|
| `obj` | Object-level (geometry, cameras, lights, subnets) |
| `out` | Output/render (ROPs) |
| `ch` | CHOPs |
| `shop` | SHOPs (deprecated shaders) |
| `img` | COPs (compositing) |
| `vex` | VEX builders |
| `mat` | Materials |
| `stage` | LOPs/Solaris (USD) |
| `part` | POPs (legacy particles) |

Each context has these sections:
- `<ctx>.def` — context-level definition (flags, position, etc.)
- `<ctx>.spare` — spare parameters
- `<ctx>.parm` — parameter values
- `<ctx>.net` — child count (integer)
- `<ctx>.order` — child node order (newline-separated list)
- `<ctx>.userdata` — binary user data block

## Node Sections

Each node is identified by its **path** relative to the archive root. The path
uses `/` separators. Node sections follow this pattern:

| Section | Purpose |
|---------|---------|
| `<path>.init` | Node type declaration: `type = <type_name>` |
| `<path>.def` | Node definition: flags, position, connections, metadata |
| `<path>.spare` | Spare parameter definitions |
| `<path>.parm` | Parameter values |
| `<path>.chn` | Channel (animation) data |
| `<path>.userdata` | Binary user data |
| `<path>.inp` | Input connection layout (UI positioning) |
| `<path>.net` | Number of child nodes (integer) |
| `<path>.order` | Child node order (newline-separated names) |
| `<path>.gdelta` | Geometry delta (JSON, for edit SOPs) |
| `<path>.cop2` | COP2-specific data |

### Path Examples

```
obj/geo1.init                  → /obj/geo1 (object-level geo node)
obj/geo1/box1.init             → /obj/geo1/box1 (SOP inside geo1)
obj/geo1/box1.def              → definition for box1
img/comp1/color1.parm          → parameters for /img/comp1/color1
```

## .init Section Format

```
type = <node_type>
matchesdef = 0|1
```

`type` is the operator type name (e.g., `geo`, `box`, `grid`, `edit`,
`attribcreate`, `cop2net`, `subnet`, `mantra`).

`matchesdef` indicates whether the node matches its operator definition defaults.

## .def Section Format

The `.def` section contains node metadata in a line-oriented format:

```
sopflags sopflags =          (SOP-specific flags, optional)
objflags objflags = ...      (OBJ-specific flags, optional)
comment "<text>"
position <x> <y>
cachesize <n>
connectornextid <n>
flags = lock off model off template off ... display on render on ...
outputsNamed3
{
<idx> "<name>"
...
}
inputsNamed3
{
<idx> <TAB> <source_node> <source_output> <flag> "<input_name>"
...
}
inputs
{
<idx> <TAB> <source_node> <source_output> <flag>
...
}
stat
{
  create <timestamp>
  modify <timestamp>
  author <user>@<host>
  access <mode>
}
color UT_Color RGB <r> <g> <b>
delscript "<script>"
exprlanguage hscript|python
end
```

### Connection Format (inputs block)

The `inputs` block defines which nodes connect to this node's inputs:

```
inputs
{
<input_index> <TAB> <source_node_name> <source_output_index> <flag>
}
```

- `input_index`: 0-based index of this node's input
- `source_node_name`: name of the node whose output connects here (sibling)
- `source_output_index`: 0-based output index on the source node
- `flag`: usually `1`

An empty string `""` means the input is disconnected.

The `inputsNamed3` block adds named connectors and is the more modern format.

## .parm Section Format

Parameters are enclosed in `{ }` braces:

```
{
version 0.8
<parm_name>  [ <channel_flags> locks=<n> ]  ( <value1> <value2> ... )
<parm_name>  ( <value> )
}
```

- `version 0.8` is always the first line
- Parameter values are tab-separated inside `( )`
- String values are quoted: `( "string value" )`
- Numeric values are unquoted: `( 1.5 )` or `( 0 1 0 )`
- Multi-component params (vectors): `( <x> <y> <z> )`
- The `[ 0 locks=0 ]` annotation indicates channel reference flags

## .order Section Format

Lists child node names, one per line, preceded by the count:

```
<count>
<child_name_1>
<child_name_2>
...
```

## Signal vs. Noise

**Signal** (useful for pattern extraction):
- `.init` — node types
- `.def` — connections (inputs/inputsNamed3 blocks)
- `.parm` — non-default parameter values
- `.order` — child ordering
- Node path hierarchy — network structure

**Noise** (skip for pattern extraction):
- `.application` — UI layout, viewport state
- `.aliases` — command aliases
- `.start` — playback settings
- `.variables` — mostly environment paths
- `.takeconfig` — take system state
- `stat {}` blocks — creation timestamps
- `position` values — visual layout coordinates
- `flags` — mostly UI state (lock, template, xray, etc.)
- `.gdelta` — geometry edit deltas (huge, node-specific)
- `.userdata` — binary metadata
