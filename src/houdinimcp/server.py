"""Houdini-side TCP server that receives JSON commands from the MCP bridge."""
import errno
import hou
import json
import socket
import sys
import time

import os
try:
    from PySide6 import QtCore
except ImportError:
    from PySide2 import QtCore

from .handlers.scene import (
    get_scene_info, save_scene, load_scene, set_frame, get_asset_lib_status,
)
from .handlers.nodes import (
    create_node, modify_node, delete_node, get_node_info, set_material,
    connect_nodes, disconnect_node_input, set_node_flags,
    layout_children, set_node_color, set_expression, find_error_nodes,
    copy_node, move_node, rename_node, list_children, find_nodes,
    list_node_types, connect_nodes_batch, reorder_inputs,
)
from .handlers.context import (
    get_network_overview, get_cook_chain, explain_node, get_scene_summary,
    get_selection, set_selection,
)
from .handlers.parameters import (
    get_parameter, set_parameter, set_parameters, get_parameter_schema,
    get_expression, revert_parameter, link_parameters, lock_parameter,
    create_spare_parameter, create_spare_parameters,
)
from .handlers.animation import (
    set_keyframe, set_keyframes, delete_keyframe, get_keyframes,
    get_frame, set_frame_range, set_playback_range, playbar_control,
)
from .handlers.vex import (
    create_wrangle, set_wrangle_code, get_wrangle_code,
    create_vex_expression, validate_vex,
)
from .handlers.materials import (
    list_materials, get_material_info, create_material_network,
    assign_material, list_material_types,
)
from .handlers.code import (
    execute_code, execute_hscript, evaluate_expression, get_env_variable,
    get_last_log, DANGEROUS_PATTERNS,
)
from .handlers.geometry import (
    get_geo_summary, geo_export, get_points, get_prims, get_attrib_values,
    set_detail_attrib, get_groups, get_group_members, get_bounding_box,
    get_prim_intrinsics, find_nearest_point,
)
from .handlers.pdg import pdg_cook, pdg_status, pdg_workitems, pdg_dirty, pdg_cancel
from .handlers.lop import (
    lop_stage_info, lop_prim_get, lop_prim_search, lop_layer_info, lop_import,
    list_usd_prims, get_usd_attribute, set_usd_attribute, get_usd_prim_stats,
    get_last_modified_prims, create_lop_node, get_usd_composition,
    get_usd_variants, inspect_usd_layer, list_lights,
)
from .handlers.workflow import (
    setup_pyro_sim, setup_rbd_sim, setup_flip_sim, setup_vellum_sim,
    create_material_workflow, assign_material_workflow, build_sop_chain, setup_render,
)
from .handlers.cops import (
    get_cop_info, get_cop_geometry, get_cop_layer, create_cop_node,
    set_cop_flags, list_cop_node_types, get_cop_vdb,
)
from .handlers.chops import (
    get_chop_data, create_chop_node, list_chop_channels, export_chop_to_parm,
)
from .handlers.takes import list_takes, get_current_take, set_current_take, create_take
from .handlers.cache import list_caches, get_cache_status, clear_cache, write_cache
from .handlers.hda import (
    hda_list, hda_get, hda_install, hda_create,
    uninstall_hda, reload_hda, update_hda,
    get_hda_sections, get_hda_section_content, set_hda_section_content,
)
from .handlers.dops import (
    get_simulation_info, list_dop_objects, get_dop_object, get_dop_field,
    get_dop_relationships, step_simulation, reset_simulation, get_sim_memory_usage,
)
from .handlers.viewport import (
    list_panes, get_viewport_info, set_viewport_camera, set_viewport_display,
    set_viewport_renderer, frame_selection, frame_all, frame_bbox, set_viewport_direction,
    capture_screenshot, set_current_network,
    list_hydra_renderers, set_hydra_renderer, set_renderer_paused,
    restart_renderer, set_hydra_display,
)
from .handlers.rendering import (
    handle_render_single_view, handle_render_quad_view,
    handle_render_specific_camera, render_flipbook,
    list_render_nodes, get_render_settings, set_render_settings,
    create_render_node, start_render, get_render_progress,
)
from .event_collector import EventCollector
from .framing import pack_message, feed_messages, MAX_PAYLOAD

EXTENSION_NAME = "Houdini MCP"
EXTENSION_VERSION = (0, 2)
EXTENSION_DESCRIPTION = "Connect Houdini to Claude via MCP"

