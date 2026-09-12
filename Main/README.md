# RL Mobile Extractor

Convierte un mapa Rocket League (`.udk` / `.upk`) en geometría 3D real (`.glb`).

Diseñado para **Android ARM64 / Termux**. Solo Python 3. Sin GUI. Sin Windows obligatorio.

```
TJBrotherAirDribble.udk  →  RL Mobile Extractor  →  TJBrotherAirDribble.glb
```

## Requisitos

- Python 3
- El archivo `.udk` del mapa (p.ej. `TJBrotherAirDribble.udk`)

```bash
./install.sh
./extract.sh /ruta/a/TJBrotherAirDribble.udk        # un StaticMesh → GLB
./extract.sh /ruta/a/TJBrotherAirDribble.udk --all  # todos + actores → escena
```

## Herramientas

| Comando | Función |
|---------|---------|
| `tools/inspect_package.py` | Header, names, imports, exports, lista StaticMesh |
| `tools/list_exports.py` | Conteo por clase |
| `tools/scan_mesh_raw.py` | Candidatos VertexStream + dump `.bin` |
| `tools/extract_one_mesh.py` | Un mesh → GLB |
| `tools/extract_map.py` | Todos los meshes + transforms → escena GLB |

## Qué hace (y qué no)

**Implementado y listo para el `.udk` real:**

1. Parse de paquete UE3/UDK (tag, version, names, imports, exports)
2. Detección de compresión (este mapa de prueba no comprimía)
3. Identificación de exports `StaticMesh`
4. Extracción de VertexStream (`FStaticMeshVertexStream3`) + IndexBuffer
5. Skip de tagged properties UObject
6. Actors / StaticMeshComponent → Location, Rotation, Scale, mesh ref
7. Escritura GLB 2.0 (un mesh o escena multi-nodo con TRS)

**No implementado (y no fingido):**

- Texturas / materiales perfectos
- Colisión `.cmf`
- Ejecución validada contra `TJBrotherAirDribble.udk` en este entorno (el archivo no está aquí)

Sin el `.udk` **no se genera ningún GLB del mapa**. No hay placeholders.

## Errores

Los fallos indican la etapa:

```
Failed at: package header/names/imports/exports
Failed while parsing StaticMesh serialization (position/vertex stream).
Failed while parsing StaticMesh serialization (index buffer).
```

## Estructura

```
rl-mobile-extractor/
├── extract.sh
├── install.sh
├── README.md
├── src/
│   ├── unreal/
│   │   ├── package_reader.py
│   │   ├── properties.py
│   │   ├── static_mesh.py
│   │   ├── actors.py
│   │   └── bulk.py
│   └── glb/
│       ├── writer.py
│       └── scene_writer.py
└── tools/
    ├── inspect_package.py
    ├── list_exports.py
    ├── scan_mesh_raw.py
    ├── extract_one_mesh.py
    └── extract_map.py
```

## Android / UModel (opcional)

Si tienes UModel + Box64 en Termux, puedes exportar con UModel y usar este repo solo para empaquetar GLB. Ver notas históricas en desarrollo; los downloads oficiales de UModel pueden no estar disponibles.

La ruta principal y definitiva de este proyecto es el parser Python anterior.
