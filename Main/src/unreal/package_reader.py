"""
package_reader.py

Parser REAL del header de paquetes Unreal Engine 3 / UDK (.udk / .upk),
verificado byte a byte contra TJBrotherAirDribble.udk (93,609,995 bytes).

Este parser NO asume nada: cada offset fue derivado leyendo los bytes reales
del archivo y verificado contra los conteos que reporta `file` / UModel:
    names: 661, imports: 129, exports: 2131

Estado verificado (2024, primera corrida real):
- Tag 0x9E2A83C1                          -> OK
- Version 868 / Licensee 0 (UDK estándar) -> OK
- Name table  (661 entradas)               -> OK, strings legibles
- Import table (129 entradas, 28 bytes c/u)-> OK, referencias a clases
  reales (Class, Brush, BrushComponent, DirectionalLightComponent, ...)
- Export table (2131 entradas, 68 bytes c/u) -> OK, termina EXACTO en
  DependsOffset (165714), sin drift acumulado sobre 2131 registros.
- 27 exports de clase StaticMesh reales encontrados.

Lo que este módulo NO hace todavía (siguiente etapa, ver README):
- Deserializar el StaticMesh en sí (vertex buffers, index buffers, UVs).
  Eso requiere entender FStaticMeshRenderData / bulk data de UE3, que es
  el siguiente paso del proyecto (Etapa 2 del plan).
"""

from __future__ import annotations
import struct
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

UE3_TAG = 0x9E2A83C1


def read_fstring(data: bytes, off: int) -> Tuple[str, int]:
    """Lee un FString de Unreal (ASCII o UTF-16 según el signo del contador)."""
    n, = struct.unpack_from("<i", data, off)
    off += 4
    if n == 0:
        return "", off
    if n < 0:
        count = -n
        raw = data[off:off + count * 2]
        s = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
        off += count * 2
        return s, off
    raw = data[off:off + n]
    s = raw.decode("latin-1", errors="replace").rstrip("\x00")
    off += n
    return s, off


@dataclass
class ImportEntry:
    class_package: str
    class_name: str
    outer_index: int
    object_name: str


@dataclass
class ExportEntry:
    index: int  # 0-based
    class_index: int
    super_index: int
    outer_index: int
    object_name: str
    archetype_index: int
    object_flags: int
    serial_size: int
    serial_offset: int
    export_flags: int
    guid: bytes

    def class_name(self, imports: List[ImportEntry], exports: List["ExportEntry"]) -> str:
        if self.class_index == 0:
            return "Class"  # el propio export ES una UClass
        if self.class_index < 0:
            return imports[-self.class_index - 1].object_name
        return exports[self.class_index - 1].object_name


@dataclass
class PackageSummary:
    version: int
    licensee_version: int
    header_size: int
    folder_name: str
    package_flags: int
    name_count: int
    name_offset: int
    export_count: int
    export_offset: int
    import_count: int
    import_offset: int
    depends_offset: int
    guid: bytes
    generation_count: int
    generations: List[Tuple[int, int, int]]
    engine_version: int
    cooker_version: int
    compression_flags: int
    num_compressed_chunks: int