def _env_number(name, default, cast=int):
    """Read a numeric env var without killing the plugin import.

    A Houdini package JSON that expands an unset variable hands us "", which
    raised ValueError at import -- the plugin then simply never loaded, with
    the traceback buried in Houdini's console.
    """
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return cast(str(raw).strip())
    except (TypeError, ValueError):
        sys.stderr.write(
            "Houdini MCP: %s=%r is not a number; using %s\n" % (name, raw, default)
        )
        return default


DEFAULT_PORT = _env_number("HOUDINIMCP_PORT", 9876)

# QTimer poll interval. Every round trip waits for the next tick, so 100ms
# put a hard 100ms floor under every MCP tool call. A non-blocking recv on a
# couple of sockets costs microseconds; 20ms is not measurable in Houdini.
POLL_INTERVAL_MS = max(1, _env_number("HOUDINIMCP_POLL_MS", 20))

# Read chunk size -- a syscall knob, not a throughput cap.
RECV_CHUNK = 1 << 16

# Bytes accepted from one client per tick. Draining to EAGAIN unconditionally
# fixed the old ~82KB/s cap and created the opposite failure: a peer that kept
# the socket readable never let the Qt event loop run again. A bounded slice
# per tick costs latency instead of freezing Houdini.
READ_BUDGET = max(RECV_CHUNK, _env_number("HOUDINIMCP_READ_BUDGET", 4 * 1024 * 1024))

# How long a response may sit half-written before the client is dropped.
# Writes are non-blocking and resume per tick, so this is a liveness bound,
# not a stretch of frozen UI.
SEND_TIMEOUT = _env_number("HOUDINIMCP_SEND_TIMEOUT", 60.0, float)

# Per-command connect/execute/disconnect used to print to the Houdini
# Python shell on every MCP tool. Default is quiet. Verbose:
# HOUDINIMCP_LOG=verbose or hou.session.houdinimcp_log = "verbose".
_VERBOSE_LOG_VALUES = ("verbose", "debug", "1", "true", "yes", "on")
_QUIET_LOG_VALUES = ("quiet", "warn", "warning", "0", "false", "no", "off")


def _log_level():
    try:
        v = getattr(hou.session, "houdinimcp_log", None)
        if v:
            v = str(v).strip().lower()
            if v in _VERBOSE_LOG_VALUES:
                return "verbose"
            if v in _QUIET_LOG_VALUES:
                return "quiet"
    except Exception:
        pass
    env = os.environ.get("HOUDINIMCP_LOG", "").strip().lower()
    if env in _VERBOSE_LOG_VALUES:
        return "verbose"
    return "quiet"


def _say(msg, verbose=False, error=False):
    """Houdini console. verbose=True is hidden unless log=verbose."""
    if verbose and not error and _log_level() != "verbose":
        return
    try:
        sys.stderr.write("%s\n" % msg)
    except Exception:
        pass


def _connect_host(host):
    if host in ("", "localhost", "0.0.0.0", "::"):
        return "127.0.0.1"
    return host


def port_is_taken(host, port, timeout=0.2):
    """True if something already accepts TCP on host:port."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(timeout)
    try:
        probe.connect((_connect_host(host), int(port)))
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False
    finally:
        try:
            probe.close()
        except Exception:
            pass


def server_is_listening(server):
    """This process's listener socket is bound. Does not open a new client."""
    if server is None or not getattr(server, "running", False):
        return False
    sock = getattr(server, "socket", None)
    if sock is None:
        return False
    try:
        name = sock.getsockname()
    except OSError:
        return False
    return bool(name) and int(name[1]) > 0


