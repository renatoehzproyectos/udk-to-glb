"""
glb/writer.py

Escritor mínimo de glTF 2.0 binario (GLB) a partir de vértices + índices.

Solo lo necesario para el hito:
  vertices reales + indices reales → archivo .glb que abre en un visor estándar.

Sin materiales, sin normales, sin UVs todavía.
"""

from __future__ import annotations
import json
import struct
from typing import List, Tuple, Sequence


def _align4(n: int) -> int:
    return (n + 3) & ~3


def write_glb(
    path: str,
    vertices: Sequence[Tuple[float, float, float]],
    indices: Sequence[int],
    mesh_name: str = "StaticMesh",
) -> None:
    """
    Escribe un GLB 2.0 con un solo mesh / un solo primitive (TRIANGLES).
    """
    if len(vertices) < 3:
        raise ValueError("Se necesitan al menos 3 vértices")
    if len(indices) < 3 or len(indices) % 3 != 0:
        raise ValueError("Los índices deben formar triángulos (múltiplo de 3)")

    # --- buffers binarios ---
    # POSITION: float32 x,y,z
    pos_data = b"".join(struct.pack("<fff", *v) for v in vertices)
    # INDICES: preferir uint16 si cabe
    max_idx = max(indices)
    if max_idx < 65536:
        idx_fmt = "<H"
        idx_component = 5123  # UNSIGNED_SHORT
        idx_data = b"".join(struct.pack(idx_fmt, i) for i in indices)
    else:
        idx_fmt = "<I"
        idx_component = 5125  # UNSIGNED_INT
        idx_data = b"".join(struct.pack(idx_fmt, i) for i in indices)

    # padding a múltiplo de 4
    pos_pad = b"\x00" * (_align4(len(pos_data)) - len(pos_data))
    idx_pad = b"\x00" * (_align4(len(idx_data)) - len(idx_data))

    bin_chunk = pos_data + pos_pad + idx_data + idx_pad
    pos_byte_length = len(pos_data)
    idx_byte_offset = len(pos_data) + len(pos_pad)
    idx_byte_length = len(idx_data)

    # bounds
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    min_pos = [min(xs), min(ys), min(zs)]
    max_pos = [max(xs), max(ys), max(zs)]

    # --- JSON glTF ---
    gltf = {
        "asset": {"version": "2.0", "generator": "rl-mobile-extractor"},
        "buffers": [{"byteLength": len(bin_chunk)}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": pos_byte_length,
                "target": 34962,  # ARRAY_BUFFER
            },
            {
                "buffer": 0,
                "byteOffset": idx_byte_offset,
                "byteLength": idx_byte_length,
                "target": 34963,  # ELEMENT_ARRAY_BUFFER
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,  # FLOAT
                "count": len(vertices),
                "type": "VEC3",
                "min": min_pos,
                "max": max_pos,
            },
            {
                "bufferView": 1,
                "componentType": idx_component,
                "count": len(indices),
                "type": "SCALAR",
            },
        ],
        "meshes": [
            {
                "name": mesh_name,
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "mode": 4,  # TRIANGLES
                    }
                ],
            }
        ],
        "nodes": [{"mesh": 0, "name": mesh_name}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }

    json_str = json.dumps(gltf, separators=(",", ":"))
    json_bytes = json_str.encode("utf-8")
    json_pad = b" " * (_align4(len(json_bytes)) - len(json_bytes))
    json_chunk = json_bytes + json_pad

    # --- GLB container ---
    # header: magic, version, length
    total_length = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    header = struct.pack("<4sII", b"glTF", 2, total_length)

    # JSON chunk
    json_chunk_header = struct.pack("<I4s", len(json_chunk), b"JSON")
    # BIN chunk
    bin_chunk_header = struct.pack("<I4s", len(bin_chunk), b"BIN\x00")

    with open(path, "wb") as f:
        f.write(header)
        f.write(json_chunk_header)
        f.write(json_chunk)
        f.write(bin_chunk_header)
        f.write(bin_chunk)
