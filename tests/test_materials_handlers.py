"""Tests for materials handlers."""
import sys
import os
import types

import pytest

if "hou" not in sys.modules:
    pytest.skip("hou mock not loaded", allow_module_level=True)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from houdinimcp.handlers.materials import (
    list_materials, get_material_info, create_material_network,
    assign_material, list_material_types,
)


class MockParm:
    def __init__(self, name, value=""):
        self._name = name
        self._value = value

    def name(self):
        return self._name

    def label(self):
        return self._name

    def eval(self):
        return self._value

    def set(self, val):
        self._value = val

    def isAtDefault(self):
        return self._value == ""

    def parmTemplate(self):
        return types.SimpleNamespace(type=lambda: types.SimpleNamespace(name=lambda: "String"))


class MockNode:
    def __init__(self, name, path, node_type="principledshader", children=None, parms=None):
        self._name = name
        self._path = path
        self._type = node_type
        self._children = children or []
        self._parms = {p.name(): p for p in (parms or [])}
        self._created = None

    def name(self):
        return self._name

    def path(self):
        return self._path

    def type(self):
        return types.SimpleNamespace(
            name=lambda: self._type,
            description=lambda: f"{self._type} node",
        )

    def children(self):
        return self._children

    def parms(self):
        return list(self._parms.values())

    def parm(self, name):
        return self._parms.get(name)

    def node(self, name):
        return None

    def createNode(self, node_type, node_name=None):
        name = node_name or node_type
        self._created = MockNode(name, f"{self._path}/{name}", node_type)
        return self._created


class TestMaterialsHandlers:
    def setup_method(self):
        self._orig_node = sys.modules["hou"].node

    def teardown_method(self):
        sys.modules["hou"].node = self._orig_node

    def test_list_materials(self):
        mat1 = MockNode("shader1", "/mat/shader1", "principledshader")
        mat_net = MockNode("mat", "/mat", children=[mat1])
        sys.modules["hou"].node = lambda p: mat_net if p == "/mat" else None
        result = list_materials()
        assert result["count"] == 1
        assert result["materials"][0]["name"] == "shader1"

    def test_list_materials_not_found(self):
        sys.modules["hou"].node = lambda p: None
        with pytest.raises(ValueError, match="Material network not found"):
            list_materials()

    def test_get_material_info(self):
        parm = MockParm("basecolor_r", "1.0")
        mat = MockNode("shader1", "/mat/shader1", parms=[parm])
        sys.modules["hou"].node = lambda p: mat if p == "/mat/shader1" else None
        result = get_material_info("/mat/shader1")
        assert result["type"] == "principledshader"
        assert "basecolor_r" in result["non_default_parms"]

    def test_create_material_network(self):
        parent = MockNode("obj", "/obj")
        sys.modules["hou"].node = lambda p: parent if p == "/obj" else None
        result = create_material_network("/obj", "mymat")
        assert result["name"] == "mymat"

    def test_assign_material(self):
        mat_parm = MockParm("shop_materialpath")
        target = MockNode("geo1", "/obj/geo1", parms=[mat_parm])
        mat = MockNode("shader1", "/mat/shader1")
        nodes = {"/obj/geo1": target, "/mat/shader1": mat}
        sys.modules["hou"].node = lambda p: nodes.get(p)
        result = assign_material("/obj/geo1", "/mat/shader1")
        assert result["assigned"] is True
        assert mat_parm._value == "/mat/shader1"

    def test_list_material_types(self):
        result = list_material_types()
        assert "count" in result
