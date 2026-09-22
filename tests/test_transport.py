"""Transport-layer tests: bounded reads, resumable writes, re-entrancy.

Guards the bugs found in the two 2026-09 audit passes:
  * sendall() on a non-blocking socket silently truncated responses >~2.5MB
  * one recv(8192) per 100ms QTimer tick capped inbound at ~82KB/s
  * the fix for those two put both directions on the Qt main thread with only
    a time bound (writes) or none at all (reads), so a local peer could hang
    or OOM houdini-bin
  * a frame followed immediately by FIN was discarded
  * a mutating command from a second client executed inside the first
    client's hou.undos.group() via a nested Qt event loop
  * an unserializable or oversized result dropped the session with no error
"""
import socket
import struct
import threading
import time

import pytest

# Importing this installs the hou / PySide2 / numpy mocks as a side effect.
from tests.test_server_commands import HoudiniMCPServer

from houdinimcp.framing import MAGIC, MAX_PAYLOAD, pack_message
from houdinimcp.server import _ClientConn, _ClientGone, READ_BUDGET


def _bare_server():
    srv = HoudiniMCPServer.__new__(HoudiniMCPServer)
    srv.host, srv.port = "localhost", 9876
    srv.running, srv.socket, srv.client = False, None, None
    srv.buffer, srv._clients, srv.timer = b"", [], None
    srv._executing = 0
    return srv


def _pump(srv, conn, deadline=10.0):
    """Drive _flush_outbox the way the QTimer would, until the socket clears."""
    end = time.monotonic() + deadline
    while conn.outbox and time.monotonic() < end:
        srv._flush_outbox(conn)
    return not conn.outbox


class _ScriptedSock:
    """Hands out a fixed list of chunks, then EAGAIN. Counts recv calls."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.recv_calls = 0

    def recv(self, _n):
        self.recv_calls += 1
        if not self._chunks:
            raise BlockingIOError()
        return self._chunks.pop(0)


class TestReadMessages:
    """Inbound drains per tick, but within a budget."""

    def test_drains_many_chunks_in_one_call(self):
        """One recv(8192) per 100ms tick capped inbound at ~82KB/s."""
        srv = _bare_server()
        frame = pack_message({"type": "execute_code",
                              "params": {"code": "x" * 300_000}})
        chunks = [frame[i:i + 8192] for i in range(0, len(frame), 8192)]
        assert len(chunks) > 30, "payload must span many old-style ticks"

        conn = _ClientConn(_ScriptedSock(chunks), ("127.0.0.1", 1))
        msgs = srv._read_messages(conn)

        assert len(msgs) == 1
        assert msgs[0]["params"]["code"] == "x" * 300_000
        assert conn.buffer == b""
        assert conn.sock.recv_calls == len(chunks) + 1

    def test_stops_at_eagain_without_spinning(self):
        srv = _bare_server()
        conn = _ClientConn(_ScriptedSock([]), ("127.0.0.1", 1))
        assert srv._read_messages(conn) == []
        assert conn.sock.recv_calls == 1

    def test_read_is_bounded_per_tick(self):
        """A peer that never yields EAGAIN must not own the Qt thread.

        The drain-to-EAGAIN loop had no ceiling: a writer that keeps the
        socket readable made _read_messages never return, so the Qt event
        loop never ran again and Houdini's UI froze for as long as it lasted.
        """
        srv = _bare_server()

        class _Endless:
            def __init__(self):
                self.calls = 0

            def recv(self, n):
                self.calls += 1
                return b"\x00" * n

        conn = _ClientConn(_Endless(), ("127.0.0.1", 1))
        srv._read_messages(conn)  # must return at all -- this is the bug

        read = conn.sock.calls * (1 << 16)
        assert read <= READ_BUDGET + (1 << 16), (
            "one tick consumed %d bytes, budget is %d" % (read, READ_BUDGET)
        )
        assert len(conn.buffer) <= READ_BUDGET + (1 << 16)

    def test_buffer_cap_rejects_a_never_ending_message(self):
        srv = _bare_server()
        junk = b"{" + b"z" * (1 << 20)
        conn = _ClientConn(_ScriptedSock([junk] * 64), ("127.0.0.1", 1))
        with pytest.raises(ValueError, match="no complete message"):
            for _ in range(64):
                srv._read_messages(conn)

    def test_partial_frame_is_kept_not_parsed(self):
        srv = _bare_server()
        whole = pack_message({"type": "ping", "params": {}})
        conn = _ClientConn(_ScriptedSock([whole[:5]]), ("127.0.0.1", 1))
        assert srv._read_messages(conn) == []
        assert conn.buffer == whole[:5]
        conn.sock = _ScriptedSock([whole[5:]])
        assert [m["type"] for m in srv._read_messages(conn)] == ["ping"]
        assert conn.buffer == b""

    def test_frame_then_immediate_close_is_still_executed(self):
        """A one-shot client's command used to be thrown away with the FIN."""
        srv = _bare_server()
        frame = pack_message({"type": "ping", "params": {}})
        conn = _ClientConn(_ScriptedSock([frame, b""]), ("127.0.0.1", 1))
        msgs = srv._read_messages(conn)
        assert [m["type"] for m in msgs] == ["ping"]
        assert conn.eof is True

    def test_reset_raises_client_gone(self):
        srv = _bare_server()

        class _Reset:
            def recv(self, _n):
                raise ConnectionResetError()

        with pytest.raises(_ClientGone):
            srv._read_messages(_ClientConn(_Reset(), ("127.0.0.1", 1)))


