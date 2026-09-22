"""Takes management handlers."""
import hou


def list_takes():
    """List all takes in the scene."""
    takes = []
    for take in hou.takes.takes():
        takes.append({
            "name": take.name(),
            "is_current": take.isCurrent(),
            "children": [c.name() for c in take.children()],
        })
    return {"count": len(takes), "takes": takes}


def get_current_take():
    """Get the current take."""
    take = hou.takes.currentTake()
    return {
        "name": take.name(),
        "parm_count": len(take.parmTuples()),
    }


def set_current_take(take_name):
    """Set the current take by name."""
    for take in hou.takes.takes():
        if take.name() == take_name:
            take.setCurrent()
            return {"name": take_name, "set": True}
    raise ValueError(f"Take not found: {take_name}")


def create_take(name, parent_name=None):
    """Create a new take, optionally under a parent take."""
    parent = None
    if parent_name:
        for take in hou.takes.takes():
            if take.name() == parent_name:
                parent = take
                break
        if not parent:
            raise ValueError(f"Parent take not found: {parent_name}")
    new_take = hou.takes.addTake(name, parent)
    return {"name": new_take.name(), "created": True}