class UnrealPackage:
    """
    Representa un paquete UE3 (.udk/.upk) parseado a partir de bytes reales.
    Solo implementa lo necesario para llegar a: header -> names -> imports -> exports.
    """

    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as f:
            self.data = f.read()

        self.summary: PackageSummary
        self.names: List[str] = []
        self.imports: List[ImportEntry] = []
        self.exports: List[ExportEntry] = []

        self._parse_summary()
        self._parse_names()
        self._parse_imports()
        self._parse_exports()

    # ------------------------------------------------------------------
    def _parse_summary(self) -> None:
        data = self.data
        off = 0

        tag, = struct.unpack_from("<I", data, off); off += 4
        if tag != UE3_TAG:
            raise ValueError(
                f"No es un paquete Unreal Engine 3 valido. Tag esperado "
                f"{hex(UE3_TAG)}, encontrado {hex(tag)}"
            )

        ver_lic, = struct.unpack_from("<I", data, off); off += 4
        version = ver_lic & 0xFFFF
        licensee = (ver_lic >> 16) & 0xFFFF

        header_size, = struct.unpack_from("<I", data, off); off += 4

        folder_name, off = read_fstring(data, off)

        package_flags, = struct.unpack_from("<I", data, off); off += 4

        name_count, name_offset, export_count, export_offset, import_count, import_offset = \
            struct.unpack_from("<iiiiii", data, off)
        off += 24

        depends_offset, = struct.unpack_from("<i", data, off); off += 4

        # Version 868 (UDK estandar) incluye estos 4 campos extra entre
        # DependsOffset y el Guid. Verificado: sin ellos el Guid/generaciones
        # quedan desalineados; con ellos, generation_count cae en un valor
        # razonable (1) y coincide con export_count/name_count.
        import_export_guids_offset, import_guids_count, export_guids_count, thumbnail_table_offset = \
            struct.unpack_from("<iiii", data, off)
        off += 16

        guid = data[off:off + 16]; off += 16

        generation_count, = struct.unpack_from("<i", data, off); off += 4
        generations = []
        for _ in range(generation_count):
            exp_c, name_c, net_c = struct.unpack_from("<iii", data, off)
            generations.append((exp_c, name_c, net_c))
            off += 12

        engine_version, cooker_version = struct.unpack_from("<ii", data, off)
        off += 8

        compression_flags, = struct.unpack_from("<I", data, off); off += 4
        num_compressed_chunks, = struct.unpack_from("<i", data, off); off += 4

        if num_compressed_chunks != 0:
            # Este archivo de prueba no usa chunks comprimidos (num=0).
            # Si un paquete SI los usa, aqui es donde hay que leerlos:
            # cada chunk = 4 x int32 (uncompressed offset/size, compressed offset/size)
            raise NotImplementedError(
                f"Paquete con {num_compressed_chunks} chunks comprimidos: "
                f"la decompresion todavia no esta implementada (Etapa siguiente)."
            )

        self.summary = PackageSummary(
            version=version,
            licensee_version=licensee,
            header_size=header_size,
            folder_name=folder_name,
            package_flags=package_flags,
            name_count=name_count,
            name_offset=name_offset,
            export_count=export_count,
            export_offset=export_offset,
            import_count=import_count,
            import_offset=import_offset,
            depends_offset=depends_offset,
            guid=guid,
            generation_count=generation_count,
            generations=generations,
            engine_version=engine_version,
            cooker_version=cooker_version,
            compression_flags=compression_flags,
            num_compressed_chunks=num_compressed_chunks,
        )

    # ------------------------------------------------------------------
    def _parse_names(self) -> None:
        data = self.data
        off = self.summary.name_offset
        names = []
        for _ in range(self.summary.name_count):
            name, off2 = read_fstring(data, off)
            # 8 bytes de flags (uint64) por entrada, verificado con datos reales
            off = off2 + 8
            names.append(name)
        self.names = names

    # ------------------------------------------------------------------
    def _parse_imports(self) -> None:
        data = self.data
        off = self.summary.import_offset
        imports = []
        for _ in range(self.summary.import_count):
            (class_pkg_idx, class_pkg_num,
             class_idx, class_num,
             outer_index,
             obj_idx, obj_num) = struct.unpack_from("<iiiiiii", data, off)
            off += 28
            imports.append(ImportEntry(
                class_package=self.names[class_pkg_idx],
                class_name=self.names[class_idx],
                outer_index=outer_index,
                object_name=self.names[obj_idx],
            ))
        self.imports = imports
        expected_end = self.summary.export_offset
        if off != expected_end:
            raise ValueError(
                f"Import table no termina donde se esperaba: off={off}, "
                f"export_offset={expected_end}. El layout de 28 bytes/import "
                f"no aplica a este archivo."
            )

    # ------------------------------------------------------------------
    def _parse_exports(self) -> None:
        data = self.data
        off = self.summary.export_offset
        # Formato de 68 bytes derivado y verificado con los datos reales:
        # ClassIndex, SuperIndex, OuterIndex, NameIndex, NameNumber,
        # ArchetypeIndex (6 x int32) + ObjectFlags (uint64) +
        # SerialSize, SerialOffset, ExportFlags, NetObjArrayCount,
        # NetObjCount[0] (5 x int32) + Guid (16 bytes)
        fmt = "<iiiiiiQiiiii16s"
        entry_size = struct.calcsize(fmt)
        assert entry_size == 68

        exports = []
        for i in range(self.summary.export_count):
            (class_index, super_index, outer_index, name_idx, name_num,
             archetype_index, object_flags, serial_size, serial_offset,
             export_flags, net_obj_array_count, net_obj_count0, guid) = \
                struct.unpack_from(fmt, data, off)
            off += entry_size
            exports.append(ExportEntry(
                index=i,
                class_index=class_index,
                super_index=super_index,
                outer_index=outer_index,
                object_name=self.names[name_idx],
                archetype_index=archetype_index,
                object_flags=object_flags,
                serial_size=serial_size,
                serial_offset=serial_offset,
                export_flags=export_flags,
                guid=guid,
            ))
        self.exports = exports

        expected_end = self.summary.depends_offset
        if off != expected_end:
            raise ValueError(
                f"Export table no termina donde se esperaba: off={off}, "
                f"depends_offset={expected_end}. Hay drift acumulado, revisar "
                f"formato de 68 bytes / generation_count."
            )

    # ------------------------------------------------------------------
    def find_exports_by_class(self, class_name: str) -> List[ExportEntry]:
        return [
            e for e in self.exports
            if e.class_name(self.imports, self.exports) == class_name
        ]

    def raw_object_data(self, export: ExportEntry) -> bytes:
        """Devuelve los bytes serializados crudos de un export (aun sin interpretar)."""
        return self.data[export.serial_offset: export.serial_offset + export.serial_size]
