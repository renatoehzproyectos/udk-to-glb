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
    for i in (0, count // 2, count - 1):
        x, y, z = struct.unpack_from("<fff", data, off + i * stride)
        if not _f_ok(x, y, z):
            return None
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


def try_index_buffer(data, start, max_index):
    if start + 4 > len(data) or max_index < 2:
        return None

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
        count = struct.unpack_from("<i", data, off)[0]
        r = u16(off + 4, count)
        if r:
            return r[0], r[1], f"IB u16 n={count} hdr={hdr}"
        r = u32(off + 4, count)
        if r:
            return r[0], r[1], f"IB u32 n={count} hdr={hdr}"

    if start + 8 <= len(data):
        esize, count = struct.unpack_from("<ii", data, start)
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


def find_ib(data, verts_end, nverts, max_index):
    search = verts_end
    for d in range(0, 256, 4):
        sk = try_skip_uv(data, verts_end + d, nverts)
        if sk:
            search = sk
            break
    end = len(data) - 8
    # full remainder, step 4
    for start in range(search, end, 4):
        r = try_index_buffer(data, start, max_index)
        if r:
            return r
    if search != verts_end:
        for start in range(verts_end, end, 4):
            r = try_index_buffer(data, start, max_index)
            if r:
                return r
    return None


def find_best_vs(data, scan_from=0):
    best = None
    end = len(data) - 16
    for pos in range(scan_from & ~3, end, 4):
        vs = struct.unpack_from("<i", data, pos)[0]
        if vs not in (12, 16, 8, 6):
            continue
        r = parse_vs_classic(data, pos)
        if r and (best is None or len(r[0]) > len(best[0])):
            best = (r[0], r[1], r[2], pos)
    if best is None and scan_from > 0:
        for pos in range(0, min(scan_from, end), 4):
            if struct.unpack_from("<i", data, pos)[0] not in (12, 16, 8, 6):
                continue
            r = parse_vs_classic(data, pos)
            if r and (best is None or len(r[0]) > len(best[0])):
                best = (r[0], r[1], r[2], pos)
    return best


def find_loose(data):
    end = len(data) - 16
    cands = []
    for pos in range(0, end, 4):
        v = struct.unpack_from("<i", data, pos)[0]
        if v == 12 and pos + 8 < end:
            c = struct.unpack_from("<i", data, pos + 4)[0]
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
    for pos, (verts, vend, note) in cands:
        if len(verts) < 8:
            continue
        ib = find_ib(data, vend, len(verts), len(verts) - 1)
        if ib:
            return verts, vend, f"loose {note}", pos, ib[0], ib[1], ib[2]
    return None


def find_bounds(data, limit=400_000):
    """Locate the native FBoxSphereBounds (Origin, BoxExtent, SphereRadius)
    written right after tagged properties. Fingerprint: SphereRadius must
    equal |BoxExtent| (within tolerance), and BoxExtent must be a real,
    non-degenerate size (rules out coincidental float matches)."""
    n = min(len(data) - 28, limit)
    for off in range(0, max(n, 0)):
        vals = struct.unpack_from("<fffffff", data, off)
        ox, oy, oz, ex, ey, ez, r = vals
        if any(v != v for v in vals):
            continue
        if ex < 1.0 or ey < 1.0 or ez < 1.0:
            continue
        if ex > 1e5 or ey > 1e5 or ez > 1e5:
            continue
        if abs(ox) > 1e5 or abs(oy) > 1e5 or abs(oz) > 1e5:
            continue
        mag = (ex * ex + ey * ey + ez * ez) ** 0.5
        if mag < 1e-3:
            continue
        if abs(r - mag) / mag < 0.01:
            return (ox, oy, oz), (ex, ey, ez), r
    return None


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
    fixed layout we re-scan for the next valid Vertices[3] pattern after each
    hit. Candidates are constrained to the mesh's own FBoxSphereBounds (with
    a margin) and to non-degenerate triangle shape, which is what keeps this
    from turning into noise on multi-megabyte exports."""
    origin, extent, radius = bounds
    margin = 1.15
    lo = tuple(origin[i] - extent[i] * margin for i in range(3))
    hi = tuple(origin[i] + extent[i] * margin for i in range(3))
    diag = 2 * radius
    min_edge = diag * 0.01
    min_area = min_edge * min_edge * 0.1

    def valid_tri(off):
        if off + 36 > len(data):
            return None
        vs = []
        for i in range(3):
            x, y, z = struct.unpack_from("<fff", data, off + i * 12)
            if x != x or y != y or z != z:
                return None
            if not (lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1] and lo[2] <= z <= hi[2]):
                return None
            vs.append((x, y, z))
        e1, e2, e3 = _sub(vs[1], vs[0]), _sub(vs[2], vs[0]), _sub(vs[2], vs[1])
        if min(_norm(e1), _norm(e2), _norm(e3)) < min_edge:
            return None
        if _norm(_cross(e1, e2)) / 2 < min_area:
            return None
        return vs

    verts = []
    indices = []
    pos = scan_from
    n = len(data)
    while pos < n - 36:
        t = valid_tri(pos)
        if t:
            base = len(verts)
            verts.extend(t)
            indices.extend((base, base + 1, base + 2))
            pos += min_gap
        else:
            pos += 1
    return verts, indices


def _valid_mesh(verts, indices):
    # min 8 verts and at least 1 triangle; prefer real props over noise
    if len(verts) < 8 or len(indices) < 3:
        return False
    if len(indices) % 3:
        return False
    return True


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

    best = find_best_vs(raw, scan_from)
    if best:
        verts, vend, note, vstart = best
        ib = find_ib(raw, vend, len(verts), len(verts) - 1)
        if ib and _valid_mesh(verts, ib[0]):
            return MeshGeometry(
                name=name, vertices=verts, indices=ib[0],
                source_offset=vstart, source_size=ib[1] - vstart,
                notes=f"{note} | {ib[2]}",
            )

    loose = find_loose(raw)
    if loose:
        verts, vend, note, vstart, indices, idx_end, idx_note = loose
        if _valid_mesh(verts, indices):
            return MeshGeometry(
                name=name, vertices=verts, indices=indices,
                source_offset=vstart, source_size=idx_end - vstart,
                notes=f"{note} | {idx_note}",
            )

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
                    return MeshGeometry(
                        name=name, vertices=verts, indices=ib[0],
                        source_offset=vstart, source_size=ib[1] - vstart,
                        notes=f"{note} | {ib[2]} | extended",
                    )

    # Legacy raw-triangle fallback (custom/modded meshes exported through a
    # different serialization path than the LOD render data the other
    # branches above expect). Anchored to the mesh's own Bounds so we don't
    # pick up UV/tangent/color garbage from elsewhere in the export.
    bounds = find_bounds(raw)
    if bounds:
        verts, indices = find_triangle_soup(raw, scan_from, bounds)
        if _valid_mesh(verts, indices):
            return MeshGeometry(
                name=name, vertices=verts, indices=indices,
                source_offset=scan_from, source_size=len(raw) - scan_from,
                notes=f"legacy raw-triangle soup n_tris={len(indices)//3}",
            )

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
