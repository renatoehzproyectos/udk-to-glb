#!/usr/bin/env python3
"""
Etapa 1: demostrar que se puede procesar el .udk y encontrar objetos reales.

Uso:
    python3 tools/inspect_package.py /ruta/a/TJBrotherAirDribble.udk
"""
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from unreal.package_reader import UnrealPackage  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print("Uso: inspect_package.py <archivo.udk>")
        sys.exit(1)

    path = sys.argv[1]
    print(f"Abriendo {path} ...")
    pkg = UnrealPackage(path)
    s = pkg.summary

    print(f"OK: paquete UE3 valido")
    print(f"  Version: {s.version} (licensee {s.licensee_version})")
    print(f"  Engine version: {s.engine_version}  Cooker version: {s.cooker_version}")
    print(f"  Compression flags: {s.compression_flags}  Chunks comprimidos: {s.num_compressed_chunks}")
    print(f"  Names: {s.name_count}  Imports: {s.import_count}  Exports: {s.export_count}")
    print()

    classes = Counter(e.class_name(pkg.imports, pkg.exports) for e in pkg.exports)
    print("Clases mas frecuentes entre los exports reales:")
    for cname, n in classes.most_common(15):
        print(f"  {cname:30s} {n}")
    print()

    static_meshes = pkg.find_exports_by_class("StaticMesh")
    print(f"StaticMesh reales encontrados: {len(static_meshes)}")
    for e in static_meshes[:20]:
        print(f"  export#{e.index:5d}  {e.object_name:40s} serial_size={e.serial_size:8d} bytes  offset={e.serial_offset}")
    if len(static_meshes) > 20:
        print(f"  ... y {len(static_meshes) - 20} mas")


if __name__ == "__main__":
    main()
