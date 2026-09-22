"""Houdini MCP in-process plugin. Importing this module must not require hou
so the stdio bridge can use houdinimcp.framing outside houdini-bin.
"""


def start_server(host=None, port=None):
    """Start the in-process TCP listener. Returns the server or None.

    Does not claim success unless this process is actually listening.
    A stale hou.session.houdinimcp_server with a dead socket is torn down
    and rebound. Address-in-use is a Houdini UI error, not 'already running.'
    """
    import hou
    from .server import HoudiniMCPServer, server_is_listening
    existing = getattr(hou.session, "houdinimcp_server", None)
    if server_is_listening(existing):
        print("Houdini MCP Server is already running on %s:%s." % (
            existing.host, existing.port))
        return existing
    if existing is not None:
        try:
            existing.stop()
        except Exception:
            pass
        hou.session.houdinimcp_server = None
    kwargs = {}
    if host is not None:
        kwargs["host"] = host
    if port is not None:
        kwargs["port"] = port
    server = HoudiniMCPServer(**kwargs)
    hou.session.houdinimcp_server = server
    if not server.start():
        hou.session.houdinimcp_server = None
        return None
    return server

def stop_server():
    import hou
    if hasattr(hou.session, "houdinimcp_server") and hou.session.houdinimcp_server:
        hou.session.houdinimcp_server.stop()
        hou.session.houdinimcp_server = None
    else:
        print("Houdini MCP Server is not running.")

def initialize_plugin():
    import hou
    if not hasattr(hou.session, "houdinimcp_use_assetlib"):
        hou.session.houdinimcp_use_assetlib = False
    start_server()

# Do not auto-start on import. pythonX.Ylibs/uiready.py calls start_server()
# after the UI exists (QTimer). Headless uses scripts/headless_server.py.
