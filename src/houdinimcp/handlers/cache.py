"""Cache management handlers."""
import hou


def list_caches(root_path="/obj"):
    """List all nodes with cache data."""
    root = hou.node(root_path)
    if not root:
        raise ValueError(f"Root not found: {root_path}")
    caches = []
    for node in root.allSubChildren():
        cache_parm = node.parm("cachedir") or node.parm("sopoutput") or node.parm("file")
        if cache_parm:
            caches.append({
                "path": node.path(),
                "type": node.type().name(),
                "cache_parm": cache_parm.name(),
                "cache_value": cache_parm.eval(),
            })
    return {"count": len(caches), "caches": caches}


def get_cache_status(path):
    """Get cache status for a file cache node."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    status = {"path": path, "type": node.type().name()}
    for parm_name in ["cachedir", "sopoutput", "file", "loadfromdisk", "basename"]:
        parm = node.parm(parm_name)
        if parm:
            status[parm_name] = str(parm.eval())
    return status


def clear_cache(path):
    """Clear cache on a file cache node by pressing the clear button."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    # Try common clear/delete cache button names
    for btn_name in ["clearcache", "clear", "execute"]:
        parm = node.parm(btn_name)
        if parm:
            parm.pressButton()
            return {"path": path, "cleared": True, "button": btn_name}
    raise ValueError(f"No clear cache button found on {path}")


def write_cache(path, frame_range=None):
    """Write cache for a file cache node."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    # Try common write/save buttons
    for btn_name in ["execute", "save", "render"]:
        parm = node.parm(btn_name)
        if parm:
            if frame_range and len(frame_range) == 2:
                f1 = node.parm("f1")
                f2 = node.parm("f2")
                if f1:
                    f1.set(frame_range[0])
                if f2:
                    f2.set(frame_range[1])
            parm.pressButton()
            return {"path": path, "writing": True, "button": btn_name}
    raise ValueError(f"No write cache button found on {path}")
