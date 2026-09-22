"""Framing: HMC1 length prefix + legacy JSON (issue #7)."""
import json
import struct

from houdinimcp.framing import MAGIC, feed_messages, pack_message


class TestPackFeed:
    def test_roundtrip(self):
        msg = {"type": "ping", "params": {}}
        framed = pack_message(msg)
        assert framed.startswith(MAGIC)
        out, rest = feed_messages(framed)
        assert rest == b""
        assert out == [msg]

    def test_partial_frame_waits(self):
        framed = pack_message({"type": "ping"})
        out, rest = feed_messages(framed[:6])
        assert out == []
        assert rest == framed[:6]
        out, rest = feed_messages(framed)
        assert out == [{"type": "ping"}]
        assert rest == b""

    def test_two_frames_one_buffer(self):
        a = pack_message({"type": "ping"})
        b = pack_message({"type": "list_hydra_renderers"})
        out, rest = feed_messages(a + b)
        assert rest == b""
        assert [m["type"] for m in out] == ["ping", "list_hydra_renderers"]

    def test_legacy_json_still_parses(self):
        raw = json.dumps({"type": "ping", "params": {}}).encode()
        out, rest = feed_messages(raw)
        assert out[0]["type"] == "ping"
        assert rest == b""

    def test_two_legacy_objects_do_not_desync(self):
        raw = json.dumps({"type": "a"}) + json.dumps({"type": "b"})
        out, rest = feed_messages(raw.encode())
        assert [m["type"] for m in out] == ["a", "b"]
        assert rest == b""

    def test_legacy_partial_waits(self):
        raw = json.dumps({"type": "ping"}).encode()
        out, rest = feed_messages(raw[:5])
        assert out == []
        assert rest == raw[:5]

    def test_magic_incomplete_prefix(self):
        out, rest = feed_messages(b"HM")
        assert out == []
        assert rest == b"HM"

    def test_oversized_rejected(self):
        header = MAGIC + struct.pack(">I", 40 * 1024 * 1024)
        try:
            feed_messages(header)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "too large" in str(e)