def report_bind_failure(host, port, exc):
    """Surface bind failure in the Houdini UI. Never hou.severityType.Fatal."""
    err = getattr(exc, "errno", None)
    if err == errno.EADDRINUSE or (exc and "already in use" in str(exc).lower()):
        if sys.platform == "win32":
            probe = "netstat -ano | findstr :%s" % port
            extra = (
                "\nOn Windows the port also stays reserved for the TIME_WAIT "
                "window after a clean shutdown; wait a moment and retry."
            )
        else:
            probe = "ss -tlnp | grep %s" % port
            extra = ""
        msg = (
            "Houdini MCP cannot bind %s:%s — address already in use.\n"
            "Another houdini-bin is probably still listening.\n"
            "%s%s" % (host, port, probe, extra)
        )
    else:
        msg = "Houdini MCP failed to start on %s:%s: %s" % (host, port, exc)
    try:
        sys.stderr.write(msg + "\n")
    except Exception:
        pass
    try:
        hou.session.houdinimcp_bind_error = msg
    except Exception:
        pass
    try:
        ui_ok = bool(hou.isUIAvailable()) if hasattr(hou, "isUIAvailable") else False
        display = getattr(getattr(hou, "ui", None), "displayMessage", None)
        if ui_ok and callable(display):
            kwargs = {"title": "Houdini MCP"}
            sev = getattr(getattr(hou, "severityType", None), "Error", None)
            if sev is not None:
                kwargs["severity"] = sev
            display(msg, **kwargs)
    except Exception as e:
        try:
            sys.stderr.write("Houdini MCP displayMessage failed: %s\n" % e)
        except Exception:
            pass
    return msg


class BatchError(Exception):
    """An operation inside a batch raised. Carries what already landed.

    hou.undos.group() groups operations into one undo entry; it does not
    roll them back. Callers must be told how far the batch got, or they
    retry the whole thing and duplicate the completed half.
    """

    def __init__(self, cmd_type, index, cause, completed):
        self.cmd_type = cmd_type
        self.index = index
        self.cause = cause
        self.completed = completed
        super().__init__(
            "batch failed at operation %d (%s): %s. %d earlier operation(s) "
            "already applied and were NOT rolled back."
            % (index, cmd_type, cause, len(completed))
        )


class _ClientGone(Exception):
    """Peer closed or reset. Drop the connection without a console traceback."""


class _ClientConn:
    """One MCP TCP client. Capture on A must not block ping on B."""

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.buffer = b""
        self.busy = False
        self.outbox = b""
        self.pending = []
        self.send_deadline = None
        self.eof = False


def _cook_followup(result):
    """After a mutating command, cook the touched node and return errors."""
    path = result.get("path") or result.get("node")
    if not path or not isinstance(path, str):
        return None
    node = hou.node(path)
    if node is None:
        return None
    try:
        node.cook(force=False)
    except Exception as e:
        return {"path": path, "cook_error": str(e)}
    errors = []
    warnings = []
    try:
        errors = list(node.errors() or [])
        warnings = list(node.warnings() or [])
    except Exception:
        pass
    if not errors and not warnings:
        return {"path": path, "ok": True}
    return {"path": path, "errors": errors, "warnings": warnings}


