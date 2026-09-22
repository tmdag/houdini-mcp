"""Tests for takes handlers."""
import sys
import os
import types

import pytest

if "hou" not in sys.modules:
    pytest.skip("hou mock not loaded", allow_module_level=True)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


def _setup_takes_mock():
    hou = sys.modules["hou"]

    class MockTake:
        def __init__(self, name, is_current=False):
            self._name = name
            self._is_current = is_current

        def name(self):
            return self._name

        def isCurrent(self):
            return self._is_current

        def setCurrent(self):
            self._is_current = True

        def children(self):
            return []

        def parmTuples(self):
            return []

    main_take = MockTake("Main", is_current=True)
    render_take = MockTake("Render")
    all_takes = [main_take, render_take]

    hou.takes = types.SimpleNamespace(
        takes=lambda: all_takes,
        currentTake=lambda: main_take,
        addTake=lambda name, parent=None: MockTake(name),
    )


from houdinimcp.handlers.takes import (
    list_takes, get_current_take, set_current_take, create_take,
)


class TestTakesHandlers:
    def setup_method(self):
        _setup_takes_mock()

    def test_list_takes(self):
        result = list_takes()
        assert result["count"] == 2
        assert result["takes"][0]["name"] == "Main"

    def test_get_current_take(self):
        result = get_current_take()
        assert result["name"] == "Main"

    def test_set_current_take(self):
        result = set_current_take("Render")
        assert result["set"] is True

    def test_set_current_take_not_found(self):
        with pytest.raises(ValueError, match="Take not found"):
            set_current_take("NonExistent")

    def test_create_take(self):
        result = create_take("NewTake")
        assert result["created"] is True
        assert result["name"] == "NewTake"

    def test_create_take_with_parent(self):
        result = create_take("ChildTake", parent_name="Main")
        assert result["created"] is True

    def test_create_take_parent_not_found(self):
        with pytest.raises(ValueError, match="Parent take not found"):
            create_take("ChildTake", parent_name="Missing")
