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
    # Classify meshes by bbox extent: world-space verts already correct at origin,
    # local-space need instance transforms, degenerate geometry is dropped.
    def _extent(verts):
        if not verts:
            return 0.0
        xs = [v[0] for v in verts]; ys = [v[1] for v in verts]; zs = [v[2] for v in verts]
        return max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))

    world_space = set()
    local_space = set()
    degenerate = set()
    for mname, (verts, idxs) in list(meshes.items()):
        ext = _extent(verts)
        if ext < 1e-3 or (idxs and max(idxs) == 0):
            degenerate.add(mname)
            del meshes[mname]
        elif ext > 400:
            world_space.add(mname)
        else:
            local_space.add(mname)
    print(f"Mesh classification: world={len(world_space)} local={len(local_space)} dropped_degenerate={len(degenerate)}")
    if degenerate:
        print(f"  dropped: {sorted(degenerate)}")

    nodes = []
    if not args.skip_actors:
        from unreal.actors import extract_level_position_candidates
        actors = collect_placements(pkg)
        print(f"Actor placements: {len(actors)}")
        cands = extract_level_position_candidates(pkg)
        print(f"Level position candidates: {len(cands)}")
        cand_i = 0
        used_meshes = set()
        # World-space meshes: single node at origin (vertices already in place)
        for mname in sorted(world_space):
            nodes.append({"name": mname, "mesh": mname, "translation": (0.0, 0.0, 0.0)})
            used_meshes.add(mname)
        # Local-space meshes: instance with Level candidates
        local_instances = [a for a in actors if a.mesh_name in local_space]
        if not local_instances:
            for mname in sorted(local_space):
                nodes.append({"name": mname, "mesh": mname, "translation": (0.0, 0.0, 0.0)})
        else:
            for a in local_instances:
                loc = a.location
                if loc == (0.0, 0.0, 0.0) and cand_i < len(cands):
                    loc = cands[cand_i]
                    cand_i += 1
                nodes.append({"name": f"{a.mesh_name}_{a.export_index}", "mesh": a.mesh_name,
                              "translation": loc, "euler": a.rotation, "scale": a.scale})
                used_meshes.add(a.mesh_name)
            for mname in local_space:
                if mname not in used_meshes:
                    nodes.append({"name": mname, "mesh": mname, "translation": (0.0, 0.0, 0.0)})
    else:
        for mname in meshes:
            nodes.append({"name": mname, "mesh": mname})
    write_scene_glb(args.out, meshes, nodes)
    print(f"GLB: {args.out} ({os.path.getsize(args.out)} bytes)")
    print(f"  meshes_ok={len(meshes)} nodes={len(nodes)} failed={len(failed)} world={len(world_space)} local={len(local_space)}")

if __name__ == "__main__":
    main()
