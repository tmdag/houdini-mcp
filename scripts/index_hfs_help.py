#!/usr/bin/env python3
"""Index THIS Houdini install's help (H22 $HFS/houdini/help).

Does not clone random GitHub dumps. Extracts hom.zip + nodes.zip into
gitignored houdini_docs/ and builds houdini_docs_index.json.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "houdini_docs"
INDEX = REPO / "houdini_docs_index.json"

# hom.zip + nodes.zip alone left the corpus with no VEX function reference at
# all -- `setprimintrinsic` had 0 hits -- so writing VEX got no doc support.
# vex.zip ships functions/*.txt for the whole language. images.zip is 324MB of
# screenshots and is deliberately excluded.
ZIPS = (
    "hom.zip",          # Python / HOM
    "nodes.zip",        # every node's reference page
    "vex.zip",          # VEX language + functions/
    "expressions.zip",  # HScript expression functions
    "commands.zip",     # HScript commands
    "model.zip",        # modelling concepts (UVs, attributes, groups)
    "shade.zip",        # shading / materials
    "solaris.zip",      # LOPs / USD
    "props.zip",        # render + USD properties
    "ref.zip",          # reference: env vars, file formats
    "io.zip",           # import/export
    "render.zip",       # Karma / Mantra
    "dyno.zip",         # DOPs
    "tops.zip",         # PDG
)


def _newest_first(paths):
    """Numeric version order. A plain reverse string sort puts hfs22.0.9
    ahead of hfs22.0.43."""
    def key(path):
        numbers = re.findall(r"\d+", path.name)
        return tuple(int(n) for n in numbers) if numbers else (0,)
    return sorted(paths, key=key, reverse=True)


def find_hfs() -> Path:
    env = os.environ.get("HFS")
    if env and Path(env, "houdini", "help").is_dir():
        return Path(env)
    for p in _newest_first(Path("/opt").glob("hfs22.0*")):
        if (p / "houdini" / "help").is_dir() and not p.is_symlink():
            return p
        if (p / "houdini" / "help").is_dir():
            return p.resolve()
    raise SystemExit("HFS not found. Set HFS or install Houdini 22 under /opt/hfs22.0*")


def extract(hfs: Path) -> None:
    helpdir = hfs / "houdini" / "help"
    DOCS.mkdir(parents=True, exist_ok=True)
    for name in ZIPS:
        zpath = helpdir / name
        if not zpath.is_file():
            print("skip missing", zpath)
            continue
        dest = DOCS / zpath.stem
        # extractall never removes files the new archive dropped, so a
        # re-index after a Houdini upgrade kept indexing deleted help pages.
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        print("extract", zpath, "->", dest)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(dest)
    # loose txt at help root
    root_txt = DOCS / "_root"
    root_txt.mkdir(exist_ok=True)
    for txt in helpdir.glob("*.txt"):
        target = root_txt / txt.name
        target.write_bytes(txt.read_bytes())


def main() -> None:
    hfs = find_hfs()
    print("HFS", hfs)
    extract(hfs)
    sys.path.insert(0, str(REPO))
    os.environ["HOUDINIMCP_DOCS_DIR"] = str(DOCS)
    os.environ["HOUDINIMCP_DOCS_INDEX"] = str(INDEX)
    from houdini_rag import build_index

    build_index(docs_dir=str(DOCS), output_path=str(INDEX))
    mb = INDEX.stat().st_size / (1024 * 1024)
    print("index", INDEX, f"{mb:.1f} MB")


if __name__ == "__main__":
    main()
