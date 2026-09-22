"""OS-level Houdini window grab. Runs on the stdio bridge, not inside houdini-bin."""
import os
import shutil
import subprocess
import sys

_PORTAL_MARKERS = (
    "accessdenied",
    "org.freedesktop.impl.portal",
    "xdg-desktop-portal",
    "screencast",
    "permission denied",
    "portal",
    "not authorized",
    "user denied",
    "wayland",
    "xgetimage",
    "cannot capture",
)

# macOS refuses the grab until Houdini (or the terminal running the bridge)
# is granted Screen Recording in System Settings > Privacy & Security.
_MACOS_PERMISSION_MARKERS = (
    "not authorized",
    "screen recording",
    "not permitted",
    "cannot be captured",
)


def desktop_error_payload(exc, stderr=""):
    """Classify a desktop-grab failure.

    A denied screen-capture permission is not a beauty-path failure, it is
    an OS prompt the user has to answer -- say so instead of blaming the
    renderer.
    """
    text = ("%s %s" % (exc, stderr or "")).strip()
    lowered = text.lower()

    if sys.platform == "darwin":
        if any(m in lowered for m in _MACOS_PERMISSION_MARKERS):
            return {
                "status": "error",
                "code": "permission_denied",
                "message": (
                    "screen recording permission denied, use capture_screenshot"
                ),
                "detail": text[:500],
                "source": "desktop",
            }
    elif sys.platform != "win32":
        wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        if wayland or any(m in lowered for m in _PORTAL_MARKERS):
            return {
                "status": "error",
                "code": "portal_denied",
                "message": "portal denied, use capture_screenshot",
                "detail": text[:500],
                "source": "desktop",
            }

    return {
        "status": "error",
        "message": "desktop capture failed: %s" % (text[:500] or exc),
        "source": "desktop",
    }


# PowerShell is the only screen grabber guaranteed to be on a Windows box.
_WINDOWS_GRAB = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$area = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $area.Width, $area.Height
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.CopyFromScreen($area.Location, [System.Drawing.Point]::Empty, $area.Size)
$bmp.Save('{path}', [System.Drawing.Imaging.ImageFormat]::Png)
$gfx.Dispose()
$bmp.Dispose()
"""


def _windows_commands(output_path):
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        return []
    script = _WINDOWS_GRAB.replace("{path}", output_path.replace("'", "''"))
    return [[shell, "-NoProfile", "-NonInteractive", "-Command", script]]


def _macos_commands(output_path):
    # -x silences the shutter sound; -o drops the window shadow.
    screencapture = shutil.which("screencapture")
    if not screencapture:
        return []
    return [[screencapture, "-x", output_path]]


def _linux_commands(output_path):
    commands = []
    if shutil.which("grim"):
        commands.append(["grim", output_path])
    if shutil.which("import"):
        wid = None
        if shutil.which("xdotool"):
            try:
                found = subprocess.check_output(
                    ["xdotool", "search", "--class", "Houdini"],
                    text=True, timeout=3,
                ).strip().splitlines()
                if found:
                    wid = found[-1]
            except Exception:
                wid = None
        if wid:
            commands.append(["import", "-window", wid, output_path])
        commands.append(["import", "-window", "root", output_path])
    if shutil.which("gnome-screenshot"):
        commands.append(["gnome-screenshot", "-f", output_path])
    if shutil.which("spectacle"):
        commands.append(["spectacle", "-b", "-n", "-f", "-o", output_path])
    return commands


def _grab_commands(output_path):
    if sys.platform == "win32":
        return _windows_commands(output_path), (
            "PowerShell not found on PATH -- it is required for capture_desktop "
            "on Windows"
        )
    if sys.platform == "darwin":
        return _macos_commands(output_path), (
            "screencapture not found on PATH (it ships with macOS)"
        )
    return _linux_commands(output_path), (
        "No desktop screenshot tool on PATH (need grim, ImageMagick "
        "`import`, gnome-screenshot, or spectacle)"
    )


def grab_houdini_window(output_path):
    """OS-level grab of the Houdini window. Must not run inside houdini-bin."""
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    commands, no_tool_message = _grab_commands(output_path)
    if not commands:
        raise RuntimeError(no_tool_message)

    last_err = None
    last_stderr = ""
    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd, timeout=30, capture_output=True, text=True,
            )
            if proc.returncode == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                return {
                    "status": "success",
                    "filepath": output_path,
                    "bytes": os.path.getsize(output_path),
                    "cmd": cmd,
                    "source": "desktop",
                }
            last_stderr = (proc.stderr or proc.stdout or "").strip()
            last_err = RuntimeError(
                last_stderr or "exit %s from %s" % (proc.returncode, cmd)
            )
        except Exception as e:
            last_err = e
            last_stderr = str(e)

    payload = desktop_error_payload(last_err, last_stderr)
    if payload.get("code"):
        raise RuntimeError(payload["message"] + " — " + payload.get("detail", ""))
    raise RuntimeError(payload["message"])
