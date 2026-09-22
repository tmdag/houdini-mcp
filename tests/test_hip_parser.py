"""Tests for hip_parser.py — .hip cpio format parser."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from hip_parser import (
    _read_sections,
    _parse_init,
    _parse_inputs,
    _parse_parms,
    _parse_comment,
    _parse_postit_text,
    _parse_netbox_comment,
    _node_category,
    _decode_body,
    parse_hip_bytes,
)


# ---------------------------------------------------------------------------
# Helpers: build cpio sections for test fixtures
# ---------------------------------------------------------------------------
def _make_cpio_entry(name, body):
    """Build a single cpio archive entry (070707 format)."""
    name_bytes = name.encode("ascii") + b"\x00"
    if isinstance(body, str):
        body_bytes = body.encode("ascii")
    else:
        body_bytes = body
    # Header: 070707 + dev(6) + ino(6) + mode(6) + uid(6) + gid(6) +
    #          nlinks(6) + rdev(6) + mtime(11) + namesize(6) + filesize(11)
    header = (
        f"070707"
        f"000001"  # dev
        f"000000"  # ino
        f"000666"  # mode
        f"000000"  # uid
        f"000000"  # gid
        f"000001"  # nlinks
        f"000000"  # rdev
        f"00000000000"  # mtime
        f"{len(name_bytes):06o}"
        f"{len(body_bytes):011o}"
    )
    return header.encode("ascii") + name_bytes + body_bytes


def _make_hip(*entries):
    """Build a minimal .hip archive from (name, body) pairs."""
    parts = [_make_cpio_entry(n, b) for n, b in entries]
    parts.append(_make_cpio_entry("TRAILER!!!", ""))
    return b"".join(parts)


# ---------------------------------------------------------------------------
# _read_sections
# ---------------------------------------------------------------------------
class TestReadSections:
    def test_single_section(self):
        data = _make_hip((".start", "fps 24\ntcur 0"))
        sections = _read_sections(data)
        assert ".start" in sections
        assert b"fps 24" in sections[".start"]

    def test_multiple_sections(self):
        data = _make_hip(
            (".start", "fps 24"),
            ("obj/box1.init", "type = box"),
        )
        sections = _read_sections(data)
        assert len(sections) >= 2
        assert ".start" in sections
        assert "obj/box1.init" in sections

    def test_trailer_is_included(self):
        data = _make_hip((".start", "fps 24"))
        sections = _read_sections(data)
        assert "TRAILER!!!" in sections

    def test_empty_body(self):
        data = _make_hip((".OPlibraries", ""))
        sections = _read_sections(data)
        assert sections[".OPlibraries"] == b""


# ---------------------------------------------------------------------------
# _decode_body
# ---------------------------------------------------------------------------
class TestDecodeBody:
    def test_strips_leading_nulls(self):
        assert _decode_body(b"\x00\x00hello") == "hello"

    def test_normal_bytes(self):
        assert _decode_body(b"hello") == "hello"


# ---------------------------------------------------------------------------
# _parse_init
# ---------------------------------------------------------------------------
class TestParseInit:
    def test_basic_type(self):
        assert _parse_init(b"type = box\nmatchesdef = 0") == "box"

    def test_with_leading_null(self):
        assert _parse_init(b"\x00type = geo\nmatchesdef = 1") == "geo"

    def test_no_type_line(self):
        assert _parse_init(b"matchesdef = 0") is None


# ---------------------------------------------------------------------------
# _parse_inputs
# ---------------------------------------------------------------------------
class TestParseInputs:
    def test_single_connection(self):
        body = b"""sopflags sopflags =