class TestSendResponse:
    """Outbound delivers every byte without blocking the Qt thread."""

    def test_sendall_on_nonblocking_socket_really_does_truncate(self):
        """The premise of the original bug, and why we no longer use sendall."""
        a, b = socket.socketpair()
        try:
            a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            b.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            a.setblocking(False)
            with pytest.raises(BlockingIOError):
                a.sendall(b"z" * (8 << 20))
        finally:
            a.close()
            b.close()

    @pytest.mark.parametrize("size", [64 * 1024, 4 * 1024 * 1024])
    def test_large_response_arrives_whole(self, size):
        srv = _bare_server()
        a, b = socket.socketpair()
        received = bytearray()
        try:
            a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            b.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            a.setblocking(False)

            def drain():
                b.settimeout(30)
                while True:
                    try:
                        chunk = b.recv(65536)
                    except (OSError, socket.timeout):
                        return
                    if not chunk:
                        return
                    received.extend(chunk)

            reader = threading.Thread(target=drain, daemon=True)
            reader.start()

            payload = {"status": "success", "result": {"stdout": "z" * size}}
            conn = _ClientConn(a, ("127.0.0.1", 1))
            srv._send_response(conn, payload)
            assert _pump(srv, conn), "outbox never drained"
            expected = pack_message(payload)

            a.close()
            reader.join(timeout=30)
            assert len(received) == len(expected), (
                "truncated: got %d of %d bytes" % (len(received), len(expected))
            )
            assert bytes(received) == expected
        finally:
            for s in (a, b):
                try:
                    s.close()
                except OSError:
                    pass

    def test_write_never_blocks_the_caller(self):
        """A peer that stops reading must not freeze Houdini for SEND_TIMEOUT."""
        srv = _bare_server()
        a, b = socket.socketpair()
        try:
            a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            b.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            a.setblocking(False)
            conn = _ClientConn(a, ("127.0.0.1", 1))

            started = time.monotonic()
            clear = srv._send_response(
                conn, {"status": "success", "result": {"x": "z" * (8 << 20)}}
            )
            elapsed = time.monotonic() - started

            assert clear is False, "peer is not reading; this cannot be done"
            assert conn.outbox, "the remainder must be queued for the next tick"
            assert elapsed < 1.0, "blocked the caller for %.1fs" % elapsed
            assert a.gettimeout() == 0.0, "socket must stay non-blocking"
        finally:
            a.close()
            b.close()

    def test_stalled_write_eventually_drops_the_client(self):
        srv = _bare_server()
        a, b = socket.socketpair()
        try:
            a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            b.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            a.setblocking(False)
            conn = _ClientConn(a, ("127.0.0.1", 1))
            srv._send_response(conn, {"result": {"x": "z" * (8 << 20)}})
            conn.send_deadline = time.monotonic() - 1  # deadline already passed
            with pytest.raises(_ClientGone):
                srv._flush_outbox(conn)
        finally:
            a.close()
            b.close()

    def test_frame_header_is_well_formed(self):
        srv = _bare_server()
        a, b = socket.socketpair()
        try:
            a.setblocking(False)
            conn = _ClientConn(a, ("127.0.0.1", 1))
            srv._send_response(conn, {"status": "success", "result": {"n": 1}})
            assert _pump(srv, conn)
            head = b.recv(8)
            assert head[:4] == MAGIC
            (length,) = struct.unpack(">I", head[4:8])
            assert len(b.recv(length)) == length
        finally:
            a.close()
            b.close()


