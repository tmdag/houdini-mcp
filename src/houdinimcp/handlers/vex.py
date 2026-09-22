"""VEX wrangle creation and validation handlers."""
import hou


# attribwrangle "class" menu order, straight from the node:
#   0 Detail (only once) | 1 Primitives | 2 Points | 3 Vertices | 4 Numbers
# The previous map was {"Detail":0,"Points":1,"Vertices":2,"Primitives":3},
# so every value except Detail was wrong: asking for Points built a
# Primitives wrangle and asking for Primitives built a Vertices one. The
# node cooked without error and wrote the attribute to the wrong class.
RUN_OVER = {
    "detail": 0,
    "primitives": 1, "primitive": 1, "prim": 1, "prims": 1,
    "points": 2, "point": 2, "pt": 2, "pts": 2,
    "vertices": 3, "vertex": 3, "vtx": 3,
    "numbers": 4, "number": 4,
}


def _run_over_value(run_over):
    """Menu index for a run-over name. Raises rather than guessing."""
    key = str(run_over or "points").strip().lower()
    if key not in RUN_OVER:
        raise ValueError(
            "run_over must be one of Detail, Primitives, Points, Vertices, "
            "Numbers; got %r" % (run_over,)
        )
    return RUN_OVER[key]


def create_wrangle(parent_path, wrangle_type="attribwrangle", name=None,
                   code="", run_over=None, input_path=None):
    """Create a VEX wrangle, optionally wired up and set to a run-over class.

    run_over was previously unreachable, so every wrangle this tool made ran
    over whatever the node defaulted to -- Points -- and a snippet written
    for primitives silently wrote point attributes.
    """
    parent = hou.node(parent_path)
    if not parent:
        raise ValueError(f"Parent not found: {parent_path}")
    node = parent.createNode(wrangle_type, node_name=name)
    if code:
        snippet_parm = node.parm("snippet")
        if snippet_parm:
            snippet_parm.set(code)
    applied = None
    if run_over is not None:
        class_parm = node.parm("class")
        if class_parm is None:
            raise ValueError(
                "%s has no 'class' parameter; run_over does not apply"
                % wrangle_type
            )
        class_parm.set(_run_over_value(run_over))
        applied = class_parm.parmTemplate().menuLabels()[class_parm.eval()]
    if input_path:
        # A half-wired node left behind meant a retry created a second one.
        source = hou.node(input_path)
        if source is None:
            node.destroy()
            raise ValueError(f"Input not found: {input_path}")
        if source.parent() != parent:
            where = source.parent().path()
            node.destroy()
            raise ValueError(
                "input_path must be in the same network as parent_path: "
                "%s is in %s, not %s" % (input_path, where, parent.path())
            )
        try:
            node.setInput(0, source)
        except hou.OperationFailed:
            node.destroy()
            raise
    return {"path": node.path(), "name": node.name(), "type": wrangle_type,
            "run_over": applied, "input": input_path}


def set_wrangle_code(node_path, code):
    """Set the VEX code on a wrangle node."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    parm = node.parm("snippet")
    if not parm:
        raise ValueError(f"Node {node_path} has no 'snippet' parameter")
    parm.set(code)
    return {"path": node_path, "code_length": len(code)}


def get_wrangle_code(node_path):
    """Get the VEX code from a wrangle node."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    parm = node.parm("snippet")
    if not parm:
        raise ValueError(f"Node {node_path} has no 'snippet' parameter")
    return {"path": node_path, "code": parm.eval()}


def create_vex_expression(parent_path, attrib_name, expression, run_over="Points"):
    """Create a wrangle node that evaluates a VEX expression and stores it in an attribute."""
    parent = hou.node(parent_path)
    if not parent:
        raise ValueError(f"Parent not found: {parent_path}")
    code = f'@{attrib_name} = {expression};'
    node = parent.createNode("attribwrangle", node_name=f"expr_{attrib_name}")
    node.parm("snippet").set(code)
    class_parm = node.parm("class")
    if class_parm:
        class_parm.set(_run_over_value(run_over))
    return {"path": node.path(), "attrib": attrib_name, "code": code}


# Wrangle type and snippet parm per VEX context.
# (container node type, wrangle type, snippet parm). The container matters:
# geo.createNode("channelwrangle") raises, because a CHOP wrangle cannot live
# in a SOP network. The previous table discarded the category and built
# everything under /obj/geo, so "lop" quietly validated SOP VEX and "chop"
# threw instead of returning {valid: false}. "pop" is gone: popwrangle is a
# DOP, and mapping it to a SOP wrangle was simply wrong.
_WRANGLE_FOR_CONTEXT = {
    "sop": ("geo", "attribwrangle", "snippet"),
    "lop": ("lopnet", "attribwrangle", "snippet"),
    "chop": ("chopnet", "channelwrangle", "snippet"),
}


def validate_vex(code, context="sop"):
    """Compile a VEX snippet and report the compiler's own errors.

    hou.text.vexSyntaxCheck() does not exist on H22 -- calling it raised
    AttributeError, so this tool reported every snippet as a server error
    rather than validating anything. The only honest check is to hand the
    snippet to a real wrangle and cook it, which is what Houdini does when
    you press Enter in the parameter anyway.
    """
    context = (context or "sop").strip().lower()
    if context not in _WRANGLE_FOR_CONTEXT:
        raise ValueError(
            "context must be one of %s, got %r"
            % (", ".join(sorted(_WRANGLE_FOR_CONTEXT)), context)
        )
    container, node_type, snippet_parm = _WRANGLE_FOR_CONTEXT[context]
    root = hou.node("/obj")
    if root is None:
        raise RuntimeError("/obj does not exist; cannot build a scratch network")

    holder = None
    # Creating and destroying a scratch node is an ordinary undoable edit, so
    # without this every validate landed in the artist's undo stack.
    with hou.undos.disabler():
        try:
            holder = root.createNode(
                container, "mcp_vex_validate_tmp", run_init_scripts=False)
            wrangle = holder.createNode(node_type)
            wrangle.parm(snippet_parm).set(code)
            try:
                wrangle.cook(force=True)
            except hou.OperationFailed:
                pass  # a compile failure is the answer, not an exception
            errors = [str(e) for e in (wrangle.errors() or [])]
            warnings = [str(w) for w in (wrangle.warnings() or [])]
        finally:
            if holder is not None:
                try:
                    holder.destroy()
                except Exception:
                    pass
    return {
        "valid": not errors,
        "context": context,
        "errors": errors or None,
        "warnings": warnings or None,
    }
