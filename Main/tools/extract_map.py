#!/usr/bin/env python3
"""Extrae todos los StaticMesh recuperables + actores → escena GLB."""
from __future__ import annotations
import argparse, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from unreal.package_reader import UnrealPackage
from unreal.static_mesh import extract_geometry
from unreal.actors import collect_placements
from glb.scene_writer import write_scene_glb

def main() -> None:
    ap = argparse.ArgumentParser(description="UDK map → scene GLB")
    ap.add_argument("udk")
    ap.add_argument("--out", default="TJBrotherAirDribble.glb")
    ap.add_argument("--max-meshes", type=int, default=0)
    ap.add_argument("--skip-actors", action="store_true")
    args = ap.parse_args()
    if not os.path.isfile(args.udk):
        print(f"ERROR: {args.udk} not found")
        print("Failed at: open package")
        sys.exit(1)
    print(f"Opening {args.udk} ...")
    try:
        pkg = UnrealPackage(args.udk)
    except Exception as e:
        print(f"ERROR: package parse failed: {e}")
        print("Failed at: package header/names/imports/exports")
        sys.exit(1)
    mesh_exports = pkg.find_exports_by_class("StaticMesh")
    print(f"StaticMesh exports: {len(mesh_exports)}")
    if not mesh_exports:
        print("ERROR: no StaticMesh in package")
        sys.exit(1)
    if args.max_meshes > 0:
        mesh_exports = sorted(mesh_exports, key=lambda e: e.serial_size)[:args.max_meshes]
    meshes = {}
    failed = []
    for e in mesh_exports:
        raw = pkg.raw_object_data(e)
        try:
            geo = extract_geometry(raw, name=e.object_name, names=pkg.names, ar_ver=pkg.summary.version,
                                  package_data=pkg.data, serial_offset=e.serial_offset)
            meshes[e.object_name] = (geo.vertices, geo.indices)
            print(f"  OK   {e.object_name}: {len(geo.vertices)} verts, {len(geo.indices)//3} tris")
        except ValueError as ex:
            failed.append((e.object_name, str(ex)))
            print(f"  FAIL {e.object_name}: {ex}")
    if not meshes:
        print("ERROR: no StaticMesh geometry extracted")
        print("Failed at: StaticMesh serialization")
        for n, err in failed[:10]:
            print(f"  {n}: {err}")
        sys.exit(1)
    nodes = []
    if not args.skip_actors:
        actors = collect_placements(pkg)
        print(f"Actor placements: {len(actors)}")
        used = set()
        for a in actors:
            if a.mesh_name and a.mesh_name in meshes:
                nodes.append({"name": a.name, "mesh": a.mesh_name,
                              "translation": a.location, "euler": a.rotation, "scale": a.scale})
                used.add(a.mesh_name)
        for mname in meshes:
            if mname not in used:
                nodes.append({"name": mname, "mesh": mname, "translation": (0, 0, 0)})
    else:
        for mname in meshes:
            nodes.append({"name": mname, "mesh": mname})
    write_scene_glb(args.out, meshes, nodes)
    print(f"GLB: {args.out} ({os.path.getsize(args.out)} bytes)")
    print(f"  meshes_ok={len(meshes)} nodes={len(nodes)} failed={len(failed)}")

if __name__ == "__main__":
    main()