class TestEncodeResponse:
    """A bad result must produce an error frame, not a dead socket."""

    def test_unserializable_value_still_frames(self):
        class Ramp:
            def __repr__(self):
                return "<hou.Ramp>"

        data = HoudiniMCPServer._encode_response(
            {"status": "success", "result": {"value": Ramp()}}
        )
        assert data.startswith(MAGIC)
        assert b"hou.Ramp" in data

    def test_oversized_result_degrades_to_an_error(self):
        huge = {"status": "success", "result": {"blob": "z" * (MAX_PAYLOAD + 1024)}}
        data = HoudiniMCPServer._encode_response(huge)
        assert data.startswith(MAGIC)
        assert len(data) < MAX_PAYLOAD
        assert b"too large" in data
        assert b"geo_export" in data, "tell the caller what to do instead"


class TestReentrancy:
    """A nested Qt event loop must not run a mutating command."""

    def test_mutating_command_waits_while_another_is_executing(self):
        srv = _bare_server()
        ran = []
        srv.execute_command = lambda cmd: ran.append(cmd["type"]) or {"ok": True}
        srv._executing = 1  # as if called from inside a flipbook capture

        conn = _ClientConn(_ScriptedSock([
            pack_message({"type": "create_node", "params": {}}),
        ]), ("127.0.0.1", 1))
        conn.sock.send = lambda data: len(data)
        srv._service_client(conn)

        assert ran == [], "create_node must not run inside another command"
        assert [c["type"] for c in conn.pending] == ["create_node"]

    def test_ping_still_answers_during_a_capture(self):
        srv = _bare_server()
        ran = []
        srv.execute_command = lambda cmd: ran.append(cmd["type"]) or {"alive": True}
        srv._executing = 1

        conn = _ClientConn(_ScriptedSock([
            pack_message({"type": "ping", "params": {}}),
        ]), ("127.0.0.1", 1))
        conn.sock.send = lambda data: len(data)
        srv._service_client(conn)

        assert ran == ["ping"], "the multi-client design exists for this"
        assert conn.pending == []

    def test_queued_command_runs_on_the_next_top_level_tick(self):
        srv = _bare_server()
        ran = []
        srv.execute_command = lambda cmd: ran.append(cmd["type"]) or {"ok": True}
        srv._executing = 1

        conn = _ClientConn(_ScriptedSock([
            pack_message({"type": "create_node", "params": {}}),
        ]), ("127.0.0.1", 1))
        conn.sock.send = lambda data: len(data)
        srv._service_client(conn)
        assert ran == []

        srv._executing = 0
        conn.sock = _ScriptedSock([])
        conn.sock.send = lambda data: len(data)
        srv._service_client(conn)
        assert ran == ["create_node"]

    def test_reentrant_safe_set_holds_no_mutating_command(self):
        overlap = HoudiniMCPServer.REENTRANT_SAFE & HoudiniMCPServer.MUTATING_COMMANDS
        assert not overlap, "these would join the outer command's undo group: %s" % overlap


class TestPollInterval:
    def test_interval_is_well_under_the_old_100ms_floor(self):
        from houdinimcp.server import POLL_INTERVAL_MS

        assert 1 <= POLL_INTERVAL_MS <= 50
