#!/usr/bin/env python3
"""Extrae UN StaticMesh real del .udk → GLB."""
from __future__ import annotations
import argparse, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from unreal.package_reader import UnrealPackage
from unreal.static_mesh import extract_geometry
from glb.writer import write_glb

def main() -> None:
    ap = argparse.ArgumentParser(description="UDK StaticMesh → GLB")
    ap.add_argument("udk")
    ap.add_argument("--name", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--dump-raw", action="store_true")
    args = ap.parse_args()
    if not os.path.isfile(args.udk):
        print(f"ERROR: file not found: {args.udk}")
        print("Failed at: open package")
        sys.exit(1)
    print(f"Opening {args.udk} ...")
    try:
        pkg = UnrealPackage(args.udk)
    except Exception as e:
        print(f"ERROR: package parse failed: {e}")
        print("Failed at: package header/names/imports/exports")
        sys.exit(1)
    s = pkg.summary
    print(f"OK package UE3 version={s.version} names={s.name_count} imports={s.import_count} exports={s.export_count}")
    meshes = pkg.find_exports_by_class("StaticMesh")
    if not meshes:
        print("ERROR: no StaticMesh exports")
        print("Failed at: find StaticMesh")
        sys.exit(1)
    print(f"StaticMesh count: {len(meshes)}")
    if args.name:
        target = next((e for e in meshes if e.object_name == args.name), None)
        if target is None:
            print(f"ERROR: StaticMesh '{args.name}' not found")
            for e in sorted(meshes, key=lambda x: x.object_name):
                print(f"  {e.object_name}  ({e.serial_size} bytes)")
            sys.exit(1)
    else:
        target = min(meshes, key=lambda e: e.serial_size)
    print(f"Target: {target.object_name}  export#{target.index}  size={target.serial_size}  offset={target.serial_offset}")
    raw = pkg.raw_object_data(target)
    if args.dump_raw:
        path = f"{target.object_name}.bin"
        open(path, "wb").write(raw)
        print(f"Raw dump: {path}")
    print("Extracting geometry...")
    try:
        geo = extract_geometry(raw, name=target.object_name, names=pkg.names, ar_ver=s.version,
                              package_data=pkg.data, serial_offset=target.serial_offset)
    except ValueError as e:
        print(f"FAILED: {e}")
        from unreal.static_mesh import scan_candidate_buffers
        print("VertexStream candidates:")
        for line in scan_candidate_buffers(raw):
            print(line)
        sys.exit(1)
    print(f"OK vertices={len(geo.vertices)} indices={len(geo.indices)} tris={len(geo.indices)//3}")
    print(f"  {geo.notes}")
    xs=[v[0] for v in geo.vertices]; ys=[v[1] for v in geo.vertices]; zs=[v[2] for v in geo.vertices]
    print(f"  bbox X[{min(xs):.3f},{max(xs):.3f}] Y[{min(ys):.3f},{max(ys):.3f}] Z[{min(zs):.3f},{max(zs):.3f}]")
    out = args.out or f"{target.object_name}.glb"
    write_glb(out, geo.vertices, geo.indices, mesh_name=target.object_name)
    print(f"GLB written: {out} ({os.path.getsize(out)} bytes)")

if __name__ == "__main__":
    main()
