#!/usr/bin/env python3
"""
install.py — Set up HoudiniMCP for automatic loading in Houdini.

This script:
1. Detects the Houdini user preferences directory
2. Copies the plugin files to the scripts/python/houdinimcp/ directory
3. Creates a packages JSON file so Houdini auto-loads the plugin at startup

Usage:
    python install.py                    # Auto-detect Houdini version
    python install.py --houdini-version 20.5  # Specify Houdini version
    python install.py --prefs-dir /path/to/houdiniX.Y  # Explicit prefs directory
    python install.py --claude-code      # Also auto-allow Houdini MCP tools in Claude Code
    python install.py --dry-run          # Show what would be done without doing it
"""
import os
import sys
import shutil
import json
import argparse
import platform
import glob
import re


PLUGIN_FILES = [
    "src/houdinimcp/__init__.py",
    "src/houdinimcp/server.py",
    "src/houdinimcp/framing.py",
    "src/houdinimcp/HoudiniMCPRender.py",
    "src/houdinimcp/claude_terminal.py",
    "src/houdinimcp/event_collector.py",
]
HANDLER_DIR = "src/houdinimcp/handlers"
PANEL_FILES = [
    "src/houdinimcp/ClaudeTerminal.pypanel",
]
SHELF_FILES = [
    "src/houdinimcp/houdinimcp.shelf",
]
PACKAGE_NAME = "houdinimcp"


def version_key(name):
    """Numeric sort key for a versioned directory name.

    sorted(reverse=True) on strings picks houdini9.5 over houdini22.0, and
    "Houdini 9.5" over "Houdini 22.0.429".
    """
    numbers = re.findall(r"\d+", name)
    return tuple(int(n) for n in numbers) if numbers else (0,)


def newest(paths):
    """Highest-versioned path, or None.

    Keys on the whole path, not the basename: HOUDINI_USER_PREF_DIR can put
    the version in a middle component (/studio/prefs/houdini__HVER__/albert),
    where every basename is identical, every key was (0,), and the winner was
    whatever the glob happened to emit last -- often the oldest Houdini.
    """
    if not paths:
        return None
    return sorted(paths, key=version_key)[-1]


def windows_documents_dir(home):
    """The real Documents folder.

    Houdini follows the Windows "Personal" known folder. OneDrive and
    corporate folder redirection move it, while os.path.expanduser("~")
    does not -- so ~/Documents can be a path that exists but is not the
    one Houdini reads, and installing there succeeds silently and does
    nothing.
    """
    # "User Shell Folders" is the authoritative value (unexpanded, may hold
    # %USERPROFILE%). "Shell Folders" is Explorer's expanded cache and can
    # still name the pre-redirect directory after a OneDrive Known Folder
    # Move, which is exactly when getting this wrong matters.
    for subkey in ("User Shell Folders", "Shell Folders"):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                "\\".join((
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer",
                    subkey,
                )),
            )
            try:
                value, _ = winreg.QueryValueEx(key, "Personal")
            finally:
                winreg.CloseKey(key)
            value = os.path.expandvars(value or "")
            if value and os.path.isdir(value):
                return value
        except Exception:
            continue
    # Business OneDrive uses "OneDrive - <Tenant>", not plain "OneDrive".
    candidates = [os.path.join(home, "OneDrive", "Documents")]
    candidates += sorted(glob.glob(os.path.join(home, "OneDrive - *", "Documents")))
    candidates.append(os.path.join(home, "Documents"))
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(home, "Documents")


def prefs_base(system, home):
    """Directory that holds the per-version Houdini prefs directories."""
    if system == "Windows":
        return windows_documents_dir(home)
    if system == "Darwin":
        return os.path.join(home, "Library", "Preferences", "houdini")
    return home


