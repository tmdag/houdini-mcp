"""Cross-platform guards.

Nobody has run this on Windows. These pin the decisions that were wrong
when the 2026-09 audit looked: Documents redirection, lexical version
sorting, SO_REUSEADDR semantics, and Linux-only screenshot tooling.
"""
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
sys.path.insert(0, os.path.join(_ROOT, "src"))

import install as install_script  # noqa: E402
import launch as launch_script  # noqa: E402
from houdinimcp import desktop  # noqa: E402


class TestVersionSorting:
    """sorted(reverse=True) on strings ranks houdini9.5 above houdini22.0."""

    def test_install_orders_numerically(self):
        names = ["houdini9.5", "houdini22.0", "houdini20.5", "houdini19.5"]
        ordered = sorted(names, key=install_script.version_key)
        assert ordered == ["houdini9.5", "houdini19.5", "houdini20.5", "houdini22.0"]

    def test_install_newest_picks_the_highest_version(self):
        assert install_script.newest(
            ["/h/houdini9.5", "/h/houdini22.0", "/h/houdini20.5"]
        ) == "/h/houdini22.0"

    def test_install_newest_handles_windows_style_names(self):
        assert install_script.newest(
            ["/pf/Houdini 9.5.100", "/pf/Houdini 22.0.429"]
        ) == "/pf/Houdini 22.0.429"

    def test_install_newest_of_nothing_is_none(self):
        assert install_script.newest([]) is None

    def test_launch_orders_numerically(self):
        ordered = launch_script.version_sorted(
            ["hfs9.5", "hfs22.0", "hfs20.5"]
        )
        assert ordered[0] == "hfs22.0"

    def test_launch_tolerates_unversioned_names(self):
        ordered = launch_script.version_sorted(["hfs22.0", "README", "hfs20.5"])
        assert ordered[0] == "hfs22.0"
        assert "README" in ordered


class TestPrefsDirResolution:
    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("HOUDINI_USER_PREF_DIR", "/custom/prefs")
        assert install_script.find_houdini_prefs() == "/custom/prefs"

    def test_env_override_expands_hver(self, monkeypatch):
        monkeypatch.setenv("HOUDINI_USER_PREF_DIR", "/custom/hou__HVER__")
        assert install_script.find_houdini_prefs("22.0") == "/custom/hou22.0"

    def test_windows_prefers_the_real_documents_folder(self, monkeypatch, tmp_path):
        """OneDrive moves Documents; ~/Documents can exist and be the wrong one."""
        home = tmp_path
        (home / "Documents").mkdir()
        (home / "OneDrive" / "Documents").mkdir(parents=True)
        (home / "OneDrive" / "Documents" / "houdini22.0").mkdir()
        # No winreg on this platform, so the OneDrive fallback is what runs.
        resolved = install_script.windows_documents_dir(str(home))
        assert resolved == str(home / "OneDrive" / "Documents")

    def test_windows_falls_back_to_plain_documents(self, tmp_path):
        (tmp_path / "Documents").mkdir()
        assert install_script.windows_documents_dir(str(tmp_path)) == str(
            tmp_path / "Documents"
        )

    def test_prefs_base_is_platform_correct(self, tmp_path):
        home = str(tmp_path)
        assert install_script.prefs_base("Linux", home) == home
        assert install_script.prefs_base("Darwin", home).endswith(
            os.path.join("Library", "Preferences", "houdini")
        )

    def test_python_lib_dirs_cover_h19_through_h22(self):
        source = open(os.path.join(_ROOT, "scripts", "install.py")).read()
        for version in ("3.9", "3.10", "3.11", "3.12", "3.13"):
            assert f'"{version}"' in source, f"python{version}libs not covered"


class TestSocketOptions:
    def test_win32_uses_exclusiveaddruse_not_reuseaddr(self):
        """On Win32 SO_REUSEADDR lets a second process steal the port."""
        source = open(os.path.join(_ROOT, "src", "houdinimcp", "server.py")).read()
        assert "SO_EXCLUSIVEADDRUSE" in source
        bind_block = source[source.index("def start(self)"):]
        bind_block = bind_block[:bind_block.index("self.socket = sock")]
        assert 'sys.platform == "win32"' in bind_block


class TestDesktopCapture:
    def test_every_platform_has_a_grabber(self):
        for platform_name in ("win32", "darwin", "linux"):
            assert hasattr(desktop, "_grab_commands")

    def test_windows_uses_powershell(self, monkeypatch):
        monkeypatch.setattr(desktop.sys, "platform", "win32")
        monkeypatch.setattr(desktop.shutil, "which",
                            lambda name: "C:\\ps\\%s.exe" % name)
        commands, _ = desktop._grab_commands("C:\\tmp\\shot.png")
        assert commands, "Windows must have a capture path"
        assert "powershell" in commands[0][0].lower()
        assert "CopyFromScreen" in commands[0][-1]

    def test_windows_without_powershell_says_so(self, monkeypatch):
        monkeypatch.setattr(desktop.sys, "platform", "win32")
        monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
        commands, message = desktop._grab_commands("C:\\tmp\\shot.png")
        assert commands == []
        assert "PowerShell" in message

    def test_windows_path_quoting_is_escaped(self, monkeypatch):
        monkeypatch.setattr(desktop.sys, "platform", "win32")
        monkeypatch.setattr(desktop.shutil, "which", lambda name: "powershell")
        commands, _ = desktop._grab_commands("C:\\tmp\\it's here.png")
        assert "it''s here.png" in commands[0][-1]

    def test_macos_uses_screencapture(self, monkeypatch):
        monkeypatch.setattr(desktop.sys, "platform", "darwin")
        monkeypatch.setattr(desktop.shutil, "which",
                            lambda name: "/usr/sbin/" + name)
        commands, _ = desktop._grab_commands("/tmp/shot.png")
        assert commands[0][0].endswith("screencapture")
        assert "/tmp/shot.png" in commands[0]

    def test_macos_permission_denial_is_classified(self, monkeypatch):
        monkeypatch.setattr(desktop.sys, "platform", "darwin")
        payload = desktop.desktop_error_payload(
            RuntimeError("screencapture: cannot run, not authorized")
        )
        assert payload["code"] == "permission_denied"
        assert "capture_screenshot" in payload["message"]

    def test_windows_failure_is_not_called_a_portal_denial(self, monkeypatch):
        """Wayland vocabulary on Windows is nonsense."""
        monkeypatch.setattr(desktop.sys, "platform", "win32")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        payload = desktop.desktop_error_payload(RuntimeError("Access is denied"))
        assert payload.get("code") != "portal_denied"


class TestNoHardcodedPosixPaths:
    """Runtime code must not assume /tmp or /opt."""

    RUNTIME_FILES = [
        os.path.join(_ROOT, "houdini_mcp_server.py"),
        os.path.join(_ROOT, "src", "houdinimcp", "server.py"),
        os.path.join(_ROOT, "src", "houdinimcp", "desktop.py"),
    ]

    def test_no_literal_tmp_paths(self):
        for path in self.RUNTIME_FILES:
            for number, line in enumerate(open(path), 1):
                if line.lstrip().startswith("#"):
                    continue
                assert not re.search(r'["\']/tmp/', line), (
                    "%s:%d hardcodes /tmp; use tempfile.gettempdir()"
                    % (os.path.basename(path), number)
                )
