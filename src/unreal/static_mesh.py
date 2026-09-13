"""
static_mesh.py — UE3/UDK StaticMesh (Rocket League maps)

12/27 meshes OK on device. Remaining often use bulk payloads or
layouts where IB sits far after UV data. Tiny false hits rejected.
"""

from __future__ import annotations
import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

try:
    from .properties import find_after_properties
except ImportError:
    from properties import find_after_properties  # type: ignore


@dataclass
class MeshGeometry:
    name: str
    vertices: List[Tuple[float, float, float]]
    indices: List[int]
    uvs: Optional[List[Tuple[float, float]]] = None
    source_offset: int = 0
    source_size: int = 0
    notes: str = ""


def _f_ok(x, y, z, lim=1e7):
    if abs(x) > lim or abs(y) > lim or abs(z) > lim:
        return False
    if x != x or y != y or z != z:
        return False
    return True


def _read_f3(data, off, count, stride=12):
    need = count * stride
    if count < 3 or count > 1_500_000 or off + need > len(data):
        return None
    # Broad, cheap pre-check (up to 24 evenly-spaced samples) before ever
    # committing to a full read. A full read of up to 1.5M verts is
    # expensive, and on a multi-megabyte buffer, many coincidental byte
    # patterns pass a weak 3-point check but fail a broader one — this is
    # what keeps find_loose from doing dozens of full-cost reads that all
    # turn out to be false positives.
    nsamples = min(24, count)
    step = max(1, count // nsamples)
    for i in range(0, count, step):
        x, y, z = struct.unpack_from("<fff", data, off + i * stride)
        if not _f_ok(x, y, z):
            return None
    if stride == 12:
        # Contiguous floats: one bulk C-level conversion instead of a
        # per-vertex struct.unpack_from call.
        flat = struct.unpack_from(f"<{count * 3}f", data, off)
        for v in flat:
            if v != v or abs(v) > 1e7:
                return None
        verts = list(zip(flat[0::3], flat[1::3], flat[2::3]))
    else:
        verts = []
        for i in range(count):
            x, y, z = struct.unpack_from("<fff", data, off + i * stride)
            if not _f_ok(x, y, z):
                return None
            verts.append((x, y, z))
    if count >= 6:
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        zs = [v[2] for v in verts]
        if (max(xs) - min(xs) < 1e-5 and max(ys) - min(ys) < 1e-5 and max(zs) - min(zs) < 1e-5):
            return None
    return verts


def _half_to_float(h):
    # IEEE 754 half → float
    s = (h >> 15) & 1
    e = (h >> 10) & 0x1F
    f = h & 0x3FF
    if e == 0:
        if f == 0:
            return -0.0 if s else 0.0
        return ((-1) ** s) * (f / 1024.0) * (2 ** -14)
    if e == 31:
        return float("nan")
    return ((-1) ** s) * (1 + f / 1024.0) * (2 ** (e - 15))


def _read_f3_half(data, off, count):
    need = count * 6
    if count < 3 or off + need > len(data):
        return None
    verts = []
    for i in range(count):
        hx, hy, hz = struct.unpack_from("<HHH", data, off + i * 6)
        x, y, z = _half_to_float(hx), _half_to_float(hy), _half_to_float(hz)
        if not _f_ok(x, y, z):
            return None
        verts.append((x, y, z))
    return verts


def parse_vs_classic(data, start):
    if start + 8 > len(data):
        return None
    vsize, nverts = struct.unpack_from("<ii", data, start)
    if vsize not in (12, 16, 8, 6) or not (3 <= nverts <= 1_500_000):
        return None
    off = start + 8

    if vsize in (12, 16):
        for label, hdr, use_esize in (
            ("bulkB", 8, True),
            ("bulkA", 4, False),
            ("bulkC", 12, True),
            ("direct", 0, False),
        ):
            o = off
            if label == "bulkB" and o + 8 <= len(data):
                esize, count = struct.unpack_from("<ii", data, o)
                if esize == vsize and count == nverts:
                    verts = _read_f3(data, o + 8, nverts, vsize)
                    if verts:
                        return verts, o + 8 + nverts * vsize, f"VS size={vsize} n={nverts} bulkB"
            elif label == "bulkA" and o + 4 <= len(data):
                count = struct.unpack_from("<i", data, o)[0]
                if count == nverts:
                    verts = _read_f3(data, o + 4, nverts, vsize)
                    if verts:
                        return verts, o + 4 + nverts * vsize, f"VS size={vsize} n={nverts} bulkA"
            elif label == "bulkC" and o + 12 <= len(data):
                esize, count, sz = struct.unpack_from("<iii", data, o)
                if esize == vsize and count == nverts and sz == nverts * vsize:
                    verts = _read_f3(data, o + 12, nverts, vsize)
                    if verts:
                        return verts, o + 12 + sz, f"VS size={vsize} n={nverts} bulkC"
            elif label == "direct":
                if o + nverts * vsize <= len(data):
                    verts = _read_f3(data, o, nverts, vsize)
                    if verts:
                        return verts, o + nverts * vsize, f"VS size={vsize} n={nverts} direct"

    # half-float positions (size 6 or 8 with pad)
    if vsize in (6, 8) and off + nverts * 6 <= len(data):
        verts = _read_f3_half(data, off, nverts)
        if verts:
            return verts, off + nverts * vsize, f"VS half size={vsize} n={nverts}"

    return None


def parse_bulk_f3(data, start, max_count=400000):
    if start + 8 <= len(data):
        esize, count = struct.unpack_from("<ii", data, start)
        if esize == 12 and 8 <= count <= max_count and start + 8 + count * 12 <= len(data):
            verts = _read_f3(data, start + 8, count, 12)
            if verts:
                return verts, start + 8 + count * 12, f"rawBulkB n={count}"
    if start + 4 <= len(data):
        count = struct.unpack_from("<i", data, start)[0]
        if 8 <= count <= max_count and start + 4 + count * 12 <= len(data):
            verts = _read_f3(data, start + 4, count, 12)
            if verts:
                return verts, start + 4 + count * 12, f"rawBulkA n={count}"
    return None


def try_index_buffer(data, start, max_index, ints=None, ints_residue=0):
    """ints, if given, is a pre-converted `array('i')` view of `data` at byte
    offset `ints_residue` (see find_ib) — lets the very-hot header-count read
    be an array index instead of a fresh struct.unpack_from call for every
    4-byte step of a multi-megabyte buffer."""
    if start + 4 > len(data) or max_index < 2:
        return None

    def read_i32(off):
        if ints is not None and off >= ints_residue and (off - ints_residue) % 4 == 0:
            idx = (off - ints_residue) // 4
            if idx < len(ints):
                return ints[idx]
        return struct.unpack_from("<i", data, off)[0]

    def u16(o, count):
        if count < 3 or count % 3 or count > 3_000_000 or o + count * 2 > len(data):
            return None
        sm = struct.unpack_from(f"<{min(9, count)}H", data, o)
        if max(sm) > max_index:
            return None
        idx = list(struct.unpack_from(f"<{count}H", data, o))
        if max(idx) <= max_index and min(idx) >= 0:
            return idx, o + count * 2
        return None

    def u32(o, count):
        if count < 3 or count % 3 or count > 3_000_000 or o + count * 4 > len(data):
            return None
        sm = struct.unpack_from(f"<{min(9, count)}I", data, o)
        if max(sm) > max_index:
            return None
        idx = list(struct.unpack_from(f"<{count}I", data, o))
        if max(idx) <= max_index and min(idx) >= 0:
            return idx, o + count * 4
        return None

    for hdr in (0, 4, 8, 12):
        off = start + hdr
        if off + 4 > len(data):
            continue
        count = read_i32(off)
        r = u16(off + 4, count)
        if r:
            return r[0], r[1], f"IB u16 n={count} hdr={hdr}"
        r = u32(off + 4, count)
        if r:
            return r[0], r[1], f"IB u32 n={count} hdr={hdr}"

    if start + 8 <= len(data):
        esize, count = read_i32(start), read_i32(start + 4)
        if esize == 2:
            r = u16(start + 8, count)
            if r:
                return r[0], r[1], f"IB bulk u16 n={count}"
        if esize == 4:
            r = u32(start + 8, count)
            if r:
                return r[0], r[1], f"IB bulk u32 n={count}"
    return None


def try_skip_uv(data, start, nverts):
    if start + 12 > len(data):
        return None
    ntc, item_size, nv = struct.unpack_from("<iii", data, start)
    if not (1 <= ntc <= 8 and 12 <= item_size <= 128 and nv == nverts):
        return None
    off = start + 12
    if off + 4 <= len(data) and struct.unpack_from("<i", data, off)[0] in (0, 1):
        off += 4
    for hdr in (0, 4, 8):
        o = off + hdr
        if o + 4 > len(data):
            continue
        count = struct.unpack_from("<i", data, o)[0]
        if count != nverts:
            continue
        for stride in (item_size, ntc * 8 + 24, ntc * 4 + 12):
            if o + 4 + count * stride <= len(data):
                return o + 4 + count * stride
        if o + 8 <= len(data):
            es, cnt = struct.unpack_from("<ii", data, o)
            if cnt == nverts and 8 <= es <= 128 and o + 8 + cnt * es <= len(data):
                return o + 8 + cnt * es
    return None


def find_ib(data, verts_end, nverts, max_index, max_scan=2_000_000):
    """Scans for the index buffer following the vertex buffer. The header
    check at each 4-byte step used to be a fresh struct.unpack_from call —
    across a multi-megabyte remainder that's millions of Python-level calls.
    We now bulk-convert the whole remainder to an int32 array once (one C
    call via the array module) and index into it instead.

    max_scan bounds the worst case: a real index buffer normally follows the
    vertex buffer closely, not megabytes away, so if nothing turns up within
    a reasonable window we give up rather than scanning the entire remainder
    of a multi-megabyte export for a match that (empirically) isn't there."""
    from array import array as _array

    search = verts_end
    for d in range(0, 256, 4):
        sk = try_skip_uv(data, verts_end + d, nverts)
        if sk:
            search = sk
            break
    end = min(len(data) - 8, search + max_scan)

    def scan_from(lo):
        hi = min(len(data) - 8, lo + max_scan)
        if lo >= hi:
            return None
        residue = lo % 4
        nints = (len(data) - residue) // 4
        if nints <= 0:
            return None
        ints = _array("i")
        ints.frombytes(data[residue : residue + nints * 4])
        start = lo
        while start < hi:
            r = try_index_buffer(data, start, max_index, ints, residue)
            if r:
                return r
            start += 4
        return None

    best = scan_from(search)
    if best is None and search != verts_end:
        best = scan_from(verts_end)
    return best


def find_best_vs(data, scan_from=0):
    """Scans for a plausible vertex-buffer header (vsize in a small known
    set). Bulk-converts the buffer to an int32 array once instead of one
    struct.unpack_from call per 4-byte step — same rationale as find_ib."""
    from array import array as _array

    best = None
    end = len(data) - 16
    if end <= 0:
        return None
    nints = len(data) // 4
    ints = _array("i")
    ints.frombytes(data[: nints * 4])

    def scan(lo, hi):
        nonlocal best
        start_idx = (lo & ~3) // 4
        end_idx = min(hi // 4, len(ints))
        for i in range(start_idx, end_idx):
            vs = ints[i]
            if vs not in (12, 16, 8, 6):
                continue
            pos = i * 4
            r = parse_vs_classic(data, pos)
            if r and (best is None or len(r[0]) > len(best[0])):
                best = (r[0], r[1], r[2], pos)

    scan(scan_from, end)
    if best is None and scan_from > 0:
        scan(0, min(scan_from, end))
    return best


def find_loose(data):
    from array import array as _array

    end = len(data) - 16
    if end <= 0:
        return None
    nints = len(data) // 4
    ints = _array("i")
    ints.frombytes(data[: nints * 4])
    end_idx = min(end // 4, len(ints))

    cands = []
    for i in range(0, end_idx):
        v = ints[i]
        pos = i * 4
        if v == 12 and pos + 8 < end:
            c = ints[i + 1] if i + 1 < len(ints) else struct.unpack_from("<i", data, pos + 4)[0]
            if 8 <= c <= 300000:
                r = parse_bulk_f3(data, pos)
                if r:
                    cands.append((pos, r))
        elif 8 <= v <= 300000:
            r = parse_bulk_f3(data, pos)
            if r:
                cands.append((pos, r))
        if len(cands) > 60:
            cands.sort(key=lambda x: -len(x[1][0]))
            cands = cands[:30]
    cands.sort(key=lambda x: -len(x[1][0]))
    for pos, (verts, vend, note) in cands[:3]:
        if len(verts) < 8:
            continue
        ib = find_ib(data, vend, len(verts), len(verts) - 1)
        if ib:
            return verts, vend, f"loose {note}", pos, ib[0], ib[1], ib[2]
    return None


def find_bounds(data, limit=400_000):
    """Locate a usable bounding box for this mesh, so find_triangle_soup has
    something to anchor its scan to. Two fingerprints are tried:

    1) FBoxSphereBounds (Origin, BoxExtent, SphereRadius) — the common case.
       SphereRadius must equal |BoxExtent| (within tolerance); this is a
       strong signature that rules out coincidental float matches.
    2) Plain FBox (Min, Max) — some custom meshes (seen on flat, custom
       "Ground"-style props with near-zero thickness on one axis) don't carry
       the sphere-bounds struct at all, or it doesn't pass check (1). Any
       Max > Min box with at least two axes of real size is accepted; among
       candidates we prefer the largest footprint, since real bounds tend to
       dwarf coincidental float matches.

    Both scans check every byte offset (fields aren't guaranteed 4-byte
    aligned in this format), so — same as find_triangle_soup — we bulk
    convert each of the 4 byte alignments to a float array once instead of
    calling struct.unpack_from per byte.
    """
    from array import array as _array

    n = min(len(data) - 28, limit)
    for r in range(4):
        usable = max(n, 0) - r
        nfloats = usable // 4
        if nfloats < 7:
            continue
        floats = _array("f")
        floats.frombytes(data[r : r + nfloats * 4])
        last_i = nfloats - 7
        for i in range(0, last_i + 1):
            ex, ey, ez = floats[i + 3], floats[i + 4], floats[i + 5]
            if ex < 1.0 or ey < 1.0 or ez < 1.0:
                continue
            if ex > 1e5 or ey > 1e5 or ez > 1e5:
                continue
            ox, oy, oz = floats[i], floats[i + 1], floats[i + 2]
            if abs(ox) > 1e5 or abs(oy) > 1e5 or abs(oz) > 1e5:
                continue
            rad = floats[i + 6]
            if rad != rad:
                continue
            mag = (ex * ex + ey * ey + ez * ez) ** 0.5
            if mag < 1e-3:
                continue
            if abs(rad - mag) / mag < 0.01:
                return (ox, oy, oz), (ex, ey, ez), rad

    n2 = min(len(data) - 24, limit)
    best = None
    best_area = -1.0
    for r in range(4):
        usable = max(n2, 0) - r
        nfloats = usable // 4
        if nfloats < 6:
            continue
        floats = _array("f")
        floats.frombytes(data[r : r + nfloats * 4])
        last_i = nfloats - 6
        for i in range(0, last_i + 1):
            minx, miny, minz = floats[i], floats[i + 1], floats[i + 2]
            maxx, maxy, maxz = floats[i + 3], floats[i + 4], floats[i + 5]
            if not (maxx >= minx and maxy >= miny and maxz >= minz):
                continue
            sx, sy, sz = maxx - minx, maxy - miny, maxz - minz
            dims = sorted((sx, sy, sz))
            if dims[1] < 500 or dims[2] > 1e6:
                continue
            area = dims[1] * dims[2]  # two largest dims
            if area > best_area:
                ex, ey, ez = sx / 2, sy / 2, sz / 2
                origin = ((minx + maxx) / 2, (miny + maxy) / 2, (minz + maxz) / 2)
                extent = (max(ex, 1.0), max(ey, 1.0), max(ez, 1.0))
                radius = (ex * ex + ey * ey + ez * ez) ** 0.5
                best = (origin, extent, radius)
                best_area = area
    return best


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return (a[0] ** 2 + a[1] ** 2 + a[2] ** 2) ** 0.5


def find_triangle_soup(data, scan_from, bounds, min_gap=40):
    """Legacy FStaticMeshTriangle fallback: some custom/modded meshes in this
    package store non-indexed per-triangle wedge data (Vertices[3] followed by
    variable-length UV/tangent/color blocks) instead of the shared
    vertex+index buffers the LOD render path uses. We can't reliably predict
    the per-triangle stride (it depends on NumUVs), so instead of assuming a
    fixed layout we re-scan for the next valid Vertices[3] pattern anywhere in
    the buffer. Candidates are constrained to the mesh's own FBoxSphereBounds
    (with a margin) and to non-degenerate triangle shape, which is what keeps
    this from turning into noise on multi-megabyte exports.

    Perf note: naive byte-by-byte struct.unpack_from was ~1 python call per
    byte (multi-minute on a 4-5MB mesh, and since this runs synchronously it
    froze the browser tab entirely). Instead we bulk-convert each of the 4
    possible byte alignments to a float array in one C call (array module),
    then do a cheap first-vertex bbox check as a plain array-index compare
    before ever touching the expensive edge/area validation.
    """
    from array import array as _array

    origin, extent, radius = bounds
    margin = 1.15
    lox, loy, loz = (origin[i] - extent[i] * margin for i in range(3))
    hix, hiy, hiz = (origin[i] + extent[i] * margin for i in range(3))
    diag = 2 * radius
    min_edge = diag * 0.01
    min_area = min_edge * min_edge * 0.1

    n = len(data)
    candidates = []  # (byte_offset, [(x,y,z)*3])

    for r in range(4):
        usable = n - r
        nfloats = usable // 4
        # need 9 floats (3 verts) ahead, and enough trailing bytes for min_gap
        if nfloats < 9:
            continue
        floats = _array("f")
        floats.frombytes(data[r : r + nfloats * 4])
        last_i = nfloats - 9
        i = 0
        while i <= last_i:
            x0 = floats[i]
            if lox <= x0 <= hix:
                y0 = floats[i + 1]
                z0 = floats[i + 2]
                if loy <= y0 <= hiy and loz <= z0 <= hiz:
                    x1, y1, z1 = floats[i + 3], floats[i + 4], floats[i + 5]
                    x2, y2, z2 = floats[i + 6], floats[i + 7], floats[i + 8]
                    if (
                        lox <= x1 <= hix and loy <= y1 <= hiy and loz <= z1 <= hiz
                        and lox <= x2 <= hix and loy <= y2 <= hiy and loz <= z2 <= hiz
                    ):
                        v0, v1, v2 = (x0, y0, z0), (x1, y1, z1), (x2, y2, z2)
                        e1, e2, e3 = _sub(v1, v0), _sub(v2, v0), _sub(v2, v1)
                        if (
                            min(_norm(e1), _norm(e2), _norm(e3)) >= min_edge
                            and _norm(_cross(e1, e2)) / 2 >= min_area
                        ):
                            candidates.append((r + i * 4, [v0, v1, v2]))
            i += 1

    candidates.sort(key=lambda c: c[0])

    verts = []
    indices = []
    next_ok = scan_from
    for off, tri in candidates:
        if off < next_ok:
            continue
        base = len(verts)
        verts.extend(tri)
        indices.extend((base, base + 1, base + 2))
        next_ok = off + min_gap
    return verts, indices


def _valid_mesh(verts, indices):
    # min 8 verts and at least 1 triangle; prefer real props over noise
    if len(verts) < 8 or len(indices) < 3:
        return False
    if len(indices) % 3:
        return False
    return True


def _is_suspicious(verts, indices):
    """A real indexed mesh with hundreds/thousands of vertices normally uses
    most of them. A tiny index buffer (<=8 tris, <=10 unique verts touched)
    carved out of a LARGE vertex buffer (>=50 verts) is the signature of a
    coincidentally-valid few-index match sitting in front of the real index
    buffer (or of the "vertex buffer" match itself being bogus) — seen in
    practice on meshes like a "three" digit (1248 verts, only 6 referenced)
    and custom map props (3632-14698 verts, only 3 referenced). Genuinely
    tiny real meshes (e.g. a 12-vert flat collision plane) never trip this,
    since the >=50-vert gate only applies to large buffers."""
    if len(verts) < 50:
        return False
    tri_count = len(indices) // 3
    if tri_count > 8:
        return False
    return len(set(indices)) <= 10


def extract_geometry(
    raw: bytes,
    name: str = "StaticMesh",
    names: Optional[List[str]] = None,
    ar_ver: int = 868,
    package_data: Optional[bytes] = None,
    serial_offset: int = 0,
) -> MeshGeometry:
    if len(raw) < 32:
        raise ValueError(
            f"StaticMesh '{name}': bloque demasiado pequeño ({len(raw)}). "
            "Failed while locating vertex buffers."
        )

    scan_from = 0
    if names:
        try:
            pe = find_after_properties(raw, names)
            if pe > 0:
                scan_from = pe
        except ValueError:
            pass

    weak = None  # (MeshGeometry) — a suspicious-but-technically-valid match, kept only if nothing better turns up

    best = find_best_vs(raw, scan_from)
    if best:
        verts, vend, note, vstart = best
        ib = find_ib(raw, vend, len(verts), len(verts) - 1)
        if ib and _valid_mesh(verts, ib[0]):
            geo = MeshGeometry(
                name=name, vertices=verts, indices=ib[0],
                source_offset=vstart, source_size=ib[1] - vstart,
                notes=f"{note} | {ib[2]}",
            )
            if not _is_suspicious(verts, ib[0]):
                return geo
            weak = geo

    loose = find_loose(raw)
    if loose:
        verts, vend, note, vstart, indices, idx_end, idx_note = loose
        if _valid_mesh(verts, indices):
            geo = MeshGeometry(
                name=name, vertices=verts, indices=indices,
                source_offset=vstart, source_size=idx_end - vstart,
                notes=f"{note} | {idx_note}",
            )
            if not _is_suspicious(verts, indices):
                return geo
            weak = weak or geo

    # extended window from package (bulk after export)
    if package_data is not None and serial_offset >= 0:
        ext_end = min(len(package_data), serial_offset + len(raw) + 3_000_000)
        extended = package_data[serial_offset:ext_end]
        if len(extended) > len(raw) + 64:
            best = find_best_vs(extended, 0)
            if best:
                verts, vend, note, vstart = best
                ib = find_ib(extended, vend, len(verts), len(verts) - 1)
                if ib and _valid_mesh(verts, ib[0]):
                    geo = MeshGeometry(
                        name=name, vertices=verts, indices=ib[0],
                        source_offset=vstart, source_size=ib[1] - vstart,
                        notes=f"{note} | {ib[2]} | extended",
                    )
                    if not _is_suspicious(verts, ib[0]):
                        return geo
                    weak = weak or geo

    # Legacy raw-triangle fallback (custom/modded meshes exported through a
    # different serialization path than the LOD render data the other
    # branches above expect). Anchored to the mesh's own Bounds so we don't
    # pick up UV/tangent/color garbage from elsewhere in the export.
    bounds = find_bounds(raw)
    if bounds:
        verts, indices = find_triangle_soup(raw, scan_from, bounds)
        if _valid_mesh(verts, indices):
            geo = MeshGeometry(
                name=name, vertices=verts, indices=indices,
                source_offset=scan_from, source_size=len(raw) - scan_from,
                notes=f"legacy raw-triangle soup n_tris={len(indices)//3}",
            )
            # triangle-soup candidates are inherently more trustworthy (every
            # triangle is independently validated against the mesh's own
            # bounds), so accept even a small one over a suspicious VS/IB hit
            return geo

    # Nothing fully convincing turned up. A suspicious-but-technically-valid
    # match beats a hole in the map — return it, clearly flagged, rather than
    # failing outright.
    if weak is not None:
        weak.notes = f"LOW-CONFIDENCE (tiny index buffer, likely incomplete) | {weak.notes}"
        return weak

    raise ValueError(
        f"StaticMesh '{name}': no se encontró geometría válida "
        f"(VS/bulk+IB, min 8 verts / 3 tris). size={len(raw)}. "
        "Failed while parsing StaticMesh serialization (position/vertex stream)."
    )


def scan_candidate_buffers(raw: bytes, max_hits: int = 20) -> List[str]:
    lines = []
    end = len(raw) - 16
    for pos in range(0, end, 4):
        if struct.unpack_from("<i", raw, pos)[0] in (12, 16, 8, 6):
            r = parse_vs_classic(raw, pos)
            if r:
                lines.append(f"  VERT @0x{pos:06x} n={len(r[0]):6d} {r[2]}")
                if len(lines) >= max_hits:
                    break
    if not lines:
        lines.append("  (no VS candidates)")
    return lines
