"""Material management handlers."""
import hou


def list_materials(mat_path="/mat"):
    """List all materials in a material network."""
    mat_node = hou.node(mat_path)
    if not mat_node:
        raise ValueError(f"Material network not found: {mat_path}")
    materials = []
    for child in mat_node.children():
        materials.append({
            "name": child.name(),
            "path": child.path(),
            "type": child.type().name(),
        })
    return {"path": mat_path, "count": len(materials), "materials": materials}


def get_material_info(path):
    """Get detailed info about a material node."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Material not found: {path}")
    parms = {}
    for parm in node.parms():
        if not parm.isAtDefault():
            parms[parm.name()] = str(parm.eval())
    return {
        "path": node.path(),
        "type": node.type().name(),
        "label": node.type().description(),
        "non_default_parms": parms,
    }


def create_material_network(parent_path="/obj", name="matnet"):
    """Create a material network (matnet) node."""
    parent = hou.node(parent_path)
    if not parent:
        raise ValueError(f"Parent not found: {parent_path}")
    node = parent.createNode("matnet", node_name=name)
    return {"path": node.path(), "name": node.name()}


def assign_material(node_path, material_path):
    """Assign a material to a node by setting shop_materialpath."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    mat = hou.node(material_path)
    if not mat:
        raise ValueError(f"Material not found: {material_path}")
    parm = node.parm("shop_materialpath")
    if parm:
        parm.set(material_path)
        return {"path": node_path, "material": material_path, "assigned": True}
    # Try to find material parm in SOP context
    geo_node = node.node("material1")
    if geo_node:
        mp = geo_node.parm("shop_materialpath1")
        if mp:
            mp.set(material_path)
            return {"path": node_path, "material": material_path, "assigned": True}
    raise ValueError(f"No material parameter found on {node_path}")


def list_material_types():
    """List available material/shader node types."""
    result = []
    for cat_name, cat in hou.nodeTypeCategories().items():
        if cat_name not in ("Shop", "Vop"):
            continue
        for name, nt in cat.nodeTypes().items():
            if "shader" in name.lower() or "material" in name.lower():
                result.append({
                    "name": name,
                    "category": cat_name,
                    "label": nt.description(),
                })
    return {"count": len(result), "types": result}
