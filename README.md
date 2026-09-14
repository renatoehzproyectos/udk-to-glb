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

**Implementado y validado contra Complexityv106.udk:**

1. Parse de paquete UE3/UDK (tag, version, names, imports, exports)
2. Detección de compresión
3. Identificación de exports `StaticMesh` (42 en Complexity)
4. Extracción de VertexStream + IndexBuffer con validación anti-ruido
   (rechaza half-float/bulk degenerados y index buffers triviales)
5. Skip de tagged properties UObject
6. Actors / StaticMeshComponent → mesh ref (+ heurística de posiciones desde PersistentLevel)
7. Clasificación world-space vs local-space por bbox
8. Escritura GLB 2.0 (escena multi-nodo con TRS)

**Resultado en Complexityv106 (2026-09):**
- 41 / 42 StaticMesh con geometría real (1 fallo residual)
- 34 meshes world-space (vértices ya en coordenadas de mapa → nodo en origen)
- 7 meshes local-space instanciados con candidatos de posición del Level
- ~118 nodos en el GLB final
- El bug original (decenas de meshes apilados en 0,0,0) está resuelto para la geometría útil

**No implementado (y no fingido):**

- Texturas / materiales perfectos
- Colisión `.cmf`
- Transforms exactos 1:1 de cada StaticMeshActor (Location tagged no está en el serial
  de este mapa cocido; se usa heurística de candidatos del Level)
- Rotators precisos en todas las instancias
- El mesh residual `simplicity_simplicity_sidewall_001` (sin VS/IB recuperable)

Sin el `.udk` **no se genera ningún GLB del mapa**. No hay placeholders.

## Estado final (Complexityv106)

| Item | Estado |
|------|--------|
| Bug original (meshes apilados en 0,0,0) | **Resuelto** para geometría útil |
| StaticMesh con geometría real | 41 / 42 |
| Escena GLB usable | Sí (`extract_map.py`) |
| Transforms exactos de actores | Heurística (Level candidates) |
| 1 mesh residual | Sin datos de geometría recuperables aquí |

**Qué puede hacer el usuario si necesita fidelidad total:**

1. Usar UModel en Termux/Box64 (ver `tools/umodel_android.md`) para exportar meshes + transforms de referencia.
2. Comparar/ajustar el GLB de este extractor con la salida de UModel.
3. Los transforms tagged no están en el serial de este mapa cocido; solo UModel (o un parser ULevel completo) los resuelve 1:1.

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
