"""Tests for DOP handlers."""
import sys
import os
import types

import pytest

if "hou" not in sys.modules:
    pytest.skip("hou mock not loaded", allow_module_level=True)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from houdinimcp.handlers.dops import (
    get_simulation_info, list_dop_objects, get_dop_object,
    step_simulation, reset_simulation, get_sim_memory_usage,
)


class MockDopObject:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name

    def objectType(self):
        return types.SimpleNamespace(name=lambda: "rbdpackedobject")

    def records(self):
        return []

    def relationships(self):
        return []


class MockSimulation:
    def __init__(self):
        self._objects = [MockDopObject("obj1")]

    def memoryUsage(self):
        return 1024

    def time(self):
        return 0.0

    def objects(self):
        return self._objects

    def findObject(self, name):
        for o in self._objects:
            if o.name() == name:
                return o
        return None

    def clear(self):
        pass


class MockDopNode:
    def __init__(self, path, sim=None):
        self._path = path
        self._sim = sim or MockSimulation()

    def path(self):
        return self._path

    def simulation(self):
        return self._sim


class TestDopHandlers:
    def setup_method(self):
        self._orig_node = sys.modules["hou"].node
        self.sim = MockSimulation()
        self.node = MockDopNode("/obj/dopnet1", self.sim)
        sys.modules["hou"].node = lambda p: self.node if p == "/obj/dopnet1" else None

    def teardown_method(self):
        sys.modules["hou"].node = self._orig_node

    def test_get_simulation_info(self):
        result = get_simulation_info("/obj/dopnet1")
        assert result["memory"] == 1024
        assert result["objects"] == 1

    def test_list_dop_objects(self):
        result = list_dop_objects("/obj/dopnet1")
        assert result["count"] == 1
        assert result["objects"][0]["name"] == "obj1"

    def test_get_dop_object(self):
        result = get_dop_object("/obj/dopnet1", "obj1")
        assert result["name"] == "obj1"

    def test_get_dop_object_not_found(self):
        with pytest.raises(ValueError, match="DOP object not found"):
            get_dop_object("/obj/dopnet1", "missing")

    def test_reset_simulation(self):
        result = reset_simulation("/obj/dopnet1")
        assert result["reset"] is True

    def test_get_sim_memory_usage(self):
        result = get_sim_memory_usage("/obj/dopnet1")
        assert result["memory_bytes"] == 1024

    def test_step_simulation(self):
        sys.modules["hou"].intFrame = lambda: 1
        frame_val = [1]
        sys.modules["hou"].setFrame = lambda f: frame_val.__setitem__(0, f)
        sys.modules["hou"].intFrame = lambda: frame_val[0]
        result = step_simulation("/obj/dopnet1", 2)
        assert result["steps"] == 2

    def test_node_not_found(self):
        sys.modules["hou"].node = lambda p: None
        with pytest.raises(ValueError, match="Node not found"):
            get_simulation_info("/obj/missing")
