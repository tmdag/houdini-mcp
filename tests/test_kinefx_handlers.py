"""KineFX / Mixamo helpers."""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import tests.test_server_commands  # noqa: F401  hou mock

from houdinimcp.handlers.kinefx import (
    list_joints, import_fbx_character, import_fbx_animation, _require_mcp,
    attach_kinefx_deform, pose_hash, map_joint_names, map_kinefx_joints,
    normalize_joint_name,
)


class TestKinefx:
    def setup_method(self):
        self._orig_node = sys.modules["hou"].node

    def teardown_method(self):
        sys.modules["hou"].node = self._orig_node

    def test_require_mcp_rejects_show(self):
        with pytest.raises(ValueError, match="mcp_"):
            _require_mcp("/obj/hero")

    def test_list_joints(self):
        pt = types.SimpleNamespace(
            number=lambda: 0,
            position=lambda: (1.0, 2.0, 3.0),
            attribValue=lambda n: "hips" if n == "name" else None,
        )
        geo = types.SimpleNamespace(
            points=lambda: [pt],
            findPointAttrib=lambda n: object() if n == "name" else None,
            pointAttribs=lambda: [types.SimpleNamespace(name=lambda: "name")],
        )
        node = types.SimpleNamespace(geometry=lambda: geo)
        sys.modules["hou"].node = lambda p: node if p == "/obj/mcp_character/fbx" else None
        result = list_joints("/obj/mcp_character/fbx")
        assert result["count"] == 1
        assert result["joints"][0]["name"] == "hips"
        assert result["has_name"] is True

    def test_import_missing_file(self):
        with pytest.raises(ValueError, match="FBX not found"):
            import_fbx_character("/no/such.fbx", parent_path="/obj/mcp_character")

    def test_import_anim_missing_parent(self, tmp_path):
        fbx = tmp_path / "clip.fbx"
        fbx.write_bytes(b"fbx")
        sys.modules["hou"].node = lambda p: None
        with pytest.raises(ValueError, match="Parent not found"):
            import_fbx_animation(str(fbx), parent_path="/obj/mcp_character")

    def test_list_joints_refuses_capture_mesh(self):
        pts = [types.SimpleNamespace(
            number=lambda i=i: i,
            position=lambda: (0.0, 0.0, 0.0),
            attribValue=lambda n: None,
        ) for i in range(3000)]
        geo = types.SimpleNamespace(
            points=lambda: pts,
            findPointAttrib=lambda n: None,
            pointAttribs=lambda: [],
        )
        node = types.SimpleNamespace(geometry=lambda: geo)
        sys.modules["hou"].node = lambda p: node
        with pytest.raises(ValueError, match="capture/skin mesh"):
            list_joints("/obj/mcp_character/capybara")


class _Parm:
    def __init__(self, value=None):
        self.value = value

    def set(self, val):
        self.value = val

    def eval(self):
        return self.value


class _GraphNode:
    def __init__(self, name, path, node_type, graph):
        self._name = name
        self._path = path
        self._type = node_type
        self._graph = graph
        self._parms = {}
        self.inputs = {}
        self.display = False
        self.render = False
        self.cooked = False

    def name(self):
        return self._name

    def path(self):
        return self._path

    def type(self):
        return types.SimpleNamespace(name=lambda: self._type)

    def node(self, name):
        return self._graph.nodes.get(self._path + "/" + name)

    def createNode(self, node_type, node_name=None):
        n = node_name or node_type.replace(":", "_")
        child = _GraphNode(n, self._path + "/" + n, node_type, self._graph)
        self._graph.nodes[child.path()] = child
        return child

    def parm(self, name):
        if name not in self._parms:
            self._parms[name] = _Parm()
        return self._parms[name]

    def setInput(self, idx, node, output_idx=0):
        self.inputs[idx] = (node.path(), output_idx)

    def setDisplayFlag(self, v):
        self.display = v

    def setRenderFlag(self, v):
        self.render = v

    def layoutChildren(self):
        pass

    def cook(self, force=False):
        self.cooked = True

    def geometry(self):
        frame = sys.modules["hou"].intFrame()
        pt = types.SimpleNamespace(position=lambda f=frame: (float(f), 1.0, 2.0))
        prims = [object()] * 8
        return types.SimpleNamespace(
            points=lambda: [pt, pt, pt, pt],
            prims=lambda: prims,
            attribValue=lambda n: (1, 8) if n == "clipinfo" else None,
            findGlobalAttrib=lambda n: object() if n == "clipinfo" else None,
        )


