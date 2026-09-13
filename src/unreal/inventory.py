"""
inventory.py

Everything in a .udk/.upk that this tool otherwise ignores: a full manifest
of every object the package defines (class, name, size), plus targeted
extraction of a handful of gameplay-relevant actor classes — lights, spawn
points, goals, boost pads — and basic material info. StaticMesh geometry
itself is handled by static_mesh.py; this module is the "everything else"
layer, informational for classes we don't turn into 3D data (materials,
Kismet, physics) and structural (transform + params) for the ones we do
(lights, marker actors).

None of this is required for a mesh to extract correctly — it's purely
additive context about what else lives in the file.
"""

from __future__ import annotations
import struct
from typing import List, Dict, Any, Optional

from .properties import read_fname
from .actors import parse_actor_properties, _resolve_object_name


def build_class_inventory(pkg) -> Dict[str, int]:
    """Every export class in the package and how many of each — the
    fastest way to see what's actually inside beyond StaticMesh."""
    counts: Dict[str, int] = {}
    for e in pkg.exports:
        cname = e.class_name(pkg.imports, pkg.exports)
        counts[cname] = counts.get(cname, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def build_export_list(pkg) -> List[Dict[str, Any]]:
    """Every export: class, name, outer (parent, for nesting), serialized
    size. This is the raw material for anything not otherwise handled —
    Kismet sequences, physics assets, particle systems, whatever the map
    happens to contain."""
    out = []
    for e in pkg.exports:
        out.append({
            "index": e.index,
            "class": e.class_name(pkg.imports, pkg.exports),
            "name": e.object_name,
            "outer": e.outer_index,
            "size": e.serial_size,
        })
    return out


def build_import_list(pkg) -> List[Dict[str, Any]]:
    """External references — objects this package uses but doesn't define
    itself (e.g. a shared texture or material living in Engine.upk)."""
    out = []
    for i, imp in enumerate(pkg.imports):
        out.append({
            "index": -(i + 1),
            "class": imp.class_name,
            "name": imp.object_name,
            "package": imp.class_package,
        })
    return out


def read_simple_properties(data: bytes, names: List[str], max_props: int = 512) -> Dict[str, Any]:
    """Generic tagged-property walker: returns every property this package
    format can trivially represent (numbers, bools, names, vectors, colors)
    as a plain dict, skipping (but still advancing past) anything more
    complex (nested structs/arrays we don't have a specific reader for).
    This is what powers light color/brightness and material parameters —
    the same walking logic actors.py uses for Location/Rotation/Scale,
    generalized to grab everything recognizable instead of a fixed set."""
    out: Dict[str, Any] = {}
    off = 0
    for _ in range(max_props):
        if off + 8 > len(data):
            break
        try:
            name, off2 = read_fname(data, off, names)
        except ValueError:
            break
        if name == "None":
            break
        try:
            type_name, off2 = read_fname(data, off2, names)
        except ValueError:
            break
        if off2 + 8 > len(data):
            break
        size, array_index = struct.unpack_from("<ii", data, off2)
        off2 += 8
        if size < 0 or off2 + size > len(data) + 64:
            break

        struct_name = ""
        if type_name == "StructProperty":
            try:
                struct_name, off2 = read_fname(data, off2, names)
            except ValueError:
                break

        value_off = off2
        try:
            if type_name == "FloatProperty" and size >= 4:
                out[name] = struct.unpack_from("<f", data, value_off)[0]
            elif type_name == "IntProperty" and size >= 4:
                out[name] = struct.unpack_from("<i", data, value_off)[0]
            elif type_name == "BoolProperty":
                out[name] = bool(data[value_off]) if size in (0, 1) and value_off < len(data) else None
            elif type_name == "ByteProperty" and size >= 1:
                out[name] = data[value_off]
            elif type_name == "NameProperty":
                nval, _ = read_fname(data, value_off, names)
                out[name] = nval
            elif type_name == "StructProperty" and struct_name in ("Vector", "Rotator") and size >= 12:
                out[name] = struct.unpack_from("<fff", data, value_off)
            elif type_name == "StructProperty" and struct_name == "Color" and size >= 4:
                b, g, r, a = struct.unpack_from("<BBBB", data, value_off)
                out[name] = {"r": r, "g": g, "b": b, "a": a}
            elif type_name == "StructProperty" and struct_name == "LinearColor" and size >= 16:
                out[name] = struct.unpack_from("<ffff", data, value_off)
            elif type_name == "ObjectProperty" and size >= 4:
                out[f"{name}_ref"] = struct.unpack_from("<i", data, value_off)[0]
        except (struct.error, IndexError):
            pass

        if type_name == "BoolProperty" and size == 0:
            off = value_off + 1
        else:
            off = value_off + max(size, 0)
    return out


_LIGHT_CLASSES = ("DirectionalLight", "PointLight", "SpotLight")
_LIGHT_GLTF_TYPE = {"DirectionalLight": "directional", "PointLight": "point", "SpotLight": "spot"}


def extract_lights(pkg) -> List[Dict[str, Any]]:
    """Light actors (position/rotation from the actor, color/intensity from
    its *LightComponent child, which is a separate export whose Outer points
    back at this actor — same parent/child pattern StaticMeshActor uses for
    its StaticMeshComponent)."""
    lights = []
    actor_by_idx = {}
    for e in pkg.exports:
        cname = e.class_name(pkg.imports, pkg.exports)
        if any(cname.startswith(lc) and "Component" not in cname for lc in _LIGHT_CLASSES):
            raw = pkg.raw_object_data(e)
            try:
                place = parse_actor_properties(raw, pkg.names, pkg.imports, pkg.exports,
                                                actor_name=e.object_name, export_index=e.index)
                actor_by_idx[e.index] = (e, place)
            except Exception:
                continue

    for e in pkg.exports:
        cname = e.class_name(pkg.imports, pkg.exports)
        if "LightComponent" not in cname:
            continue
        outer = e.outer_index
        if outer <= 0:
            continue
        oi = outer - 1
        if oi not in actor_by_idx:
            continue
        actor_e, place = actor_by_idx[oi]
        actor_cname = actor_e.class_name(pkg.imports, pkg.exports)
        light_type = next((_LIGHT_GLTF_TYPE[lc] for lc in _LIGHT_CLASSES if actor_cname.startswith(lc)), "point")

        raw = pkg.raw_object_data(e)
        props = read_simple_properties(raw, pkg.names)
        color = props.get("LightColor", {"r": 255, "g": 255, "b": 255})
        brightness = props.get("Brightness", 1.0)
        radius = props.get("Radius", None)

        lights.append({
            "name": actor_e.object_name,
            "type": light_type,
            "location": place.location,
            "rotation": place.rotation,
            "color": (color["r"] / 255.0, color["g"] / 255.0, color["b"] / 255.0) if isinstance(color, dict) else (1.0, 1.0, 1.0),
            "intensity": brightness,
            "radius": radius,
        })
    return lights


# class-name substrings -> a short category label, for grouping in the manifest
_GAMEPLAY_CLASSES = {
    "PlayerStart_TA": "spawn_point",
    "Goal_TA": "goal",
    "GoalVolume_TA": "goal_volume",
    "GoalCrossbarVolume_TA": "goal_crossbar",
    "VehiclePickup_Boost_TA": "boost_pad",
    "CameraActor": "camera",
}


def extract_gameplay_actors(pkg) -> Dict[str, List[Dict[str, Any]]]:
    """Non-mesh gameplay actors with a transform worth knowing about: spawn
    points, goal volumes, boost pad placements, cameras. Grouped by category
    so the manifest reads as "here's every boost pad" rather than a flat
    list the caller has to filter themselves."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for e in pkg.exports:
        cname = e.class_name(pkg.imports, pkg.exports)
        category = _GAMEPLAY_CLASSES.get(cname)
        if category is None:
            continue
        raw = pkg.raw_object_data(e)
        try:
            place = parse_actor_properties(raw, pkg.names, pkg.imports, pkg.exports,
                                            actor_name=e.object_name, export_index=e.index)
        except Exception:
            continue
        out.setdefault(category, []).append({
            "name": e.object_name,
            "location": place.location,
            "rotation": place.rotation,
        })
    return out


def extract_materials(pkg) -> List[Dict[str, Any]]:
    """Material / MaterialInstanceConstant exports: name, parent material
    (if it's a Material Instance), and any simple scalar/vector parameters
    found in its properties. Base textures for these usually live in other
    packages entirely (imports only, no pixel data in this file) — this is
    naming/parameter info, not renderable textures."""
    out = []
    for e in pkg.exports:
        cname = e.class_name(pkg.imports, pkg.exports)
        if cname not in ("Material", "MaterialInstanceConstant"):
            continue
        raw = pkg.raw_object_data(e)
        props = read_simple_properties(raw, pkg.names)
        parent_ref = props.pop("Parent_ref", None)
        entry = {
            "name": e.object_name,
            "class": cname,
            "parent": _resolve_object_name(parent_ref, pkg.imports, pkg.exports) if parent_ref else None,
            "params": {k: v for k, v in props.items() if not k.endswith("_ref")},
        }
        out.append(entry)
    return out


def build_manifest(pkg) -> Dict[str, Any]:
    """Everything this tool doesn't turn into mesh geometry, in one
    JSON-serializable dict: full class inventory + export/import tables,
    plus structured extraction of lights, gameplay actors, and materials."""
    return {
        "class_counts": build_class_inventory(pkg),
        "exports": build_export_list(pkg),
        "imports": build_import_list(pkg),
        "lights": extract_lights(pkg),
        "gameplay_actors": extract_gameplay_actors(pkg),
        "materials": extract_materials(pkg),
    }
