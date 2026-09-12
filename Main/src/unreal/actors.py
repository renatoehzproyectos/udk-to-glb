"""
actors.py

Extracción mínima de StaticMeshActor / transforms desde exports UE3.

Objetivo de esta capa:
  - Localizar exports de clase StaticMeshActor (y similares)
  - Leer tagged properties: Location, Rotation, DrawScale3D / Scale3D,
    StaticMesh (ObjectProperty)
  - Devolver lista de ActorPlacement listos para montar la escena GLB

No carga meshes todavía; solo transforms + nombre del mesh referenciado.
"""

from __future__ import annotations
import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple, Any

from .properties import read_fname


@dataclass
class ActorPlacement:
    name: str
    mesh_name: str
    location: Tuple[float, float, float]
    rotation: Tuple[float, float, float]  # pitch, yaw, roll (grados Unreal) o euler
    scale: Tuple[float, float, float]
    export_index: int = -1
    notes: str = ""


def _read_vector(data: bytes, off: int) -> Tuple[Tuple[float, float, float], int]:
    if off + 12 > len(data):
        raise ValueError(f"EOF Vector @{off}")
    x, y, z = struct.unpack_from("<fff", data, off)
    return (x, y, z), off + 12


def _read_rotator(data: bytes, off: int) -> Tuple[Tuple[float, float, float], int]:
    """FRotator: Pitch, Yaw, Roll as float (UE3 often stores as float degrees*...)."""
    if off + 12 > len(data):
        raise ValueError(f"EOF Rotator @{off}")
    p, y, r = struct.unpack_from("<fff", data, off)
    return (p, y, r), off + 12


def _read_object_index(data: bytes, off: int) -> Tuple[int, int]:
    """ObjectProperty value: int32 package index (negative=import, positive=export)."""
    if off + 4 > len(data):
        raise ValueError(f"EOF ObjectIndex @{off}")
    idx, = struct.unpack_from("<i", data, off)
    return idx, off + 4


def parse_actor_properties(
    data: bytes,
    names: List[str],
    imports: list,
    exports: list,
    actor_name: str = "Actor",
    export_index: int = -1,
) -> ActorPlacement:
    """
    Parsea tagged properties de un Actor y extrae Location/Rotation/Scale/StaticMesh.
    """
    location = (0.0, 0.0, 0.0)
    rotation = (0.0, 0.0, 0.0)
    scale = (1.0, 1.0, 1.0)
    mesh_name = ""
    notes = []

    off = 0
    max_props = 256
    for _ in range(max_props):
        if off + 8 > len(data):
            break
        name, off2 = read_fname(data, off, names)
        if name == "None":
            off = off2
            break

        type_name, off2 = read_fname(data, off2, names)
        if off2 + 8 > len(data):
            break
        size, array_index = struct.unpack_from("<ii", data, off2)
        off2 += 8

        if size < 0 or off2 + size > len(data) + 64:
            # corrupt; abort gracefully
            notes.append(f"bad_size:{name}")
            break

        # StructProperty extra: StructName
        struct_name = ""
        if type_name == "StructProperty":
            struct_name, off2 = read_fname(data, off2, names)

        value_off = off2

        try:
            if name in ("Location", "RelativeLocation") and type_name == "StructProperty":
                if size >= 12:
                    location, _ = _read_vector(data, value_off)
            elif name in ("Rotation", "RelativeRotation") and type_name == "StructProperty":
                if size >= 12:
                    rotation, _ = _read_rotator(data, value_off)
            elif name in ("DrawScale3D", "Scale3D", "RelativeScale3D") and type_name == "StructProperty":
                if size >= 12:
                    scale, _ = _read_vector(data, value_off)
            elif name == "DrawScale" and type_name == "FloatProperty" and size >= 4:
                s, = struct.unpack_from("<f", data, value_off)
                scale = (s, s, s)
            elif name == "StaticMesh" and type_name == "ObjectProperty" and size >= 4:
                obj_idx, _ = _read_object_index(data, value_off)
                mesh_name = _resolve_object_name(obj_idx, imports, exports)
            elif name in ("StaticMeshComponent",) and type_name == "ObjectProperty":
                # reference to component; mesh often on the component itself
                notes.append("has_SMC")
        except ValueError as e:
            notes.append(str(e))

        # advance past value
        if type_name == "BoolProperty" and size == 0:
            off = value_off + 1
        else:
            off = value_off + max(size, 0)

    return ActorPlacement(
        name=actor_name,
        mesh_name=mesh_name or "",
        location=location,
        rotation=rotation,
        scale=scale,
        export_index=export_index,
        notes=";".join(notes),
    )


