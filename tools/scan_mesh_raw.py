#!/usr/bin/env python3
"""
Diagnóstico: vuelca candidatos de VertexStream / IndexBuffer
dentro del bloque serializado de un StaticMesh.

Uso (cuando el .udk esté disponible):
  python3 tools/scan_mesh_raw.py TJBrotherAirDribble.udk
  python3 tools/scan_mesh_raw.py TJBrotherAirDribble.udk --name HoopBase
  python3 tools/scan_mesh_raw.py TJBrotherAirDribble.udk --dump
"""

from __future__ import annotations
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unreal.package_reader import UnrealPackage
from unreal.static_mesh import scan_candidate_buffers, extract_geometry


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("udk")
    ap.add_argument("--name", default=None)
    ap.add_argument("--dump", action="store_true", help="guardar .bin del mesh")
    ap.add_argument("--try-extract", action="store_true", help="intentar extract completo")
    args = ap.parse_args()

    if not os.path.isfile(args.udk):
        print(f"ERROR: {args.udk} no encontrado")
        sys.exit(1)

    pkg = UnrealPackage(args.udk)
    meshes = pkg.find_exports_by_class("StaticMesh")
    if not meshes:
        print("No StaticMesh exports")
        sys.exit(1)

    if args.name:
        target = next((e for e in meshes if e.object_name == args.name), None)
        if not target:
            print("Nombres:", [e.object_name for e in meshes])
            sys.exit(1)
    else:
        target = min(meshes, key=lambda e: e.serial_size)

    print(f"Mesh: {target.object_name}  size={target.serial_size}  off={target.serial_offset}")
    raw = pkg.raw_object_data(target)
    print(f"bytes: {len(raw)}")

    if args.dump:
        path = f"{target.object_name}.bin"
        open(path, "wb").write(raw)
        print(f"dumped {path}")

    print("Candidatos VertexStream:")
    for line in scan_candidate_buffers(raw):
        print(line)

    if args.try_extract:
        print("\nIntentando extract_geometry...")
        try:
            geo = extract_geometry(raw, target.object_name)
            print(f"OK verts={len(geo.vertices)} idx={len(geo.indices)}  {geo.notes}")
        except ValueError as e:
            print(f"FAILED: {e}")


if __name__ == "__main__":
    main()
