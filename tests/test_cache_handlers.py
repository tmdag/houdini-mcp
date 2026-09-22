"""Tests for cache handlers."""
import sys
import os
import types

import pytest

if "hou" not in sys.modules:
    pytest.skip("hou mock not loaded", allow_module_level=True)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from houdinimcp.handlers.cache import (
    list_caches, get_cache_status, clear_cache, write_cache,
)


class MockParm:
    def __init__(self, name, value=""):
        self._name = name
        self._value = value
        self._pressed = False

    def name(self):
        return self._name

    def eval(self):
        return self._value

    def set(self, val):
        self._value = val

    def pressButton(self):
        self._pressed = True


class MockCacheNode:
    def __init__(self, name, path, parms=None):
        self._name = name
        self._path = path
        self._parms = {p.name(): p for p in (parms or [])}

    def name(self):
        return self._name

    def path(self):
        return self._path

    def type(self):
        return types.SimpleNamespace(name=lambda: "filecache")

    def parm(self, name):
        return self._parms.get(name)


class MockRootNode:
    def __init__(self, children=None):
        self._children = children or []

    def allSubChildren(self):
        return self._children


class TestCacheHandlers:
    def setup_method(self):
        self._orig_node = sys.modules["hou"].node

    def teardown_method(self):
        sys.modules["hou"].node = self._orig_node

    def test_list_caches(self):
        cache = MockCacheNode("fc1", "/obj/geo1/fc1",
                              [MockParm("sopoutput", "/tmp/cache.$F4.bgeo.sc")])
        root = MockRootNode([cache])
        sys.modules["hou"].node = lambda p: root if p == "/obj" else None
        result = list_caches()
        assert result["count"] == 1

    def test_list_caches_empty(self):
        root = MockRootNode([])
        sys.modules["hou"].node = lambda p: root if p == "/obj" else None
        result = list_caches()
        assert result["count"] == 0

    def test_get_cache_status(self):
        node = MockCacheNode("fc1", "/obj/fc1",
                             [MockParm("sopoutput", "/tmp/cache.bgeo.sc"),
                              MockParm("loadfromdisk", "0")])
        sys.modules["hou"].node = lambda p: node if p == "/obj/fc1" else None
        result = get_cache_status("/obj/fc1")
        assert result["sopoutput"] == "/tmp/cache.bgeo.sc"

    def test_clear_cache(self):
        btn = MockParm("execute")
        node = MockCacheNode("fc1", "/obj/fc1", [btn])
        sys.modules["hou"].node = lambda p: node if p == "/obj/fc1" else None
        result = clear_cache("/obj/fc1")
        assert result["cleared"] is True
        assert btn._pressed is True

    def test_clear_cache_no_button(self):
        node = MockCacheNode("fc1", "/obj/fc1", [])
        sys.modules["hou"].node = lambda p: node if p == "/obj/fc1" else None
        with pytest.raises(ValueError, match="No clear cache button"):
            clear_cache("/obj/fc1")

    def test_write_cache(self):
        btn = MockParm("execute")
        node = MockCacheNode("fc1", "/obj/fc1", [btn])
        sys.modules["hou"].node = lambda p: node if p == "/obj/fc1" else None
        result = write_cache("/obj/fc1")
        assert result["writing"] is True

    def test_node_not_found(self):
        sys.modules["hou"].node = lambda p: None
        with pytest.raises(ValueError, match="Node not found"):
            get_cache_status("/obj/missing")