comment ""
inputs
{
0 \tgrid1 0 1
}
end"""
        conns = _parse_inputs(body)
        assert len(conns) == 1
        assert conns[0] == {"dst_input": 0, "src_name": "grid1", "src_output": 0}

    def test_multiple_connections(self):
        body = b"""inputs
{
0 \tnode_a 0 1
1 \tnode_b 1 1
}
end"""
        conns = _parse_inputs(body)
        assert len(conns) == 2
        assert conns[0]["src_name"] == "node_a"
        assert conns[1]["src_name"] == "node_b"
        assert conns[1]["src_output"] == 1

    def test_empty_inputs(self):
        body = b"""inputs
{
}
end"""
        conns = _parse_inputs(body)
        assert conns == []

    def test_disconnected_input_skipped(self):
        body = b"""inputs
{
0 \t"" 0 1
}
end"""
        conns = _parse_inputs(body)
        assert conns == []

    def test_no_inputs_block(self):
        body = b"""comment ""
position 0 0
end"""
        conns = _parse_inputs(body)
        assert conns == []


# ---------------------------------------------------------------------------
# _parse_parms
# ---------------------------------------------------------------------------
class TestParseParms:
    def test_basic_params(self):
        body = b"""{
version 0.8
name\t( "width" )
value\t( 0.5 )
}"""
        params = _parse_parms(body)
        assert params["name"] == "width"
        assert params["value"] == "0.5"

    def test_vector_param(self):
        body = b"""{
version 0.8
t\t[ 0\tlocks=0 ]\t( 1.0\t2.0\t3.0 )
}"""
        params = _parse_parms(body)
        assert params["t"] == ["1.0", "2.0", "3.0"]

    def test_skips_version(self):
        body = b"""{
version 0.8
scale\t( 1 )
}"""
        params = _parse_parms(body)
        assert "version" not in params
        assert params["scale"] == "1"

    def test_empty_parms(self):
        body = b"""{
version 0.8
}"""
        params = _parse_parms(body)
        assert params == {}

    def test_with_flags_annotation(self):
        body = b"""{
version 0.8
display\t[ 0\tlocks=0 ]\t( 1 )
}"""
        params = _parse_parms(body)
        assert params["display"] == "1"


# ---------------------------------------------------------------------------
# _node_category
# ---------------------------------------------------------------------------
class TestNodeCategory:
    def test_obj_top_level(self):
        assert _node_category("obj/geo1") == "OBJ"

    def test_sop_nested(self):
        assert _node_category("obj/geo1/box1") == "SOP"

    def test_out_context(self):
        assert _node_category("out/mantra1") == "ROP"

    def test_stage_context(self):
        assert _node_category("stage/lop1") == "LOP"

    def test_unknown_context(self):
        assert _node_category("custom/node1") == "CUSTOM"


# ---------------------------------------------------------------------------
# parse_hip_bytes (integration)
# ---------------------------------------------------------------------------
class TestParseHipBytes:
    def test_minimal_scene(self):
        """Parse a minimal scene with one geo node containing a box."""
        data = _make_hip(
            (".start", "fps 24"),
            ("obj/geo1.init", "type = geo\nmatchesdef = 0"),
            ("obj/geo1.def", "comment \"\"\nposition 0 0\ninputs\n{\n}\nend"),
            ("obj/geo1.parm", "{\nversion 0.8\ndisplay\t( 1 )\n}"),
            ("obj/geo1/box1.init", "type = box\nmatchesdef = 0"),
            ("obj/geo1/box1.def", "comment \"\"\nposition 0 0\ninputs\n{\n}\nend"),
            ("obj/geo1/box1.parm", "{\nversion 0.8\nsize\t( 2.0\t2.0\t2.0 )\n}"),
        )
        result = parse_hip_bytes(data)

        assert len(result["nodes"]) == 2
        paths = {n["path"] for n in result["nodes"]}
        assert "/obj/geo1" in paths
        assert "/obj/geo1/box1" in paths

        geo = next(n for n in result["nodes"] if n["path"] == "/obj/geo1")
        assert geo["type"] == "geo"
        assert geo["category"] == "OBJ"
        assert geo["parameters"]["display"] == "1"
        assert "/obj/geo1/box1" in geo["children"]

        box = next(n for n in result["nodes"] if n["path"] == "/obj/geo1/box1")
        assert box["type"] == "box"
        assert box["category"] == "SOP"
        assert box["parameters"]["size"] == ["2.0", "2.0", "2.0"]
        assert box["children"] == []

    def test_connections(self):
        """Parse a scene with SOP connections: box → transform."""
        data = _make_hip(
            ("obj/geo1.init", "type = geo"),
            ("obj/geo1.def", "inputs\n{\n}\nend"),
            ("obj/geo1/box1.init", "type = box"),
            ("obj/geo1/box1.def", "inputs\n{\n}\nend"),
            ("obj/geo1/xform1.init", "type = xform"),
            ("obj/geo1/xform1.def", "inputs\n{\n0 \tbox1 0 1\n}\nend"),
        )
        result = parse_hip_bytes(data)

        assert len(result["connections"]) == 1
        conn = result["connections"][0]
        assert conn["src_path"] == "/obj/geo1/box1"
        assert conn["src_output"] == 0
        assert conn["dst_path"] == "/obj/geo1/xform1"
        assert conn["dst_input"] == 0

    def test_chain_connections(self):
        """Parse a 3-node chain: grid → edit → attribcreate."""
        data = _make_hip(
            ("obj/geo1.init", "type = geo"),
            ("obj/geo1.def", "inputs\n{\n}\nend"),
            ("obj/geo1/grid1.init", "type = grid"),
            ("obj/geo1/grid1.def", "inputs\n{\n}\nend"),
            ("obj/geo1/edit1.init", "type = edit"),
            ("obj/geo1/edit1.def", "inputs\n{\n0 \tgrid1 0 1\n}\nend"),
            ("obj/geo1/attrib1.init", "type = attribcreate"),
            ("obj/geo1/attrib1.def", "inputs\n{\n0 \tedit1 0 1\n}\nend"),
        )
        result = parse_hip_bytes(data)

        assert len(result["connections"]) == 2
        src_paths = {c["src_path"] for c in result["connections"]}
        dst_paths = {c["dst_path"] for c in result["connections"]}
        assert "/obj/geo1/grid1" in src_paths
        assert "/obj/geo1/edit1" in src_paths
        assert "/obj/geo1/edit1" in dst_paths
        assert "/obj/geo1/attrib1" in dst_paths

    def test_multiple_contexts(self):
        """Nodes in different contexts get correct categories."""
        data = _make_hip(
            ("obj/cam1.init", "type = cam"),
            ("obj/cam1.def", "inputs\n{\n}\nend"),
            ("out/mantra1.init", "type = ifd"),
            ("out/mantra1.def", "inputs\n{\n}\nend"),
            ("stage/lop1.init", "type = sublayer"),
            ("stage/lop1.def", "inputs\n{\n}\nend"),
        )
        result = parse_hip_bytes(data)

        cats = {n["path"]: n["category"] for n in result["nodes"]}
        assert cats["/obj/cam1"] == "OBJ"
        assert cats["/out/mantra1"] == "ROP"
        assert cats["/stage/lop1"] == "LOP"

    def test_empty_scene(self):
        """A scene with no nodes returns empty lists."""
        data = _make_hip((".start", "fps 24"))
        result = parse_hip_bytes(data)
        assert result["nodes"] == []
        assert result["connections"] == []

    def test_source_field(self):
        data = _make_hip((".start", "fps 24"))
        result = parse_hip_bytes(data, source="test.hip")
        assert result["source"] == "test.hip"

    def test_empty_scene_has_sticky_notes_and_netboxes(self):
        data = _make_hip((".start", "fps 24"))
        result = parse_hip_bytes(data)
        assert result["sticky_notes"] == []
        assert result["netboxes"] == []

    def test_node_comment_extracted(self):
        """Node comment from .def is included on the node dict."""
        data = _make_hip(
            ("obj/geo1/box1.init", "type = box"),
            ("obj/geo1/box1.def",
             'comment "Creates a width attribute"\nposition 0 0\ninputs\n{\n}\nend'),
        )
        result = parse_hip_bytes(data)
        box = result["nodes"][0]
        assert box["comment"] == "Creates a width attribute"

    def test_node_without_comment_has_no_key(self):
        """Nodes with empty comments should not have a 'comment' key."""
        data = _make_hip(
            ("obj/geo1/box1.init", "type = box"),
            ("obj/geo1/box1.def", 'comment ""\nposition 0 0\ninputs\n{\n}\nend'),
        )
        result = parse_hip_bytes(data)
        assert "comment" not in result["nodes"][0]

    def test_sticky_note_extracted(self):
        """Sticky notes from .postitdef sections are collected."""
        data = _make_hip(
            ("obj/geo1.init", "type = geo"),
            ("obj/geo1.def", "inputs\n{\n}\nend"),
            ("obj/__stickynote1.postitinit", "type = postitnote\nmatchesdef = 0"),
            ("obj/__stickynote1.postitdef",
             'text "Dive into the geo node"\nposition 0 0\nend'),
        )
        result = parse_hip_bytes(data)
        assert len(result["sticky_notes"]) == 1
        sn = result["sticky_notes"][0]
        assert sn["text"] == "Dive into the geo node"
        assert sn["context"] == "/obj"
        assert sn["name"] == "__stickynote1"

    def test_sticky_note_not_in_nodes(self):
        """Postit nodes should not appear in the nodes list."""
        data = _make_hip(
            ("obj/__stickynote1.postitinit", "type = postitnote\nmatchesdef = 0"),
            ("obj/__stickynote1.postitdef",
             'text "Some note"\nposition 0 0\nend'),
        )
        result = parse_hip_bytes(data)
        assert result["nodes"] == []
        assert len(result["sticky_notes"]) == 1

    def test_netbox_extracted(self):
        """Network box labels from .netboxinit are collected."""
        netbox_body = '2\n2\n{\n\tcomment := "Merge Attributes";\n\theight := 10;\n}\n{\n}'
        data = _make_hip(
            ("obj/topnet1/__netbox1.netboxinit", netbox_body),
        )
        result = parse_hip_bytes(data)
        assert len(result["netboxes"]) == 1
        nb = result["netboxes"][0]
        assert nb["label"] == "Merge Attributes"
        assert nb["context"] == "/obj/topnet1"
        assert nb["name"] == "__netbox1"

    def test_netbox_empty_comment_skipped(self):
        netbox_body = '2\n2\n{\n\tcomment := "";\n\theight := 10;\n}\n{\n}'
        data = _make_hip(
            ("obj/topnet1/__netbox1.netboxinit", netbox_body),
        )
        result = parse_hip_bytes(data)
        assert result["netboxes"] == []


# ---------------------------------------------------------------------------
# New parsers (unit tests)
# ---------------------------------------------------------------------------

class TestParseComment:
    def test_quoted_comment(self):
        body = b'comment "Creates a width attribute"\nposition 0 0\nend'
        assert _parse_comment(body) == "Creates a width attribute"

    def test_empty_comment(self):
        body = b'comment ""\nposition 0 0\nend'
        assert _parse_comment(body) == ""

    def test_no_comment_line(self):
        body = b"position 0 0\nend"
        assert _parse_comment(body) == ""


class TestParsePostitText:
    def test_quoted_text(self):
        body = b'text "Dive into the AutoDopNetwork."\nposition 0 0\nend'
        assert _parse_postit_text(body) == "Dive into the AutoDopNetwork."

    def test_unquoted_text(self):
        body = b"text Chapters/Sections\nposition 0 0\nend"
        assert _parse_postit_text(body) == "Chapters/Sections"

    def test_empty_text(self):
        body = b"position 0 0\nend"
        assert _parse_postit_text(body) == ""


class TestParseNetboxComment:
    def test_labeled_netbox(self):
        body = b'2\n2\n{\n\tcomment := "Split by Attribute";\n\theight := 10;\n}\n{\n}'
        assert _parse_netbox_comment(body) == "Split by Attribute"

    def test_empty_comment(self):
        body = b'2\n2\n{\n\tcomment := "";\n\theight := 10;\n}\n{\n}'
        assert _parse_netbox_comment(body) == ""

    def test_no_comment_field(self):
        body = b"2\n2\n{\n\theight := 10;\n}\n{\n}"
        assert _parse_netbox_comment(body) == ""