def find_houdini_prefs(houdini_version=None):
    """Find the Houdini user preferences directory.

    HOUDINI_USER_PREF_DIR wins: it is SideFX's documented override and the
    only correct answer on a machine that sets it.
    """
    system = platform.system()
    home = os.path.expanduser("~")

    override = os.environ.get("HOUDINI_USER_PREF_DIR", "").strip()
    if override:
        # Houdini expands __HVER__ to the version inside this variable.
        if houdini_version:
            return override.replace("__HVER__", houdini_version)
        if "__HVER__" not in override:
            return override
        expanded = newest(glob.glob(override.replace("__HVER__", "*")))
        if expanded:
            return expanded
        # Nothing on disk yet (first install). Falling through to the $HOME
        # scan here reported success into ~/houdiniX.Y while Houdini read the
        # override path and never loaded the plugin -- the same silent no-op
        # this function exists to prevent. Make the caller say which version.
        raise SystemExit(
            "HOUDINI_USER_PREF_DIR=%s contains __HVER__ but nothing matches "
            "it yet.\nPass --houdini-version (e.g. --houdini-version 22.0) "
            "so the path can be resolved." % override
        )

    base = prefs_base(system, home)

    if houdini_version:
        leaf = houdini_version if system == "Darwin" else f"houdini{houdini_version}"
        # Returned even when absent: a first install has to create it.
        return os.path.join(base, leaf)

    pattern = "[0-9]*.[0-9]*" if system == "Darwin" else "houdini[0-9]*.[0-9]*"
    return newest([p for p in glob.glob(os.path.join(base, pattern))
                   if os.path.isdir(p)])


