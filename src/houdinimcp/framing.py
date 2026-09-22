"""Length-prefixed Houdini MCP frames (issue #7).

New messages: magic HMC1 + uint32be length + UTF-8 JSON.
Legacy: concatenated JSON objects via JSONDecoder.raw_decode.

Partial buffers stay in the leftover. Two objects in one recv cannot
desync the socket.
"""
import json
import struct

MAGIC = b"HMC1"
MAX_PAYLOAD = 32 * 1024 * 1024
_DECODER = json.JSONDecoder()


def _stringify(obj):
    """Last resort for a value json cannot encode.

    Handler results carry whatever the hou API returned: parm.eval() on a
    ramp gives a hou.Ramp, attribValue() can give a hou.Vector3. json.dumps
    raised TypeError on those, and because pack_message is called on the
    response path that killed the whole TCP session instead of returning a
    value -- the client saw "connection closed by Houdini" for a benign read.
    """
    return str(obj)


def pack_message(obj):
    payload = json.dumps(
        obj, separators=(",", ":"), default=_stringify
    ).encode("utf-8")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("MCP payload too large: %d" % len(payload))
    return MAGIC + struct.pack(">I", len(payload)) + payload


def feed_messages(buffer):
    """Parse complete messages from *buffer*.

    Returns (list_of_objects, remaining_bytes).
    """
    if not buffer:
        return [], buffer
    messages = []
    buf = buffer
    while buf:
        if buf.startswith(MAGIC) or MAGIC.startswith(buf):
            if not buf.startswith(MAGIC):
                return messages, buf
            if len(buf) < 8:
                return messages, buf
            (length,) = struct.unpack(">I", buf[4:8])
            if length > MAX_PAYLOAD:
                raise ValueError("HMC1 payload too large: %d" % length)
            if len(buf) < 8 + length:
                return messages, buf
            payload = buf[8:8 + length]
            messages.append(json.loads(payload.decode("utf-8")))
            buf = buf[8 + length:]
            continue
        # The legacy branch had no size check at all, so an unterminated
        # JSON object grew the caller's buffer without limit and was
        # re-decoded in full on every poll.
        if len(buf) > MAX_PAYLOAD:
            raise ValueError("unframed payload too large: %d" % len(buf))
        try:
            text = buf.decode("utf-8")
        except UnicodeDecodeError:
            return messages, buf
        i = 0
        n = len(text)
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            return messages, b""
        try:
            obj, end = _DECODER.raw_decode(text, i)
        except json.JSONDecodeError:
            return messages, buf
        messages.append(obj)
        buf = text[end:].encode("utf-8")
    return messages, buf
