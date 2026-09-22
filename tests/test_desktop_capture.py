"""#15: Wayland portal denial is a clear error, not a generic failure."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from houdinimcp.desktop import desktop_error_payload


def test_portal_denied_message():
    payload = desktop_error_payload(
        RuntimeError("org.freedesktop.DBus.Error.AccessDenied: portal"),
        "xdg-desktop-portal: ScreenCast denied",
    )
    assert payload["code"] == "portal_denied"
    assert payload["message"] == "portal denied, use capture_screenshot"


def test_generic_desktop_error_not_portal(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    payload = desktop_error_payload(RuntimeError("No screenshot tool on PATH"))
    assert payload.get("code") != "portal_denied"
    assert "desktop capture failed" in payload["message"]


def test_wayland_session_is_portal_denied(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    payload = desktop_error_payload(RuntimeError("import: exit 1"))
    assert payload["code"] == "portal_denied"
    assert payload["message"] == "portal denied, use capture_screenshot"