def install(prefs_dir, source_dir, dry_run=False):
    """Install plugin files and create the packages JSON."""
    plugin_dest = os.path.join(prefs_dir, "scripts", "python", PACKAGE_NAME)
    packages_dir = os.path.join(prefs_dir, "packages")

    print(f"Source directory:  {source_dir}")
    print(f"Plugin install to: {plugin_dest}")
    print(f"Package config:    {os.path.join(packages_dir, f'{PACKAGE_NAME}.json')}")
    print()

    # Copy plugin files
    if not dry_run:
        os.makedirs(plugin_dest, exist_ok=True)

    for filepath in PLUGIN_FILES:
        src = os.path.join(source_dir, filepath)
        dst = os.path.join(plugin_dest, os.path.basename(filepath))
        if not os.path.isfile(src):
            print(f"  SKIP {filepath} (not found in source)")
            continue
        if dry_run:
            print(f"  COPY {src} -> {dst}")
        else:
            shutil.copy2(src, dst)
            print(f"  Copied {os.path.basename(filepath)}")

    # Copy handlers/ directory
    handlers_src = os.path.join(source_dir, HANDLER_DIR)
    handlers_dest = os.path.join(plugin_dest, "handlers")
    if os.path.isdir(handlers_src):
        if dry_run:
            print(f"  COPY {handlers_src}/ -> {handlers_dest}/")
        else:
            if os.path.exists(handlers_dest):
                shutil.rmtree(handlers_dest)
            shutil.copytree(handlers_src, handlers_dest)
            handler_count = sum(1 for f in os.listdir(handlers_dest) if f.endswith('.py'))
            print(f"  Copied handlers/ ({handler_count} modules)")

    # Copy .pypanel files to Houdini's python_panels directory
    panels_dest = os.path.join(prefs_dir, "python_panels")
    if not dry_run:
        os.makedirs(panels_dest, exist_ok=True)
    for filepath in PANEL_FILES:
        src = os.path.join(source_dir, filepath)
        dst = os.path.join(panels_dest, os.path.basename(filepath))
        if not os.path.isfile(src):
            print(f"  SKIP {filepath} (not found in source)")
            continue
        if dry_run:
            print(f"  COPY {src} -> {dst}")
        else:
            shutil.copy2(src, dst)
            print(f"  Copied {os.path.basename(filepath)} -> python_panels/")

    # Copy .shelf files to Houdini's toolbar directory
    toolbar_dest = os.path.join(prefs_dir, "toolbar")
    if not dry_run:
        os.makedirs(toolbar_dest, exist_ok=True)
    for filepath in SHELF_FILES:
        src = os.path.join(source_dir, filepath)
        dst = os.path.join(toolbar_dest, os.path.basename(filepath))
        if not os.path.isfile(src):
            print(f"  SKIP {filepath} (not found in source)")
            continue
        if dry_run:
            print(f"  COPY {src} -> {dst}")
        else:
            shutil.copy2(src, dst)
            print(f"  Copied {os.path.basename(filepath)} -> toolbar/")

    # Create packages JSON
    # Use forward slashes for cross-platform Houdini compatibility
    python_scripts_dir = os.path.join(prefs_dir, "scripts", "python").replace("\\", "/")
    # Do NOT set package "path" to the Python package dir — Houdini would
    # prepend it onto HOUDINI_PATH and search it for config/Applications
    # (that polluted path contributed to an H22 OPUI_ShelfDock.ui crash).
    package_json = {
        "load_package_once": True,
        "version": "0.2",
        "env": [
            {
                "PYTHONPATH": {
                    "value": python_scripts_dir,
                    "method": "append",
                }
            }
        ]
    }

    package_file = os.path.join(packages_dir, f"{PACKAGE_NAME}.json")
    if dry_run:
        print(f"\n  WRITE {package_file}:")
        print(f"  {json.dumps(package_json, indent=2)}")
    else:
        os.makedirs(packages_dir, exist_ok=True)
        with open(package_file, "w") as f:
            json.dump(package_json, f, indent=2)
        print(f"\n  Created package file: {package_file}")

    # Write MCP config so Claude Code launched from Houdini gets MCP tools.
    # Prefer the repo's own interpreter: it is an absolute path that works
    # from any cwd, and a bare "uv" needs uv.exe resolvable from whatever
    # environment Houdini hands to the terminal.
    venv_python = os.path.join(
        source_dir, ".venv",
        "Scripts" if platform.system() == "Windows" else "bin",
        "python.exe" if platform.system() == "Windows" else "python",
    )
    bridge = os.path.join(source_dir, "houdini_mcp_server.py")
    if os.path.isfile(venv_python):
        command, args = venv_python, [bridge]
    else:
        command, args = "uv", ["--directory", source_dir, "run", "python", bridge]
    mcp_config = {
        "mcpServers": {
            "houdini": {"command": command, "args": args}
        }
    }
    mcp_config_path = os.path.join(plugin_dest, "mcp.json")
    if dry_run:
        print(f"  WRITE {mcp_config_path}")
    else:
        with open(mcp_config_path, "w") as f:
            json.dump(mcp_config, f, indent=2)
            f.write("\n")
        print(f"  Created MCP config: {mcp_config_path}")

    # Houdini does not run scripts/pythonrc.py. The UI-ready hook is
    # pythonX.Ylibs/uiready.py (QTimer needs the UI).
    uiready_body = (
        '"""Start HoudiniMCP after the UI exists."""\n'
        "try:\n"
        "    import houdinimcp\n"
        "    houdinimcp.start_server()\n"
        "except Exception as e:\n"
        "    import sys\n"
        "    sys.stderr.write('HoudiniMCP uiready failed: %s\\n' % (e,))\n"
    )
    # Houdini reads only the directory matching its own interpreter, so
    # writing all of them is harmless and survives a version bump.
    # H19.5=3.9, H20.0=3.10, H20.5=3.11, H21=3.11/3.12, H22=3.13.
    pyver_dirs = [
        os.path.join(prefs_dir, f"python{v}libs")
        for v in ("3.13", "3.12", "3.11", "3.10", "3.9")
    ]
    for py_dir in pyver_dirs:
        uiready_path = os.path.join(py_dir, "uiready.py")
        if dry_run:
            print(f"  WRITE {uiready_path}")
            continue
        os.makedirs(py_dir, exist_ok=True)
        with open(uiready_path, "w") as f:
            f.write(uiready_body)
        print(f"  Wrote {uiready_path}")

    scripts_dir = os.path.join(prefs_dir, "scripts")
    pythonrc_path = os.path.join(scripts_dir, "pythonrc.py")
    if os.path.isfile(pythonrc_path) and not dry_run:
        with open(pythonrc_path) as f:
            existing = f.read()
        if "import houdinimcp" in existing and "Dead file" not in existing:
            with open(pythonrc_path, "w") as f:
                f.write(
                    "# Dead file. Houdini never executes scripts/pythonrc.py.\n"
                    "# Auto-start lives in pythonX.Ylibs/uiready.py\n"
                )
            print(f"  Neutralized {pythonrc_path}")

    print("\nDone!" if not dry_run else "\nDry run complete — no files were changed.")
    if not dry_run:
        print("Restart Houdini for changes to take effect.")
        print("The MCP server will auto-start when Houdini loads the plugin.")


