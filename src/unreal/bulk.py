"""
bulk.py

Helpers para FByteBulkData / TArray BulkSerialize de UE3.
"""

from __future__ import annotations
import struct
from typing import Tuple, Optional


def skip_byte_bulk_data(data: bytes, off: int) -> int:
    """
    FByteBulkData header (UE3 típico):
      int32 BulkDataFlags
      int32 ElementCount
      int32 BulkDataSizeOnDisk
      int32 BulkDataOffsetInFile   (a veces int64 en versiones nuevas)

    Si los datos están inline, ElementCount bytes siguen.
    Si están en otro sitio del archivo, solo se salta el header.
    """
    if off + 16 > len(data):
        return off
    flags, count, size_on_disk, offset_in_file = struct.unpack_from("<iiii", data, off)
    off += 16

    # Flags comunes: 0x1 = StoreInSeparateFile, 0x2 = Optional, etc.
    STORE_IN_SEPARATE = 0x1
    NO_DATA = 0x20  # approximate / varies

    if flags & STORE_IN_SEPARATE:
        return off  # data elsewhere
    if count <= 0:
        return off
    # inline
    if off + size_on_disk <= len(data) and size_on_disk >= 0:
        return off + size_on_disk
    if off + count <= len(data):
        return off + count
    return off


def read_tarray_header(data: bytes, off: int) -> Tuple[int, int]:
    """int32 Count → (count, new_off)."""
    if off + 4 > len(data):
        raise ValueError(f"EOF TArray @{off}")
    count, = struct.unpack_from("<i", data, off)
    return count, off + 4