class HoudiniMCPServer:
    MUTATING_COMMANDS = {
        "create_node", "modify_node", "delete_node", "execute_code",
        "set_material", "connect_nodes", "disconnect_node_input",
        "set_node_flags", "save_scene", "load_scene", "set_expression",
        "set_frame", "layout_children", "set_node_color",
        "pdg_cook", "pdg_dirty", "pdg_cancel",
        "lop_import", "hda_install", "hda_create", "batch",
        "set_selection", "set_parameter", "set_parameters", "set_file",
        "revert_parameter", "link_parameters", "lock_parameter",
        "create_spare_parameter", "create_spare_parameters",
        "copy_node", "move_node", "rename_node", "connect_nodes_batch",
        "reorder_inputs", "set_detail_attrib", "execute_hscript",
        "set_keyframe", "set_keyframes", "delete_keyframe",
        "set_frame_range", "set_playback_range", "playbar_control",
        "create_wrangle", "set_wrangle_code", "create_vex_expression",
        "create_material_network", "assign_material",
        "step_simulation", "reset_simulation",
        "set_viewport_camera", "set_viewport_display", "set_viewport_renderer",
        "frame_selection", "frame_all", "frame_bbox", "set_viewport_direction", "set_current_network",
        "set_render_settings", "create_render_node", "start_render",
        "create_cop_node", "set_cop_flags",
        "create_chop_node", "export_chop_to_parm",
        "set_current_take", "create_take",
        "clear_cache", "write_cache",
        "uninstall_hda", "reload_hda", "update_hda", "set_hda_section_content",
        "set_usd_attribute", "create_lop_node",
        "setup_pyro_sim", "setup_rbd_sim", "setup_flip_sim", "setup_vellum_sim",
        "create_material_workflow", "assign_material_workflow", "build_sop_chain", "setup_render",
        "import_fbx_character", "import_fbx_animation",
        "attach_kinefx_deform", "map_kinefx_joints",
        "lookdev_dome", "lookdev_preview_surface", "lookdev_display_color",
        "lookdev_camera", "set_karma_samples", "set_karma_quality",
        "frame_usd_prim",
    }

    # Commands allowed to run from inside a nested Qt event loop, i.e. while
    # another command is still executing. Anything that mutates the scene
    # waits: serviced re-entrantly it would join the outer command's undo
    # group and run mid-capture.
    REENTRANT_SAFE = frozenset({
        "ping", "get_pending_events", "subscribe_events", "get_last_log",
    })

    # Re-export for tests that reference it on the class
    DANGEROUS_PATTERNS = DANGEROUS_PATTERNS

    def __init__(self, host='localhost', port=None):
        port = port if port is not None else DEFAULT_PORT
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.client = None
        self.buffer = b''
        self._clients = []
        self.timer = None
        self._executing = 0
        self.event_collector = EventCollector()

    def start(self):
        """Begin listening on the given port; sets up a QTimer to poll for data.

        Returns True if this process is listening. Returns False on bind
        failure (does not leave running=True).
        """
        if server_is_listening(self):
            return True
        if port_is_taken(self.host, self.port):
            report_bind_failure(
                self.host, self.port,
                OSError(errno.EADDRINUSE, "Address already in use"),
            )
            return False
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform == "win32":
                # On Win32 SO_REUSEADDR means the opposite of the POSIX flag:
                # it lets a second process bind a port that is already in use
                # and silently take traffic from the first.
                # SO_EXCLUSIVEADDRUSE is the flag that means what the POSIX
                # one means. Setting it inside the try so a failure closes
                # the socket instead of leaking it.
                exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
                if exclusive is not None:
                    sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.listen(8)
            sock.setblocking(False)
        except OSError as e:
            try:
                sock.close()
            except Exception:
                pass
            report_bind_failure(self.host, self.port, e)
            return False
        self.socket = sock
        self.running = True
        try:
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self._process_server)
            self.timer.start(POLL_INTERVAL_MS)
            _say("HoudiniMCP server started on %s:%s" % (self.host, self.port))
            self.event_collector.start()
            try:
                from .handlers.plugin import _mark_loaded
                _mark_loaded()
            except Exception:
                pass
        except Exception as e:
            _say("Failed to start server: %s" % e, error=True)
            self.stop()
            return False
        return True

    def stop(self):
        """Stop listening; close sockets and timers."""
        self.running = False
        self.event_collector.stop()
        if self.timer:
            self.timer.stop()
            self.timer = None
        if self.socket:
            self.socket.close()
        for conn in list(getattr(self, "_clients", []) or []):
            self._drop_client(conn)
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        self.socket = None
        self.client = None
        self.buffer = b''
        self._clients = []
        _say("HoudiniMCP server stopped")

    def _accept_clients(self):
        if not self.socket:
            return
        while True:
            try:
                sock, address = self.socket.accept()
                sock.setblocking(False)
                conn = _ClientConn(sock, address)
                peers = len(self._clients)
                self._clients.append(conn)
                self.client = sock
                if peers:
                    _say(
                        "Houdini MCP: additional client %s (%d already connected; "
                        "not stealing the first session)" % (address, peers),
                        verbose=True,
                    )
                else:
                    _say("Connected to client: %s" % (address,), verbose=True)
            except BlockingIOError:
                break
            except Exception as e:
                _say("Error accepting connection: %s" % e, error=True)
                break

    def _drop_client(self, conn):
        try:
            conn.sock.close()
        except Exception:
            pass
        clients = getattr(self, "_clients", None)
        if clients and conn in clients:
            clients.remove(conn)
        if self.client is conn.sock:
            remaining = clients or []
            self.client = remaining[0].sock if remaining else None
            self.buffer = b''

    def _read_messages(self, conn):
        """Read a bounded slice this tick; return the complete messages in it.

        One recv(8192) per 100ms tick capped inbound at ~82KB/s. Draining to
        EAGAIN fixed that but handed a local peer the ability to hold the Qt
        main thread forever and grow conn.buffer without limit, because
        MAX_PAYLOAD is only checked once a whole frame has arrived. This reads
        at most READ_BUDGET and resumes next tick.

        Sets conn.eof instead of raising on a clean close, so a peer that
        sends a frame and immediately closes still gets it executed.
        """
        got = 0
        while got < READ_BUDGET:
            try:
                data = conn.sock.recv(RECV_CHUNK)
            except BlockingIOError:
                break
            except (ConnectionResetError, BrokenPipeError):
                raise _ClientGone()
            except OSError as e:
                raise _ClientGone() from e
            if not data:
                conn.eof = True
                break
            conn.buffer += data
            got += len(data)
            if len(conn.buffer) > MAX_PAYLOAD:
                raise ValueError(
                    "client %s buffered %d bytes with no complete message "
                    "(limit %d)" % (conn.addr, len(conn.buffer), MAX_PAYLOAD)
                )
        if not conn.buffer:
            return []
        messages, conn.buffer = feed_messages(conn.buffer)
        return messages

    @staticmethod
    def _encode_response(payload):
        """Frame a response, degrading to an error frame rather than dying.

        pack_message raises on a payload over MAX_PAYLOAD. That exception used
        to escape into _service_client and drop a healthy client, so the caller
        saw a dead socket instead of a reason it could act on.
        """
        try:
            return pack_message(payload)
        except ValueError as e:
            return pack_message({
                "status": "error",
                "message": (
                    "response too large to send (%s). Narrow the query: fewer "
                    "points/prims, or geo_export to a file." % e
                ),
                "oversized": True,
            })
        except Exception as e:
            return pack_message({
                "status": "error",
                "message": "response could not be serialized: %s" % e,
            })

    def _flush_outbox(self, conn):
        """Push queued bytes without blocking. True when the socket is clear.

        The previous fix put the socket into blocking mode and sendall'd the
        whole frame on the Qt main thread, so a peer that stopped reading
        froze all of Houdini for up to SEND_TIMEOUT -- including ping on a
        second client, which the multi-client design exists to keep alive.
        A partial write now simply resumes on the next tick.
        """
        while conn.outbox:
            try:
                sent = conn.sock.send(conn.outbox)
            except BlockingIOError:
                break
            except (ConnectionResetError, BrokenPipeError):
                raise _ClientGone()
            except OSError as e:
                raise _ClientGone() from e
            if sent <= 0:
                break
            conn.outbox = conn.outbox[sent:]
        if not conn.outbox:
            conn.send_deadline = None
            return True
        if conn.send_deadline is not None and time.monotonic() > conn.send_deadline:
            _say("Dropping %s: response stalled over %ss"
                 % (conn.addr, SEND_TIMEOUT), error=True)
            raise _ClientGone()
        return False

    def _send_response(self, conn, payload):
        """Queue one framed response and push whatever the socket takes now."""
        conn.outbox += self._encode_response(payload)
        if conn.send_deadline is None:
            conn.send_deadline = time.monotonic() + SEND_TIMEOUT
        return self._flush_outbox(conn)

    def _service_client(self, conn):
        try:
            clear = self._flush_outbox(conn)
            conn.pending.extend(self._read_messages(conn))
        except _ClientGone:
            _say("Client disconnected", verbose=True)
            self._drop_client(conn)
            return
        except Exception as e:
            _say("Error receiving data: %s" % e, error=True)
            self._drop_client(conn)
            return

        while conn.pending and clear:
            if self._executing and conn.pending[0].get("type") not in self.REENTRANT_SAFE:
                # Flipbook capture pumps a nested Qt event loop, which
                # re-enters this timer. Running a mutating command from there
                # lands it inside the outer command's hou.undos.group() -- one
                # Ctrl-Z would undo both -- and executes it mid-capture. Leave
                # it queued for a top-level tick.
                break
            command = conn.pending.pop(0)
            conn.busy = True
            self._executing += 1
            try:
                response = self.execute_command(command)
            finally:
                self._executing -= 1
                conn.busy = False
            try:
                clear = self._send_response(conn, response)
            except _ClientGone:
                self._drop_client(conn)
                return
            except Exception as e:
                _say("Error sending response: %s" % e, error=True)
                self._drop_client(conn)
                return

        if conn.eof and not conn.pending and not conn.outbox:
            _say("Client disconnected", verbose=True)
            self._drop_client(conn)

    def _process_server(self):
        """Timer callback: accept every pending client, then service each.

        Capture/flipbook can nest Qt events. A second connection must still
        be able to `ping` while one client is busy (see issue #2).
        """
        if not self.running:
            return
        try:
            self._accept_clients()
            for conn in list(getattr(self, "_clients", []) or []):
                self._service_client(conn)
        except Exception as e:
            _say("Server error: %s" % e, error=True)

    def _ensure_reload_hook(self):
        """If this process still has a stale command table, patch it.

        ping/execute_code always existed. reload_plugin 404s until this runs.
        Does not restart the TCP listener.
        """
        try:
            if "reload_plugin" in self._get_handlers():
                return
        except Exception:
            pass
        from .handlers.plugin import bootstrap_reload
        bootstrap_reload()

    def execute_command(self, command):
        """Entry point for executing a JSON command from the client.

        Body lives in handlers.plugin.dispatch_command so reload_plugin can
        rebind this method on the live instance without reloading server.py.
        """
        from .handlers.plugin import dispatch_command
        return dispatch_command(self, command)

    def _get_handlers(self):
        """Return the command handler dispatch dict.

        Late-binds through handlers.plugin.bind_handlers so importlib.reload
        of handler modules (reload_plugin) picks up new function objects and
        new command keys without restarting houdini-bin.
        """
        from .handlers.plugin import bind_handlers
        return bind_handlers(self)


    def _execute_command_internal(self, command):
        """Dispatch a JSON command to its handler."""
        cmd_type = command.get("type")
        params = command.get("params", {})

        handler = self._get_handlers().get(cmd_type)
        if not handler:
            return {"status": "error", "message": f"Unknown command type: {cmd_type}"}

        _say("Executing handler for %s" % cmd_type, verbose=True)
        result = handler(**params)
        _say("Handler execution complete for %s" % cmd_type, verbose=True)
        if cmd_type in self.MUTATING_COMMANDS and isinstance(result, dict):
            cook = _cook_followup(result)
            if cook:
                result = dict(result)
                result["cook"] = cook
        return {"status": "success", "result": result}

    def ping(self):
        """Simple health check that returns server status."""
        clients = getattr(self, "_clients", None)
        if clients is None:
            n = 1 if self.client is not None else 0
            busy = 0
        else:
            n = len(clients)
            busy = sum(1 for c in clients if c.busy)
        payload = {
            "alive": True,
            "host": self.host,
            "port": self.port,
            "has_client": n > 0 or self.client is not None,
            "clients": n,
            "busy": busy,
            "log": _log_level(),
        }
        try:
            from .handlers.plugin import plugin_status
            payload.update(plugin_status())
            payload["commands"] = len(self._get_handlers())
        except Exception as e:
            payload["plugin_status_error"] = str(e)
        if payload.get("clients", 0) > 1:
            payload["peer_warning"] = (
                "%d MCP clients connected; sessions are shared, not stolen"
                % payload["clients"]
            )
        return payload

    def batch(self, operations):
        """Execute multiple operations in one undo group. Each op: {type, params}.

        Not a transaction. Unknown command types are rejected up front so a
        typo cannot leave the scene half-built; a handler that raises
        mid-run reports how far it got via BatchError.
        """
        handlers = self._get_handlers()
        unknown = [
            op.get("type") for op in operations
            if op.get("type") not in handlers
        ]
        if unknown:
            raise ValueError(
                "Unknown operation(s) in batch: %s. Nothing was executed."
                % ", ".join(repr(u) for u in unknown)
            )
        results = []
        for index, op in enumerate(operations):
            cmd_type = op.get("type")
            try:
                result = handlers[cmd_type](**(op.get("params") or {}))
            except Exception as e:
                raise BatchError(cmd_type, index, e, results) from e
            results.append({"type": cmd_type, "result": result})
        return {"count": len(results), "results": results}

    def get_pending_events(self, since=None):
        """Return buffered events since last poll and clear the buffer."""
        events = self.event_collector.get_pending(since=since)
        return {"count": len(events), "events": events}

    def subscribe_events(self, types=None):
        """Configure which event types to collect. None = all."""
        self.event_collector.subscribe(types)
        return {"subscribed": types or "all"}

    def get_asset_categories(self):
        """Placeholder for an asset library feature."""
        return {"error": "get_asset_categories not implemented"}

    def search_assets(self):
        """Placeholder for asset search logic."""
        return {"error": "search_assets not implemented"}

    def import_asset(self):
        """Placeholder for asset import logic."""
        return {"error": "import_asset not implemented"}
