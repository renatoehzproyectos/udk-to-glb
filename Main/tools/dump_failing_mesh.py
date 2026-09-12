#!/usr/bin/env python3
"""Dump raw bytes + VS scan for a named StaticMesh (debug)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from unreal.package_reader import UnrealPackage
from unreal.static_mesh import scan_candidate_buffers, extract_geometry

def main():
    if len(sys.argv) < 3:
        print("Usage: dump_failing_mesh.py file.udk MeshName")
        sys.exit(1)
    pkg = UnrealPackage(sys.argv[1])
    name = sys.argv[2]
    meshes = pkg.find_exports_by_class("StaticMesh")
    e = next((x for x in meshes if x.object_name == name), None)
    if not e:
        print("not found. names:", [x.object_name for x in meshes])
        sys.exit(1)
    raw = pkg.raw_object_data(e)
    open(f"{name}.bin", "wb").write(raw)
    print(f"wrote {name}.bin size={len(raw)}")
    for line in scan_candidate_buffers(raw, 30):
        print(line)
    try:
        geo = extract_geometry(raw, name, pkg.names, pkg.summary.version, pkg.data, e.serial_offset)
        print("EXTRACT OK", len(geo.vertices), len(geo.indices), geo.notes)
    except ValueError as ex:
        print("EXTRACT FAIL", ex)

if __name__ == "__main__":
    main()
