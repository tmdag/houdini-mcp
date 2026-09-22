"""Bridge-side in-band image for capture_screenshot (issue #3)."""
import os
import json
import struct
import zlib

import pytest

try:
    # mcp >= 2.0: FastMCP became MCPServer, and _convert_to_content moved
    # from .server into .utilities.func_metadata.
    from mcp.server.mcpserver.utilities.func_metadata import _convert_to_content
    from mcp.server.mcpserver.utilities.types import Image
except ImportError:
    # mcp 1.x
    from mcp.server.fastmcp.server import _convert_to_content
    from mcp.server.fastmcp.utilities.types import Image
from mcp.types import ImageContent


def mime_of(content):
    """ImageContent.mimeType on mcp 1.x, .mime_type on 2.x."""
    return getattr(content, "mime_type", None) or getattr(content, "mimeType", None)

# Import after mcp — houdini_mcp_server builds the server at import.
os.environ.setdefault("HOUDINIMCP_NO_HEADLESS", "1")
from houdini_mcp_server import _result_with_image, _MAX_INLINE_IMAGE_BYTES  # noqa: E402


def _one_pixel_png(path):
    """Write a valid 1x1 black PNG without Pillow."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF
        )
    raw = zlib.compress(b"\x00\x00\x00\x00")
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", raw)
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(png)
    return png


class TestResultWithImage:
    def test_missing_file_is_text_only(self):
        out = _result_with_image({"filepath": "/no/such/mcp.png", "hydra_renderer": "Karma XPU"})
        assert isinstance(out, str)
        assert "Karma XPU" in out

    def test_empty_file_is_text_only(self, tmp_path):
        p = tmp_path / "empty.png"
        p.write_bytes(b"")
        out = _result_with_image({"filepath": str(p)})
        assert isinstance(out, str)

    def test_png_returns_text_and_image(self, tmp_path):
        p = tmp_path / "mcp.png"
        png = _one_pixel_png(p)
        meta = {
            "filepath": str(p),
            "hydra_renderer": "Karma XPU",
            "camera_path": "/world/cam",
            "snapshot": True,
        }
        out = _result_with_image(meta)
        assert isinstance(out, list)
        assert json.loads(out[0])["camera_path"] == "/world/cam"
        assert isinstance(out[1], Image)
        content = _convert_to_content(out)
        types = [c.type for c in content]
        assert types == ["text", "image"]
        img = content[1]
        assert isinstance(img, ImageContent)
        assert mime_of(img) == "image/png"
        import base64
        assert base64.b64decode(img.data) == png

    def test_oversized_stays_path_only(self, tmp_path, monkeypatch):
        p = tmp_path / "huge.png"
        p.write_bytes(b"\x89PNG" + b"x" * 64)
        import houdini_mcp_server as bridge
        monkeypatch.setattr(bridge, "_MAX_INLINE_IMAGE_BYTES", 8)
        out = bridge._result_with_image({"filepath": str(p)})
        assert isinstance(out, str)
        payload = json.loads(out)
        assert "inline_skipped" in payload
        assert payload["filepath"] == str(p)

    def test_live_flipbook_if_present(self):
        path = "/tmp/mcp_xpu_snap6.png"
        if not os.path.isfile(path) or os.path.getsize(path) < 100:
            pytest.skip("no live flipbook from H22")
        out = _result_with_image({
            "filepath": path,
            "hydra_renderer": "Karma XPU",
            "snapshot": True,
        })
        content = _convert_to_content(out)
        assert content[1].type == "image"
        assert mime_of(content[1]) == "image/png"
        assert len(content[1].data) > 100
