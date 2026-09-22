"""Tests for scripts/ingest_hips.py — Houdini install detection & .hip discovery."""
import os
import sys
import tempfile

import pytest

# scripts/ is not a package — add it to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from ingest_hips import find_houdini_install, discover_hip_files


# ---------------------------------------------------------------------------
# find_houdini_install
# ---------------------------------------------------------------------------
class TestFindHoudiniInstall:
    def test_hfs_dir_arg_valid(self, tmp_path):
        """Explicit --hfs-dir that exists is returned."""
        result = find_houdini_install(hfs_dir=str(tmp_path))
        assert result == str(tmp_path)

    def test_hfs_dir_arg_missing(self):
        """Explicit --hfs-dir that doesn't exist returns None."""
        result = find_houdini_install(hfs_dir="/nonexistent/hfs99.9")
        assert result is None

    def test_hfs_env_var(self, tmp_path, monkeypatch):
        """$HFS env var pointing to a valid dir is returned."""
        monkeypatch.setenv("HFS", str(tmp_path))
        result = find_houdini_install()
        assert result == str(tmp_path)

    def test_hfs_env_var_invalid(self, monkeypatch):
        """$HFS set but dir doesn't exist — falls through."""
        monkeypatch.setenv("HFS", "/nonexistent/hfs")
        monkeypatch.setattr("ingest_hips.glob.glob", lambda p, **kw: [])
        result = find_houdini_install()
        assert result is None

    def test_platform_glob_linux(self, tmp_path, monkeypatch):
        """Linux glob /opt/hfs* returns newest."""
        monkeypatch.delenv("HFS", raising=False)
        monkeypatch.setattr("ingest_hips.platform.system", lambda: "Linux")

        dir1 = str(tmp_path / "hfs20.0")
        dir2 = str(tmp_path / "hfs21.0")
        os.makedirs(dir1)
        os.makedirs(dir2)

        # sorted reverse → dir2 first
        monkeypatch.setattr("ingest_hips.glob.glob", lambda p, **kw: sorted([dir1, dir2], reverse=True))
        result = find_houdini_install()
        assert result == dir2

    def test_platform_glob_darwin(self, tmp_path, monkeypatch):
        """macOS glob picks newest."""
        monkeypatch.delenv("HFS", raising=False)
        monkeypatch.setattr("ingest_hips.platform.system", lambda: "Darwin")

        d = str(tmp_path / "Houdini21.0.123")
        os.makedirs(d)
        monkeypatch.setattr("ingest_hips.glob.glob", lambda p, **kw: [d])
        result = find_houdini_install()
        assert result == d

    def test_platform_glob_windows(self, tmp_path, monkeypatch):
        """Windows glob picks newest."""
        monkeypatch.delenv("HFS", raising=False)
        monkeypatch.setattr("ingest_hips.platform.system", lambda: "Windows")

        d = str(tmp_path / "Houdini 21.0")
        os.makedirs(d)
        monkeypatch.setattr("ingest_hips.glob.glob", lambda p, **kw: [d])
        result = find_houdini_install()
        assert result == d

    def test_nothing_found(self, monkeypatch):
        """No env, no glob matches → None."""
        monkeypatch.delenv("HFS", raising=False)
        monkeypatch.setattr("ingest_hips.glob.glob", lambda p, **kw: [])
        result = find_houdini_install()
        assert result is None


# ---------------------------------------------------------------------------
# discover_hip_files
# ---------------------------------------------------------------------------
class TestDiscoverHipFiles:
    def _make_tree(self, base, files):
        """Create files in a directory tree. files is a list of relative paths."""
        for rel in files:
            full = os.path.join(base, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write("dummy")

    def test_finds_hip_and_hda(self, tmp_path):
        """Discovers .hip, .hipnc, .hda, .otl under $HFS subdirs."""
        hfs = str(tmp_path / "hfs")
        self._make_tree(hfs, [
            "houdini/help/examples/sop/box.hip",
            "houdini/help/examples/sop/scatter.hipnc",
            "houdini/otls/custom.hda",
            "packages/demo/legacy.otl",
            "houdini/help/examples/sop/readme.txt",  # should be ignored
        ])
        results = discover_hip_files(hfs)
        assert len(results) == 4
        types = {r["type"] for r in results}
        assert types == {"hip", "hda"}

    def test_file_entry_fields(self, tmp_path):
        """Each entry has path, type, size, rel_dir."""
        hfs = str(tmp_path / "hfs")
        self._make_tree(hfs, ["houdini/help/sop/box.hip"])
        results = discover_hip_files(hfs)
        assert len(results) == 1
        entry = results[0]
        assert set(entry.keys()) == {"path", "type", "size", "rel_dir"}
        assert entry["type"] == "hip"
        assert entry["size"] > 0
        assert entry["rel_dir"] == "sop"

    def test_extra_dirs(self, tmp_path):
        """--extra-dir paths are also scanned."""
        hfs = str(tmp_path / "hfs")
        extra = str(tmp_path / "my_hips")
        self._make_tree(hfs, ["houdini/help/sop/box.hip"])
        self._make_tree(extra, ["project/scene.hip"])

        results = discover_hip_files(hfs, extra_dirs=[extra])
        assert len(results) == 2

    def test_no_known_subdirs(self, tmp_path):
        """hfs_path with no known subdirs returns empty list."""
        hfs = str(tmp_path / "hfs")
        os.makedirs(hfs)
        results = discover_hip_files(hfs)
        assert results == []

    def test_extra_dir_missing(self, tmp_path):
        """Non-existent extra dir is silently skipped."""
        hfs = str(tmp_path / "hfs")
        os.makedirs(hfs)
        results = discover_hip_files(hfs, extra_dirs=["/nonexistent/dir"])
        assert results == []

    def test_nested_subdirectories(self, tmp_path):
        """Files in deeply nested dirs are found."""
        hfs = str(tmp_path / "hfs")
        self._make_tree(hfs, [
            "houdini/help/a/b/c/deep.hip",
            "houdini/help/x/flat.hipnc",
        ])
        results = discover_hip_files(hfs)
        assert len(results) == 2
        rel_dirs = {r["rel_dir"] for r in results}
        assert os.path.join("a", "b", "c") in rel_dirs
        assert "x" in rel_dirs

    def test_multiple_subdirs(self, tmp_path):
        """Files from multiple $HFS subdirs are all discovered."""
        hfs = str(tmp_path / "hfs")
        self._make_tree(hfs, [
            "houdini/help/examples/box.hip",
            "houdini/otls/tools.hda",
            "packages/demo/scene.hip",
            "toolkit/samples/test.hipnc",
            "engine/examples/export.hip",
        ])
        results = discover_hip_files(hfs)
        assert len(results) == 5

    def test_extra_only_skips_hfs(self, tmp_path):
        """--extra-only must not walk $HFS help/otls."""
        hfs = str(tmp_path / "hfs")
        extra = str(tmp_path / "my_hips")
        self._make_tree(hfs, [
            "houdini/help/examples/box.hip",
            "houdini/otls/tools.hda",
        ])
        self._make_tree(extra, ["project/scene.hipnc"])
        results = discover_hip_files(hfs, extra_dirs=[extra], extra_only=True)
        assert len(results) == 1
        assert results[0]["path"].endswith("scene.hipnc")
        assert all("houdini/help" not in r["path"] for r in results)
        assert all("houdini/otls" not in r["path"] for r in results)
