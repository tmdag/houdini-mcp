"""Tests for VEX handlers."""
import sys
import os
import types

import pytest

if "hou" not in sys.modules:
    pytest.skip("hou mock not loaded", allow_module_level=True)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


class _NullContext:
    """Stand-in for hou.undos.disabler()."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _setup_hou_text():
    hou = sys.modules["hou"]
    if not hasattr(hou, "text"):
        hou.text = types.SimpleNamespace(
            vexSyntaxCheck=lambda code: "" if "error" not in code else "Syntax error at line 1",
        )
    # validate_vex wraps its scratch node in hou.undos.disabler() so a
    # validation does not land in the artist's undo stack.
    if not hasattr(hou.undos, "disabler"):
        hou.undos.disabler = lambda: _NullContext()


class MockParm:
    def __init__(self, name, value=""):
        self._name = name
        self._value = value

    def name(self):
        return self._name

    def set(self, val):
        self._value = val

    def eval(self):
        return self._value


class MockCreatedNode:
    def __init__(self, name, path, node_type):
        self._name = name
        self._path = path
        self._type = node_type
        self._parms = {"snippet": MockParm("snippet"), "class": MockParm("class", 1)}

    def name(self):
        return self._name

    def path(self):
        return self._path

    def type(self):
        return types.SimpleNamespace(name=lambda: self._type)

    def parm(self, name):
        return self._parms.get(name)


class MockParentNode:
    def __init__(self, path):
        self._path = path
        self._created = None

    def path(self):
        return self._path

    def createNode(self, node_type, node_name=None):
        name = node_name or node_type
        self._created = MockCreatedNode(name, f"{self._path}/{name}", node_type)
        return self._created


from houdinimcp.handlers.vex import (
    create_wrangle, set_wrangle_code, get_wrangle_code,
    create_vex_expression, validate_vex,
)


class TestVexHandlers:
    def setup_method(self):
        _setup_hou_text()
        self._orig_node = sys.modules["hou"].node
        self.parent = MockParentNode("/obj/geo1")
        self.wrangle = MockCreatedNode("wrangle1", "/obj/geo1/wrangle1", "attribwrangle")
        nodes = {"/obj/geo1": self.parent, "/obj/geo1/wrangle1": self.wrangle}
        sys.modules["hou"].node = lambda p: nodes.get(p)

    def teardown_method(self):
        sys.modules["hou"].node = self._orig_node

    def test_create_wrangle(self):
        result = create_wrangle("/obj/geo1", code="@Cd = {1,0,0};")
        assert result["type"] == "attribwrangle"

    def test_set_wrangle_code(self):
        result = set_wrangle_code("/obj/geo1/wrangle1", "@P.y += 1;")
        assert result["code_length"] > 0
        assert self.wrangle._parms["snippet"]._value == "@P.y += 1;"

    def test_get_wrangle_code(self):
        self.wrangle._parms["snippet"]._value = "@P *= 2;"
        result = get_wrangle_code("/obj/geo1/wrangle1")
        assert result["code"] == "@P *= 2;"

    def test_create_vex_expression(self):
        result = create_vex_expression("/obj/geo1", "dist", "length(@P)")
        assert "@dist" in result["code"]

    # validate_vex now compiles the snippet on a throwaway wrangle, because
    # hou.text.vexSyntaxCheck() does not exist on H22 and raised
    # AttributeError for every input.

    def _stub_temp_wrangle(self, errors=(), warnings=()):
        """Make hou.node('/obj').createNode(...) yield a wrangle we control."""
        _setup_hou_text()
        wrangle = MockCreatedNode("attribwrangle1",
                                  "/obj/mcp_vex_validate_tmp/attribwrangle1",
                                  "attribwrangle")
        wrangle.errors = lambda: list(errors)
        wrangle.warnings = lambda: list(warnings)
        wrangle.cook = lambda force=False: None
        holder = MockParentNode("/obj/mcp_vex_validate_tmp")
        holder.createNode = lambda *a, **kw: wrangle
        holder.destroy = lambda: None
        obj = MockParentNode("/obj")
        obj.createNode = lambda *a, **kw: holder
        sys.modules["hou"].node = lambda p: obj if p == "/obj" else None
        return wrangle

    def test_validate_vex_valid(self):
        self._stub_temp_wrangle()
        result = validate_vex("@P.y += 1;")
        assert result["valid"] is True
        assert result["errors"] is None
        assert result["context"] == "sop"

    def test_validate_vex_invalid(self):
        self._stub_temp_wrangle(errors=["Syntax error, unexpected ';' (1,9)"])
        result = validate_vex("int x = ;;;")
        assert result["valid"] is False
        assert "Syntax error" in result["errors"][0]

    def test_validate_vex_rejects_unknown_context(self):
        with pytest.raises(ValueError, match="context must be one of"):
            validate_vex("@P.y += 1;", context="dop")


class TestRunOverMapping:
    """The class menu is 0 Detail, 1 Primitives, 2 Points, 3 Vertices.

    The old map was {"Detail":0,"Points":1,"Vertices":2,"Primitives":3}, so
    every value but Detail built the wrong kind of wrangle and the snippet
    silently wrote to the wrong attribute class.
    """

    def test_menu_indices_match_the_node(self):
        from houdinimcp.handlers.vex import _run_over_value
        assert _run_over_value("Detail") == 0
        assert _run_over_value("Primitives") == 1
        assert _run_over_value("Points") == 2
        assert _run_over_value("Vertices") == 3
        assert _run_over_value("Numbers") == 4

    def test_common_spellings(self):
        from houdinimcp.handlers.vex import _run_over_value
        assert _run_over_value("prim") == _run_over_value("primitives") == 1
        assert _run_over_value("pts") == _run_over_value("point") == 2
        assert _run_over_value("vtx") == _run_over_value("vertex") == 3

    def test_unknown_raises_instead_of_defaulting(self):
        from houdinimcp.handlers.vex import _run_over_value
        with pytest.raises(ValueError, match="run_over must be one of"):
            _run_over_value("Edges")

    def test_set_wrangle_node_not_found(self):
        sys.modules["hou"].node = lambda p: None
        with pytest.raises(ValueError, match="Node not found"):
            set_wrangle_code("/obj/missing", "code")

    def test_create_wrangle_parent_not_found(self):
        sys.modules["hou"].node = lambda p: None
        with pytest.raises(ValueError, match="Parent not found"):
            create_wrangle("/obj/missing")