def _resolve_object_name(index: int, imports: list, exports: list) -> str:
    if index == 0:
        return ""
    if index < 0:
        # import: -index - 1
        i = -index - 1
        if 0 <= i < len(imports):
            return imports[i].object_name
        return f"Import[{index}]"
    # export: index - 1
    i = index - 1
    if 0 <= i < len(exports):
        return exports[i].object_name
    return f"Export[{index}]"


def find_static_mesh_actors(pkg) -> List[ActorPlacement]:
    """
    Recorre exports buscando StaticMeshActor (y subclases por nombre)
    y parsea sus propiedades.
    """
    results = []
    for e in pkg.exports:
        cname = e.class_name(pkg.imports, pkg.exports)
        # RL/UE3: StaticMeshActor, StaticMeshActor_TA, InterpActor, etc.
        if "StaticMeshActor" not in cname and cname not in ("Actor", "InterpActor", "Mover"):
            if "Actor" not in cname:
                continue
        if e.serial_size <= 0:
            continue
        raw = pkg.raw_object_data(e)
        try:
            place = parse_actor_properties(
                raw, pkg.names, pkg.imports, pkg.exports,
                actor_name=e.object_name, export_index=e.index,
            )
            results.append(place)
        except Exception as ex:
            results.append(ActorPlacement(
                name=e.object_name,
                mesh_name="",
                location=(0, 0, 0),
                rotation=(0, 0, 0),
                scale=(1, 1, 1),
                export_index=e.index,
                notes=f"parse_fail:{ex}",
            ))
    return results


def find_mesh_components(pkg) -> List[ActorPlacement]:
    """
    StaticMeshComponent often holds the actual StaticMesh reference.
    Outer points to the owning Actor. We recover:
      component → StaticMesh name
      component → Outer actor name
      actor → Location/Rotation/Scale
    """
    # map export index → placement from actors
    actors_by_idx = {}
    for e in pkg.exports:
        cname = e.class_name(pkg.imports, pkg.exports)
        if "StaticMeshActor" in cname or cname == "Actor":
            raw = pkg.raw_object_data(e)
            try:
                place = parse_actor_properties(
                    raw, pkg.names, pkg.imports, pkg.exports,
                    actor_name=e.object_name, export_index=e.index,
                )
                actors_by_idx[e.index] = place
            except Exception:
                pass

    results = []
    for e in pkg.exports:
        cname = e.class_name(pkg.imports, pkg.exports)
        if "StaticMeshComponent" not in cname:
            continue
        raw = pkg.raw_object_data(e)
        try:
            place = parse_actor_properties(
                raw, pkg.names, pkg.imports, pkg.exports,
                actor_name=e.object_name, export_index=e.index,
            )
        except Exception:
            continue

        # OuterIndex of component → parent actor
        outer = e.outer_index
        parent_name = e.object_name
        parent_loc = place.location
        parent_rot = place.rotation
        parent_scale = place.scale
        if outer > 0:
            oi = outer - 1
            if oi in actors_by_idx:
                parent = actors_by_idx[oi]
                parent_name = parent.name
                # prefer actor transform if non-zero
                if parent.location != (0.0, 0.0, 0.0):
                    parent_loc = parent.location
                if parent.rotation != (0.0, 0.0, 0.0):
                    parent_rot = parent.rotation
                if parent.scale != (1.0, 1.0, 1.0):
                    parent_scale = parent.scale
            elif 0 <= oi < len(pkg.exports):
                parent_name = pkg.exports[oi].object_name

        if not place.mesh_name:
            continue

        results.append(ActorPlacement(
            name=parent_name,
            mesh_name=place.mesh_name,
            location=parent_loc,
            rotation=parent_rot,
            scale=parent_scale,
            export_index=e.index,
            notes=f"from_component:{e.object_name}",
        ))
    return results


def collect_placements(pkg) -> List[ActorPlacement]:
    """Combina actores directos + componentes; prefiere los que tienen mesh_name."""
    direct = find_static_mesh_actors(pkg)
    from_comp = find_mesh_components(pkg)
    by_name = {}
    for p in direct + from_comp:
        key = (p.name, p.mesh_name)
        if p.mesh_name:
            by_name[key] = p
        elif key not in by_name:
            by_name[key] = p
    return list(by_name.values())