def main():
    parser = argparse.ArgumentParser(description="Install HoudiniMCP plugin for auto-loading")
    parser.add_argument("--houdini-version", default=None, help="Houdini version (e.g. 20.5)")
    parser.add_argument("--prefs-dir", default=None, help="Explicit Houdini preferences directory")
    parser.add_argument("--claude-code", action="store_true",
                        help="Auto-allow Houdini MCP tools in Claude Code (no per-tool prompts)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without doing it")
    args = parser.parse_args()

    # scripts/ is one level below the repo root
    source_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if args.prefs_dir:
        prefs_dir = args.prefs_dir
    else:
        prefs_dir = find_houdini_prefs(args.houdini_version)

    if not prefs_dir:
        print("Error: Could not find Houdini preferences directory.", file=sys.stderr)
        print("Use --houdini-version or --prefs-dir to specify it.", file=sys.stderr)
        sys.exit(1)

    print(f"Houdini prefs directory: {prefs_dir}\n")
    if not os.path.isdir(prefs_dir):
        print(
            f"Warning: {prefs_dir} does not exist yet.\n"
            "         If Houdini has already run on this machine, this is the\n"
            "         wrong directory -- OneDrive or folder redirection moves\n"
            "         Documents on Windows. Check Houdini's own answer with\n"
            "         hou.homeHoudiniDirectory() in its Python Shell, then pass\n"
            "         --prefs-dir or set HOUDINI_USER_PREF_DIR.\n",
            file=sys.stderr,
        )
    install(prefs_dir, source_dir, args.dry_run)

    if args.claude_code:
        configure_claude_code(args.dry_run)


def configure_claude_code(dry_run=False):
    """Add HoudiniMCP permissions to Claude Code's allowed tools."""
    settings_dir = os.path.join(os.path.expanduser("~"), ".claude")
    settings_file = os.path.join(settings_dir, "settings.json")

    import tempfile
    temp_glob = os.path.join(tempfile.gettempdir(), "*").replace("\\", "/")
    permissions = [
        "mcp__houdini__*",
        "Bash(mplay *)",
        f"Read({temp_glob})",
    ]
    if platform.system() != "Windows":
        permissions.append(f"Bash(ls -la {temp_glob})")

    if os.path.isfile(settings_file):
        with open(settings_file) as f:
            settings = json.load(f)
    else:
        settings = {}

    allow_list = settings.setdefault("permissions", {}).setdefault("allow", [])
    added = []
    for permission in permissions:
        if permission not in allow_list:
            added.append(permission)
            if not dry_run:
                allow_list.append(permission)

    if not added:
        print(f"\nClaude Code: All permissions already in {settings_file}")
        return

    if dry_run:
        for permission in added:
            print(f"\n  WOULD ADD '{permission}' to {settings_file}")
        return

    os.makedirs(settings_dir, exist_ok=True)
    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    for permission in added:
        print(f"  Claude Code: Added '{permission}' to {settings_file}")
    print("Houdini MCP tools and mplay will no longer require per-call approval.")


if __name__ == "__main__":
    main()
