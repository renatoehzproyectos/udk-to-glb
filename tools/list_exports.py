#!/usr/bin/env python3
"""Lista exports por clase y muestra StaticMeshActor / Component counts."""
from __future__ import annotations
import os, sys
from collections import Counter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from unreal.package_reader import UnrealPackage

def main():
    if len(sys.argv) < 2:
        print("Uso: list_exports.py <udk>")
        sys.exit(1)
    pkg = UnrealPackage(sys.argv[1])
    classes = Counter(e.class_name(pkg.imports, pkg.exports) for e in pkg.exports)
    print(f"Exports: {len(pkg.exports)}")
    for c, n in classes.most_common():
        print(f"  {n:5d}  {c}")
    sm = pkg.find_exports_by_class("StaticMesh")
    print(f"\nStaticMesh: {len(sm)}")
    for e in sorted(sm, key=lambda x: x.serial_size)[:15]:
        print(f"  {e.object_name:40s} {e.serial_size:8d} bytes")

if __name__ == "__main__":
    main()
