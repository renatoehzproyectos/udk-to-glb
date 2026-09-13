// Runs entirely off the main thread. This is the whole point: without it,
// a single slow mesh scan freezes the tab (no scroll, no zoom, no reload)
// for as long as it takes, no matter how many asyncio.sleep(0) yields the
// Python side does — those only yield to *this* thread's event loop, and if
// this thread IS the main thread, "yielding" still competes with painting
// and input. Moving Pyodide here means the main thread is always free.

importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.1/full/pyodide.js");
importScripts("./_sources.js"); // defines EMBEDDED_SOURCES

let pyodidePromise = null;
function getPyodide() {
  if (!pyodidePromise) {
    pyodidePromise = (async () => {
      const pyodide = await loadPyodide();
      pyodide.FS.mkdirTree("/pkg/unreal");
      pyodide.FS.mkdirTree("/pkg/glb");
      for (const [relpath, content] of Object.entries(EMBEDDED_SOURCES)) {
        pyodide.FS.writeFile("/pkg/" + relpath, content);
      }
      await pyodide.runPythonAsync(`
import sys
sys.path.insert(0, "/pkg")
`);
      return pyodide;
    })();
  }
  return pyodidePromise;
}

const RUNNER = `
import io, zipfile, asyncio, json
from unreal.package_reader import UnrealPackage
from unreal.static_mesh import extract_geometry
from unreal.actors import collect_placements
from unreal.inventory import build_manifest
from glb.scene_writer import write_scene_glb

async def run(zip_bytes, say, progress):
    zip_bytes = bytes(zip_bytes)  # JS Uint8Array arrives as a JsProxy; needs an explicit copy to Python bytes

    zin = zipfile.ZipFile(io.BytesIO(zip_bytes))
    udk_name = None
    for n in zin.namelist():
        low = n.lower()
        if low.endswith('.udk') or low.endswith('.upk'):
            udk_name = n
            break
    if udk_name is None:
        raise ValueError("No .udk/.upk file found inside the zip")

    say(f"Found package: {udk_name}")
    await asyncio.sleep(0)
    raw_pkg = zin.read(udk_name)
    with open('/tmp/pkg.udk', 'wb') as f:
        f.write(raw_pkg)

    pkg = UnrealPackage('/tmp/pkg.udk')
    mesh_exports = pkg.find_exports_by_class("StaticMesh")
    say(f"StaticMesh exports: {len(mesh_exports)}")
    await asyncio.sleep(0)

    meshes = {}
    failed = []
    total = len(mesh_exports)
    for i, e in enumerate(mesh_exports):
        progress(i, total, e.object_name)
        raw = pkg.raw_object_data(e)
        try:
            geo = extract_geometry(raw, name=e.object_name, names=pkg.names,
                                    ar_ver=pkg.summary.version,
                                    package_data=pkg.data, serial_offset=e.serial_offset)
            meshes[e.object_name] = (geo.vertices, geo.indices)
            tag = "LOWCONF" if "LOW-CONFIDENCE" in geo.notes else "OK  "
            say(f"  {tag} {e.object_name}: {len(geo.vertices)} verts, {len(geo.indices)//3} tris")
        except ValueError as ex:
            failed.append((e.object_name, str(ex)))
            say(f"  FAIL {e.object_name}: {ex}")
        await asyncio.sleep(0)
    progress(total, total, "")

    if not meshes:
        raise ValueError("No StaticMesh geometry could be extracted")

    nodes = []
    try:
        actors = collect_placements(pkg)
        say(f"Actor placements: {len(actors)}")
        used = set()
        for a in actors:
            if a.mesh_name and a.mesh_name in meshes:
                nodes.append({"name": a.name, "mesh": a.mesh_name,
                              "translation": a.location, "euler": a.rotation, "scale": a.scale})
                used.add(a.mesh_name)
        for mname in meshes:
            if mname not in used:
                nodes.append({"name": mname, "mesh": mname, "translation": (0, 0, 0)})
    except Exception:
        say("Actor placement parsing failed, placing meshes at origin.")
        for mname in meshes:
            nodes.append({"name": mname, "mesh": mname, "translation": (0, 0, 0)})

    await asyncio.sleep(0)
    base_name = udk_name.rsplit('/', 1)[-1]
    base_name = base_name.rsplit('.', 1)[0]

    say("Reading everything else in the package (lights, spawn points, goals, boost pads, materials)...")
    try:
        manifest = build_manifest(pkg)
        say(f"  found {len(manifest['lights'])} lights, "
            f"{sum(len(v) for v in manifest['gameplay_actors'].values())} gameplay actors, "
            f"{len(manifest['materials'])} materials, "
            f"{len(manifest['exports'])} total objects in the package")
    except Exception as ex:
        manifest = None
        say(f"  manifest extraction failed (non-fatal): {ex}")
    await asyncio.sleep(0)

    lights_gltf = []
    if manifest:
        for i, l in enumerate(manifest["lights"]):
            lights_gltf.append({"name": l["name"], "type": l["type"],
                                 "color": l["color"], "intensity": l["intensity"]})
            nodes.append({
                "name": f"Light_{l['name']}_{i}",
                "translation": l["location"],
                "euler": l["rotation"],
                "light": i,
            })
        for category, actors in manifest["gameplay_actors"].items():
            for a in actors:
                nodes.append({
                    "name": f"{category}_{a['name']}",
                    "translation": a["location"],
                    "euler": a["rotation"],
                })

    glb_path = f"/tmp/{base_name}.glb"
    write_scene_glb(glb_path, meshes, nodes, lights=lights_gltf)

    with open(glb_path, 'rb') as f:
        glb_bytes = f.read()

    out_zip = io.BytesIO()
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base_name}.glb", glb_bytes)
        if manifest:
            zf.writestr(f"{base_name}_manifest.json", json.dumps(manifest, indent=2))
    out_zip.seek(0)

    say(f"GLB size: {len(glb_bytes)} bytes")
    say(f"meshes_ok={len(meshes)} nodes={len(nodes)} failed={len(failed)}")
    return base_name, out_zip.getvalue()
`;

self.onmessage = async (event) => {
  const { zipBytes } = event.data;
  try {
    const pyodide = await getPyodide();
    self.postMessage({ type: "ready" });
    await pyodide.runPythonAsync(RUNNER);
    const run = pyodide.globals.get("run");
    const sayLine = (line) => self.postMessage({ type: "log", line });
    const progress = (current, total, meshName) =>
      self.postMessage({ type: "progress", current, total, meshName });
    const result = await run(zipBytes, sayLine, progress);
    const [baseName, outZipBytes] = result.toJs();
    const bytes = new Uint8Array(outZipBytes);
    self.postMessage({ type: "done", baseName, zipBytes: bytes }, [bytes.buffer]);
  } catch (err) {
    self.postMessage({ type: "error", message: String(err) });
  }
};
