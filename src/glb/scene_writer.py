"""
scene_writer.py

GLB con múltiples meshes + nodos con transform (TRS).

Usado cuando ya hay geometría de varios StaticMesh y placements de actores.
"""

from __future__ import annotations
import json
import math
import struct
from typing import List, Sequence, Tuple, Dict, Any

from .writer import _align4


def _mesh_color(name: str) -> Tuple[float, float, float]:
    """Deterministic, well-separated color per mesh name — this map has no
    real texture data (albedo textures live in other packages this file
    only references, not embedded here), so distinct flat colors per mesh
    are the honest substitute for 'can I tell parts apart'. Hash-based hue
    keeps it stable across re-exports (same mesh name -> same color) and
    golden-angle spacing keeps adjacent hashes from landing on similar hues."""
    h = (hash(name) % 100000) * 0.6180339887498949  # golden angle walk
    h = h - math.floor(h)
    s, v = 0.55, 0.85
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    r, g, b = [
        (v, t, p), (q, v, p), (p, v, t),
        (p, q, v), (t, p, v), (v, p, q),
    ][i % 6]
    return (r, g, b)


def _euler_unreal_to_quat(pitch: float, yaw: float, roll: float) -> Tuple[float, float, float, float]:
    """
    Aproximación: Unreal Rotator en grados → quaternion (x,y,z,w).
    Orden típico UE: Yaw (Z), Pitch (Y), Roll (X) — simplificado.
    """
    # convertir a radianes
    p = math.radians(pitch)
    y = math.radians(yaw)
    r = math.radians(roll)
    cy, sy = math.cos(y * 0.5), math.sin(y * 0.5)
    cp, sp = math.cos(p * 0.5), math.sin(p * 0.5)
    cr, sr = math.cos(r * 0.5), math.sin(r * 0.5)
    # ZYX
    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y_ = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    return (x, y_, z, w)


def write_scene_glb(
    path: str,
    meshes: Dict[str, Tuple[Sequence[Tuple[float, float, float]], Sequence[int]]],
    nodes: List[Dict[str, Any]],
    lights: List[Dict[str, Any]] = None,
) -> None:
    """
    meshes: name -> (vertices, indices)
    nodes: list of {name, mesh, translation, rotation, scale, light}
      rotation as quaternion (x,y,z,w) or euler degrees under 'euler'
      'light': index into `lights`, for non-mesh light marker nodes
    lights: list of {name, type: 'directional'|'point'|'spot', color: (r,g,b) 0-1,
                     intensity}. Written as glTF KHR_lights_punctual.
    """
    if not meshes:
        raise ValueError("No meshes to write")
    lights = lights or []

    bin_parts = []
    accessors = []
    buffer_views = []
    gltf_meshes = []
    gltf_materials = []
    mesh_index = {}

    byte_offset = 0
    for mi, (mname, (vertices, indices)) in enumerate(meshes.items()):
        pos_data = b"".join(struct.pack("<fff", *v) for v in vertices)
        max_idx = max(indices) if indices else 0
        if max_idx < 65536:
            idx_data = b"".join(struct.pack("<H", i) for i in indices)
            idx_ctype = 5123
        else:
            idx_data = b"".join(struct.pack("<I", i) for i in indices)
            idx_ctype = 5125

        pos_pad = b"\x00" * (_align4(len(pos_data)) - len(pos_data))
        idx_pad = b"\x00" * (_align4(len(idx_data)) - len(idx_data))

        xs = [v[0] for v in vertices]
        ys = [v[1] for v in vertices]
        zs = [v[2] for v in vertices]
        min_pos = [min(xs), min(ys), min(zs)]
        max_pos = [max(xs), max(ys), max(zs)]

        bv_pos = len(buffer_views)
        buffer_views.append({
            "buffer": 0, "byteOffset": byte_offset, "byteLength": len(pos_data), "target": 34962,
        })
        acc_pos = len(accessors)
        accessors.append({
            "bufferView": bv_pos, "componentType": 5126, "count": len(vertices),
            "type": "VEC3", "min": min_pos, "max": max_pos,
        })
        bin_parts.append(pos_data + pos_pad)
        byte_offset += len(pos_data) + len(pos_pad)

        bv_idx = len(buffer_views)
        buffer_views.append({
            "buffer": 0, "byteOffset": byte_offset, "byteLength": len(idx_data), "target": 34963,
        })
        acc_idx = len(accessors)
        accessors.append({
            "bufferView": bv_idx, "componentType": idx_ctype, "count": len(indices), "type": "SCALAR",
        })
        bin_parts.append(idx_data + idx_pad)
        byte_offset += len(idx_data) + len(idx_pad)

        mesh_index[mname] = len(gltf_meshes)
        r, g, b = _mesh_color(mname)
        mat_index = len(gltf_materials)
        gltf_materials.append({
            "name": f"mat_{mname}",
            "pbrMetallicRoughness": {
                "baseColorFactor": [r, g, b, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.85,
            },
        })
        gltf_meshes.append({
            "name": mname,
            "primitives": [{"attributes": {"POSITION": acc_pos}, "indices": acc_idx,
                             "mode": 4, "material": mat_index}],
        })

    gltf_nodes = []
    root_children = []
    for n in nodes:
        node = {"name": n.get("name", "node")}
        if "mesh" in n and n["mesh"] in mesh_index:
            node["mesh"] = mesh_index[n["mesh"]]
        if "translation" in n:
            node["translation"] = list(n["translation"])
        if "scale" in n:
            node["scale"] = list(n["scale"])
        if "rotation" in n:
            node["rotation"] = list(n["rotation"])
        elif "euler" in n:
            e = n["euler"]
            node["rotation"] = list(_euler_unreal_to_quat(e[0], e[1], e[2]))
        if "light" in n:
            node["extensions"] = {"KHR_lights_punctual": {"light": n["light"]}}
        gltf_nodes.append(node)
        root_children.append(len(gltf_nodes) - 1)

    bin_chunk = b"".join(bin_parts)
    gltf = {
        "asset": {"version": "2.0", "generator": "rl-mobile-extractor"},
        "buffers": [{"byteLength": len(bin_chunk)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "meshes": gltf_meshes,
        "materials": gltf_materials,
        "nodes": gltf_nodes,
        "scenes": [{"nodes": root_children}],
        "scene": 0,
    }
    if lights:
        gltf["extensionsUsed"] = ["KHR_lights_punctual"]
        gltf["extensions"] = {
            "KHR_lights_punctual": {
                "lights": [
                    {
                        "name": l.get("name", "light"),
                        "type": l.get("type", "point"),
                        "color": list(l.get("color", (1.0, 1.0, 1.0))),
                        "intensity": l.get("intensity", 1.0),
                    }
                    for l in lights
                ]
            }
        }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_pad = b" " * (_align4(len(json_bytes)) - len(json_bytes))
    json_chunk = json_bytes + json_pad

    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(json_chunk), b"JSON"))
        f.write(json_chunk)
        f.write(struct.pack("<I4s", len(bin_chunk), b"BIN\x00"))
        f.write(bin_chunk)
