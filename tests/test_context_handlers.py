"""Tests for context handlers (get_network_overview, get_cook_chain, etc.)."""
import sys
import os
import types

import pytest

# Ensure hou mock is available
if "hou" not in sys.modules:
    pytest.skip("hou mock not loaded", allow_module_level=True)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from houdinimcp.handlers.context import (
    get_network_overview, get_cook_chain, explain_node,
    get_scene_summary, get_selection, set_selection,
)


class MockNode:
    def __init__(self, name, path, node_type="geo", children=None, inputs=None):
        self._name = name
        self._path = path
        self._type = node_type
        self._children = children or []
        self._inputs = inputs or []
        self._selected = False
        self._comment = ""

    def name(self):
        return self._name

    def path(self):
        return self._path

    def type(self):
        return types.SimpleNamespace(
            name=lambda: self._type,
            description=lambda: f"{self._type} node",
            category=lambda: types.SimpleNamespace(name=lambda: "Sop"),
        )

    def children(self):
        return self._children

    def inputs(self):
        return self._inputs

    def outputs(self):
        return []

    def outputConnections(self):
        return []

    def parms(self):
        return []

    def comment(self):
        return self._comment

    def isSelected(self):
        return self._selected

    def setSelected(self, val):
        self._selected = val

    def allSubChildren(self):
        return self._children


class TestContextHandlers:
    def setup_method(self):
        self._orig_node = sys.modules["hou"].node
        self._orig_selected = getattr(sys.modules["hou"], "selectedNodes", None)
        self._orig_intFrame = getattr(sys.modules["hou"], "intFrame", None)

    def teardown_method(self):
        sys.modules["hou"].node = self._orig_node
        if self._orig_selected is not None:
            sys.modules["hou"].selectedNodes = self._orig_selected
        if self._orig_intFrame is not None:
            sys.modules["hou"].intFrame = self._orig_intFrame

    def test_get_network_overview(self):
        child1 = MockNode("box1", "/obj/box1", "box")
        child2 = MockNode("sphere1", "/obj/sphere1", "sphere")
        parent = MockNode("obj", "/obj", children=[child1, child2])
        sys.modules["hou"].node = lambda p: parent if p == "/obj" else None
        result = get_network_overview("/obj")
        assert result["node_count"] == 2
        assert result["nodes"][0]["name"] == "box1"

    def test_get_network_overview_not_found(self):
        sys.modules["hou"].node = lambda p: None
        with pytest.raises(ValueError, match="Node not found"):
            get_network_overview("/nonexistent")

    def test_get_cook_chain(self):
        node_a = MockNode("a", "/obj/a", "box")
        node_b = MockNode("b", "/obj/b", "xform", inputs=[node_a])
        nodes = {"/obj/a": node_a, "/obj/b": node_b}
        sys.modules["hou"].node = lambda p: nodes.get(p)
        result = get_cook_chain("/obj/b")
        assert len(result["chain"]) == 2
        assert result["chain"][0]["name"] == "a"
        assert result["chain"][1]["name"] == "b"

    def test_explain_node(self):
        node = MockNode("box1", "/obj/box1", "box")
        sys.modules["hou"].node = lambda p: node if p == "/obj/box1" else None
        result = explain_node("/obj/box1")
        assert result["type"] == "box"
        assert result["path"] == "/obj/box1"

    def test_get_scene_summary(self):
        child = MockNode("box1", "/obj/box1", "box")
        root = MockNode("root", "/", children=[child])
        sys.modules["hou"].node = lambda p: root if p == "/" else None
        sys.modules["hou"].intFrame = lambda: 1
        result = get_scene_summary()
        assert result["total_nodes"] == 1

    def test_get_selection(self):
        n1 = MockNode("box1", "/obj/box1")
        n1._selected = True
        sys.modules["hou"].selectedNodes = lambda: [n1]
        result = get_selection()
        assert result["count"] == 1
        assert result["nodes"][0]["path"] == "/obj/box1"

    def test_set_selection(self):
        n1 = MockNode("box1", "/obj/box1")
        n2 = MockNode("sphere1", "/obj/sphere1")
        nodes = {"/obj/box1": n1, "/obj/sphere1": n2}
        sys.modules["hou"].node = lambda p: nodes.get(p)
        sys.modules["hou"].selectedNodes = lambda: [n1]
        result = set_selection(["/obj/sphere1"])
        assert "/obj/sphere1" in result["selected"]
        assert n1._selected is False
        assert n2._selected is True

    def test_set_selection_not_found(self):
        sys.modules["hou"].node = lambda p: None
        sys.modules["hou"].selectedNodes = lambda: []
        with pytest.raises(ValueError, match="Node not found"):
            set_selection(["/obj/nonexistent"])