class TestAttachKinefxDeform:
    def setup_method(self):
        hou = sys.modules["hou"]
        self._orig_node = hou.node
        self._orig_playbar = hou.playbar
        self._orig_setFrame = getattr(hou, "setFrame", None)
        self._orig_intFrame = getattr(hou, "intFrame", None)
        self.graph = types.SimpleNamespace(nodes={})
        obj = _GraphNode("obj", "/obj", "objnet", self.graph)
        self.graph.nodes["/obj"] = obj
        hou.node = lambda p, g=self.graph: g.nodes.get(p)
        hou.setFrame = lambda f: setattr(hou, "_frame", int(f))
        hou.intFrame = lambda: getattr(hou, "_frame", 1)
        hou._frame = 1
        hou.playbar = types.SimpleNamespace(
            setFrameRange=lambda a, b: setattr(hou, "_range", (a, b)),
            setPlaybackRange=lambda a, b: setattr(hou, "_play", (a, b)),
            addEventCallback=lambda cb: None,
            removeEventCallback=lambda cb: None,
            frameRange=lambda: (1, 240),
        )

    def teardown_method(self):
        hou = sys.modules["hou"]
        hou.node = self._orig_node
        hou.playbar = self._orig_playbar
        if self._orig_setFrame is not None:
            hou.setFrame = self._orig_setFrame
        if self._orig_intFrame is not None:
            hou.intFrame = self._orig_intFrame

    def test_rejects_non_mcp(self):
        with pytest.raises(ValueError, match="mcp_"):
            attach_kinefx_deform(parent_path="/obj/hero")

    def test_capy_wires_jointdeform_and_proof_moves(self):
        result = attach_kinefx_deform(
            parent_path="/obj/mcp_character", source="capybara",
            clip="elbowdrop", proof=True,
        )
        deform = self.graph.nodes[result["path"]]
        assert deform._type == "kinefx::jointdeform"
        assert deform.display is True
        assert 0 in deform.inputs and 1 in deform.inputs and 2 in deform.inputs
        assert deform.inputs[0][1] == 0
        assert deform.inputs[1][1] == 1
        eval_node = self.graph.nodes[result["eval"]]
        assert eval_node._type == "kinefx::motionclipevaluate"
        assert eval_node.inputs[0][1] == 2
        capy = self.graph.nodes[result["capy"]]
        assert capy._parms["outputclip"].value == 1
        assert capy._parms["clip"].value == "elbowdrop"
        assert capy._parms["addshader"].value == 0
        assert capy._parms["addnormalmap"].value == 0
        assert capy._parms["sss_enable"].value == 0
        assert result["hashes"]["moved"] is True
        assert result["hashes"]["start"]["hash"] != result["hashes"]["end"]["hash"]
        assert result["range"] == [1, 8]

    def test_nodes_source_requires_paths(self):
        with pytest.raises(ValueError, match="rest_path"):
            attach_kinefx_deform(parent_path="/obj/mcp_character", source="nodes")


class TestMapJoints:
    def test_mixamo_prefix_maps(self):
        mapped = map_joint_names(
            ["hips", "spine", "head"],
            ["mixamorig:Hips", "mixamorig:Spine", "mixamorig:Head"],
        )
        by_clip = {m["clip"]: m["rest"] for m in mapped}
        assert by_clip["mixamorig:Hips"] == "hips"
        assert by_clip["mixamorig:Spine"] == "spine"
        assert normalize_joint_name("mixamorig:Hips") == "hips"

    def test_unmapped_raises(self):
        with pytest.raises(ValueError, match="Unmapped clip joints"):
            map_joint_names(["hips"], ["mixamorig:Hips", "mixamorig:Tail"])

    def test_map_kinefx_joints_shipped(self):
        def _skel(names):
            pts = []
            for i, n in enumerate(names):
                pts.append(types.SimpleNamespace(
                    number=lambda i=i: i,
                    position=lambda: (float(i), 0.0, 0.0),
                    attribValue=lambda a, n=n: n if a == "name" else None,
                ))
            geo = types.SimpleNamespace(
                points=lambda pts=pts: pts,
                findPointAttrib=lambda n: object() if n in ("name", "transform") else None,
                pointAttribs=lambda: [types.SimpleNamespace(name=lambda: "name")],
            )
            return types.SimpleNamespace(geometry=lambda geo=geo: geo)
        rest = _skel(["hips", "spine"])
        clip = _skel(["mixamorig:Hips", "mixamorig:Spine"])
        hou = sys.modules["hou"]
        orig = hou.node
        hou.node = lambda p: rest if p.endswith("rest") else clip if p.endswith("clip") else None
        try:
            out = map_kinefx_joints("/obj/mcp_character/rest", "/obj/mcp_character/clip")
        finally:
            hou.node = orig
        assert out["count"] == 2
        assert out["map"][0]["rest"] == "hips"

    def test_map_kinefx_joints_unmapped_errors(self):
        def _skel(names):
            pts = [
                types.SimpleNamespace(
                    number=lambda i=i: i,
                    position=lambda: (0.0, 0.0, 0.0),
                    attribValue=lambda a, n=n: n if a == "name" else None,
                )
                for i, n in enumerate(names)
            ]
            geo = types.SimpleNamespace(
                points=lambda pts=pts: pts,
                findPointAttrib=lambda n: object() if n == "name" else None,
                pointAttribs=lambda: [types.SimpleNamespace(name=lambda: "name")],
            )
            return types.SimpleNamespace(geometry=lambda geo=geo: geo)
        hou = sys.modules["hou"]
        orig = hou.node
        hou.node = lambda p: (
            _skel(["hips"]) if p.endswith("rest") else _skel(["mixamorig:Hips", "tail"])
        )
        try:
            with pytest.raises(ValueError, match="Unmapped clip joints"):
                map_kinefx_joints("/obj/mcp_character/rest", "/obj/mcp_character/clip")
        finally:
            hou.node = orig
