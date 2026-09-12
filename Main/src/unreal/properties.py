"""
properties.py

Skip mínimo de propiedades tagged de UObject (UE3).

En UE3, UObject::Serialize escribe un stream de FPropertyTag hasta
encontrar el nombre "None". Cada tag tiene:

  FName Name
  FName Type
  int32 Size
  int32 ArrayIndex
  [extra según Type: StructName, EnumName, InnerType, ...]
  luego Size bytes de valor

Para StaticMesh necesitamos saltar esas propiedades y llegar a la
parte de serialización nativa (Bounds, Lods, etc.).

Este módulo solo SALTA; no interpreta valores. Suficiente para
acercar el cursor al VertexStream.
"""

from __future__ import annotations
import struct
from typing import List, Tuple, Optional


def read_fname(data: bytes, off: int, names: List[str]) -> Tuple[str, int]:
    """
    FName en paquetes UE3: int32 NameIndex + int32 Number.
    """
    if off + 8 > len(data):
        raise ValueError(f"EOF FName @{off}")
    idx, number = struct.unpack_from("<ii", data, off)
    off += 8
    if idx < 0 or idx >= len(names):
        return f"INVALID_NAME_{idx}", off
    name = names[idx]
    if number > 0:
        name = f"{name}_{number - 1}"
    return name, off


def skip_tagged_properties(data: bytes, off: int, names: List[str], max_props: int = 512) -> int:
    """
    Avanza off hasta después del terminador None de las propiedades tagged.
    Devuelve el nuevo offset.
    """
    for _ in range(max_props):
        if off + 8 > len(data):
            raise ValueError(
                f"EOF while reading property tags @{off}. "
                "Failed while skipping UObject tagged properties."
            )
        name, off2 = read_fname(data, off, names)
        if name == "None":
            return off2

        # Type
        type_name, off2 = read_fname(data, off2, names)
        if off2 + 8 > len(data):
            raise ValueError(f"EOF property size @{off2}")
        size, array_index = struct.unpack_from("<ii", data, off2)
        off2 += 8

        if size < 0 or size > len(data):
            raise ValueError(
                f"Property '{name}' type={type_name} size={size} inválido @{off}. "
                "Failed while skipping UObject tagged properties."
            )

        # Campos extra según tipo (UE3)
        # StructProperty → StructName (FName)
        # ByteProperty   → EnumName (FName)  [a veces]
        # ArrayProperty  → InnerType (FName) [variantes]
        # BoolProperty   → 1 byte value inline en algunos ver; en otros Size incluye el valor
        extra = 0
        if type_name == "StructProperty":
            _, off2 = read_fname(data, off2, names)
        elif type_name == "ByteProperty":
            # en muchas versiones UE3 hay EnumName
            if off2 + 8 <= len(data):
                # peek: si parece un name index válido, consumirlo
                peek_idx = struct.unpack_from("<i", data, off2)[0]
                if 0 <= peek_idx < len(names):
                    _, off2 = read_fname(data, off2, names)

        # BoolProperty: en UE3 a menudo el valor es 1 byte y Size=0 o Size=1
        if type_name == "BoolProperty":
            if size == 0:
                # valor bool de 1 byte justo después del tag
                off2 += 1
            else:
                off2 += size
        else:
            off2 += size

        if off2 > len(data):
            raise ValueError(
                f"Property '{name}' overruns buffer (end={off2}, len={len(data)}). "
                "Failed while skipping UObject tagged properties."
            )
        off = off2

    raise ValueError(
        f"Too many properties (>{max_props}) without None terminator. "
        "Failed while skipping UObject tagged properties."
    )


def find_after_properties(data: bytes, names: List[str]) -> int:
    """
    Intenta localizar el final de las tagged properties desde offset 0.
    Si falla, devuelve 0 (el caller puede seguir con heurística global).
    """
    try:
        return skip_tagged_properties(data, 0, names)
    except ValueError:
        return 0
